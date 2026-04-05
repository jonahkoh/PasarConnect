from __future__ import annotations

import logging
import os
from typing import Any

import grpc
import httpx
import jwt as pyjwt
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# OutSystems login endpoint — returns a signed JWT on successful charity login
OUTSYSTEMS_API_URL = os.getenv("OUTSYSTEMS_API_URL", "")
OUTSYSTEMS_API_KEY = os.getenv("OUTSYSTEMS_API_KEY", "")
_TIMEOUT_SECONDS = float(os.getenv("OUTSYSTEMS_TIMEOUT_SECONDS", "5.0"))
MOCK_OUTSYSTEMS = os.getenv("MOCK_OUTSYSTEMS", "false").lower() == "true"

VERIFICATION_GRPC_HOST = os.getenv("VERIFICATION_GRPC_HOST", "localhost")
VERIFICATION_GRPC_PORT = os.getenv("VERIFICATION_GRPC_PORT", "50052")

# ── Schemas ───────────────────────────────────────────────────────────────────

# All three user types share the same login fields — email + password.
class LoginRequest(BaseModel):
    email: str
    password: str


# Backward-compat aliases so existing callers don't need renaming.
CharityLoginRequest = LoginRequest
VendorLoginRequest  = LoginRequest
PublicLoginRequest  = LoginRequest


class CharityLoginResponse(BaseModel):
    access_token: str           # RS256 JWT signed by OutSystems
    token_type: str = "bearer"
    user_id: int                # decoded from JWT 'sub'
    role: str                   # decoded from JWT 'role' claim — always "charity"
    status: dict[str, Any] | None = None  # CharityStanding from verification service


class VendorLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int                # decoded from JWT 'sub'
    role: str                   # decoded from JWT 'role' claim — always "vendor"
    status: dict[str, Any] | None = None  # VendorStanding from verification service


class PublicLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int                # decoded from JWT 'sub'
    role: str                   # decoded from JWT 'role' claim — always "public"


# Pydantic v2 + `from __future__ import annotations` defers annotation evaluation;
# model_rebuild() forces resolution of `Any` in the dict[str, Any] fields.
CharityLoginResponse.model_rebuild()
VendorLoginResponse.model_rebuild()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PasarConnect — OutSystems Auth Wrapper",
    description="HTTP wrapper for OutSystems auth. Issues JWTs for charity, vendor, and public users.",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_charity_status_grpc(charity_id: int) -> dict[str, Any]:
    """
    Calls GetCharityStatus on the verification gRPC service.
    Returns a default 'good standing' dict on any failure so login is never blocked
    by a verification service outage.
    """
    if MOCK_OUTSYSTEMS:
        return {
            "is_banned":      False,
            "ban_reason":     "",
            "cooldown_until": None,
            "warning_count":  0,
            "recent_noshows": 0,
            "claimed_today":  0,
            "appeal_status":  "NONE",
        }

    try:
        import verification_pb2
        import verification_pb2_grpc

        addr = f"{VERIFICATION_GRPC_HOST}:{VERIFICATION_GRPC_PORT}"
        async with grpc.aio.insecure_channel(addr) as channel:
            stub = verification_pb2_grpc.VerificationServiceStub(channel)
            resp = await stub.GetCharityStatus(
                verification_pb2.CharityStatusRequest(charity_id=charity_id)
            )
        return {
            "is_banned":      resp.is_banned,
            "ban_reason":     resp.ban_reason,
            "cooldown_until": resp.cooldown_until or None,
            "warning_count":  resp.warning_count,
            "recent_noshows": resp.recent_noshows,
            "claimed_today":  resp.claimed_today,
            "appeal_status":  resp.appeal_status,
        }
    except Exception as exc:
        logger.warning("Could not fetch charity status from verification service: %s", exc)
        return {
            "is_banned":      False,
            "ban_reason":     "",
            "cooldown_until": None,
            "warning_count":  0,
            "recent_noshows": 0,
            "claimed_today":  0,
            "appeal_status":  "NONE",
        }


async def _get_vendor_status_grpc(vendor_id: int) -> dict[str, Any]:
    """
    Calls GetVendorStatus on the verification gRPC service.
    Returns a default 'compliant' dict on any failure so login is never blocked
    by a verification service outage.
    """
    if MOCK_OUTSYSTEMS:
        return {
            "is_compliant":     True,
            "compliance_flag":  "",
            "license_expires_at": "",
        }

    try:
        import verification_pb2
        import verification_pb2_grpc

        addr = f"{VERIFICATION_GRPC_HOST}:{VERIFICATION_GRPC_PORT}"
        async with grpc.aio.insecure_channel(addr) as channel:
            stub = verification_pb2_grpc.VerificationServiceStub(channel)
            resp = await stub.GetVendorStatus(
                verification_pb2.VendorStatusRequest(vendor_id=vendor_id)
            )
        return {
            "is_compliant":       resp.is_compliant,
            "compliance_flag":    resp.compliance_flag,
            "license_expires_at": resp.license_expires_at or "",
        }
    except Exception as exc:
        logger.warning("Could not fetch vendor status from verification service: %s", exc)
        return {
            "is_compliant":     True,
            "compliance_flag":  "",
            "license_expires_at": "",
        }


async def _outsystems_login(email: str, password: str) -> tuple[str, int, str]:
    """
    Shared helper: calls OutSystems /api/auth/login and returns (token, user_id, role).

    Raises HTTPException on any failure so individual endpoints stay clean.
    The 'role' value comes from the JWT payload — OutSystems sets it to
    "charity", "vendor", or "public" based on the account type.
    """
    url = f"{OUTSYSTEMS_API_URL}/api/auth/login"
    headers = {"X-API-Key": OUTSYSTEMS_API_KEY}
    payload = {"Email": email, "Password": password}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException:
        raise HTTPException(status_code=503, detail="OutSystems login timed out")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"OutSystems unreachable: {exc}")

    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if response.status_code == 403:
        # OutSystems returns 403 when the account is pending admin approval.
        raise HTTPException(status_code=403, detail="Account pending approval")
    if response.status_code != 200:
        logger.error("OutSystems login failed HTTP %s for email=%s", response.status_code, email)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    data = response.json()
    # OutSystems REST actions use PascalCase field names.
    token: str = data.get("AccessToken", "")
    if not token:
        raise HTTPException(status_code=502, detail="OutSystems did not return a token")

    # Decode WITHOUT signature verification — we only need sub + role for the response.
    # Full RS256 signature verification happens in shared/jwt_auth.py on every protected request.
    decoded = pyjwt.decode(token, options={"verify_signature": False})
    user_id = int(decoded.get("sub", 0))
    role = decoded.get("role", "")
    return token, user_id, role


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "outsystems"}


@app.post("/auth/charity/login", response_model=CharityLoginResponse)
async def charity_login(body: LoginRequest):
    """
    Charity login — validates credentials via OutSystems, enriches response with
    the charity's current standing (quota usage, bans, cooldowns) from the
    Verification service.
    """
    if MOCK_OUTSYSTEMS:
        logger.info("MOCK charity login for email=%s", body.email)
        status = await _get_charity_status_grpc(charity_id=1)
        return CharityLoginResponse(
            access_token="mock.charity.token",
            user_id=1,
            role="charity",
            status=status,
        )

    token, user_id, role = await _outsystems_login(body.email, body.password)
    status = await _get_charity_status_grpc(charity_id=user_id)
    return CharityLoginResponse(access_token=token, user_id=user_id, role=role, status=status)


@app.post("/auth/vendor/login", response_model=VendorLoginResponse)
async def vendor_login(body: LoginRequest):
    """
    Vendor login — validates credentials via OutSystems, enriches response with
    the vendor's NEA licence compliance status from the Verification service.
    """
    if MOCK_OUTSYSTEMS:
        logger.info("MOCK vendor login for email=%s", body.email)
        status = await _get_vendor_status_grpc(vendor_id=1)
        return VendorLoginResponse(
            access_token="mock.vendor.token",
            user_id=1,
            role="vendor",
            status=status,
        )

    token, user_id, role = await _outsystems_login(body.email, body.password)
    status = await _get_vendor_status_grpc(vendor_id=user_id)
    return VendorLoginResponse(access_token=token, user_id=user_id, role=role, status=status)


@app.post("/auth/public/login", response_model=PublicLoginResponse)
async def public_login(body: LoginRequest):
    """
    Public user login — validates credentials via OutSystems.
    No status enrichment needed: public users have no quota or compliance checks.
    """
    if MOCK_OUTSYSTEMS:
        logger.info("MOCK public login for email=%s", body.email)
        return PublicLoginResponse(
            access_token="mock.public.token",
            user_id=1,
            role="public",
        )

    token, user_id, role = await _outsystems_login(body.email, body.password)
    return PublicLoginResponse(access_token=token, user_id=user_id, role=role)
