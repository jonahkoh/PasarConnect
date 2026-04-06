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

# OUTSYSTEMS_API_URL  — UserAuth base (no API key required for public/login/register)
# OUTSYSTEMS_ADMIN_URL — AdminAuth base (X-API-Key required for approve/reject)
OUTSYSTEMS_API_URL   = os.getenv("OUTSYSTEMS_API_URL", "")
OUTSYSTEMS_ADMIN_URL = os.getenv("OUTSYSTEMS_ADMIN_URL", "")
OUTSYSTEMS_ADMIN_API_KEY = os.getenv("OUTSYSTEMS_ADMIN_API_KEY", "")
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
    Shared helper: calls OutSystems UserAuth /api/auth/login and returns (token, user_id, role).
    UserAuth endpoints require no API key.
    """
    url = f"{OUTSYSTEMS_API_URL}/api/auth/login"
    payload = {"Email": email, "Password": password}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload)
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
    token: str = data.get("AccessToken", "")
    if not token:
        raise HTTPException(status_code=502, detail="OutSystems did not return a token")

    # Decode WITHOUT signature verification — we only need sub + role for the response.
    # Full RS256 signature verification happens in shared/jwt_auth.py on every protected request.
    decoded = pyjwt.decode(token, options={"verify_signature": False})
    user_id = int(decoded.get("sub", 0))
    role = decoded.get("role", "")
    return token, user_id, role


async def _outsystems_register(path: str, body: dict) -> dict:
    """
    Shared helper: forwards a registration payload to an OutSystems UserAuth endpoint.
    UserAuth endpoints require no API key.
    Returns the raw OutSystems response dict on success.
    """
    url = f"{OUTSYSTEMS_API_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=body)
    except httpx.TimeoutException:
        raise HTTPException(status_code=503, detail="OutSystems registration timed out")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"OutSystems unreachable: {exc}")

    if response.status_code not in (200, 201):
        logger.error("OutSystems register failed HTTP %s path=%s", response.status_code, path)
        raise HTTPException(status_code=response.status_code, detail=response.text or "Registration failed")

    # OutSystems register endpoints may return an empty body on success.
    if not response.content:
        return {"message": "Registration successful"}
    try:
        return response.json()
    except Exception:
        return {"message": response.text or "Registration successful"}


async def _outsystems_admin_call(path: str, body: dict) -> dict:
    """
    Shared helper: forwards an admin action to OutSystems AdminAuth.
    AdminAuth endpoints require the X-API-Key header.
    Returns the raw OutSystems response dict on success.
    """
    url = f"{OUTSYSTEMS_ADMIN_URL}{path}"
    headers = {"X-API-Key": OUTSYSTEMS_ADMIN_API_KEY}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=body, headers=headers)
    except httpx.TimeoutException:
        raise HTTPException(status_code=503, detail="OutSystems admin call timed out")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"OutSystems unreachable: {exc}")

    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid or missing admin API key")
    if response.status_code not in (200, 201):
        logger.error("OutSystems admin call failed HTTP %s path=%s", response.status_code, path)
        raise HTTPException(status_code=response.status_code, detail=response.text or "Admin action failed")

    return response.json()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
@app.get("/auth/health")   # Kong routes /auth/* with strip_path:false, so /auth/health arrives here as-is
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


# ── Registration schemas ──────────────────────────────────────────────────────

class PublicRegisterRequest(BaseModel):
    FullName: str
    Email: str
    Password: str
    Phone: str


class CharityRegisterRequest(BaseModel):
    FullName: str
    Email: str
    Password: str
    OrgName: str
    CharityRegNumber: str


class VendorRegisterRequest(BaseModel):
    FullName: str
    Email: str
    Password: str
    BusinessName: str
    NeaLicenceNumber: str
    LicenceExpiry: str   # ISO date string e.g. "2027-01-01"
    Address: str
    Uen: str


# ── Admin action schemas ──────────────────────────────────────────────────────

class AdminActionRequest(BaseModel):
    UserId: int
    RejectionReason: str = ""


# ── Registration endpoints (UserAuth — no API key) ────────────────────────────

@app.post("/auth/public/register", status_code=201)
async def public_register(body: PublicRegisterRequest):
    """Forward public user registration to OutSystems UserAuth."""
    if MOCK_OUTSYSTEMS:
        logger.info("MOCK public register for email=%s", body.Email)
        return {"message": "Registration successful. You can now log in."}

    return await _outsystems_register("/api/auth/public/register", body.model_dump())


@app.post("/auth/charity/register", status_code=201)
async def charity_register(body: CharityRegisterRequest):
    """
    Forward charity registration to OutSystems UserAuth.
    Account is created in pending state — admin must approve before login is allowed.
    """
    if MOCK_OUTSYSTEMS:
        logger.info("MOCK charity register for email=%s", body.Email)
        return {"message": "Registration submitted. Pending admin approval."}

    return await _outsystems_register("/api/auth/charity/register", body.model_dump())


@app.post("/auth/vendor/register", status_code=201)
async def vendor_register(body: VendorRegisterRequest):
    """
    Forward vendor registration to OutSystems UserAuth.
    Account is created in pending state — admin must approve before login is allowed.
    """
    if MOCK_OUTSYSTEMS:
        logger.info("MOCK vendor register for email=%s", body.Email)
        return {"message": "Registration submitted. Pending admin approval."}

    return await _outsystems_register("/api/auth/vendor/register", body.model_dump())


# ── Admin endpoints (AdminAuth — X-API-Key required) ─────────────────────────

@app.post("/admin/charity/approve")
async def admin_approve_charity(body: AdminActionRequest):
    """Approve a pending charity account. Requires OUTSYSTEMS_ADMIN_API_KEY."""
    if MOCK_OUTSYSTEMS:
        logger.info("MOCK approve charity UserId=%s", body.UserId)
        return {"message": f"Charity {body.UserId} approved."}

    return await _outsystems_admin_call("/api/admin/charity/approve", body.model_dump())


@app.post("/admin/charity/reject")
async def admin_reject_charity(body: AdminActionRequest):
    """Reject a pending charity account. Requires OUTSYSTEMS_ADMIN_API_KEY."""
    if MOCK_OUTSYSTEMS:
        logger.info("MOCK reject charity UserId=%s reason=%s", body.UserId, body.RejectionReason)
        return {"message": f"Charity {body.UserId} rejected."}

    return await _outsystems_admin_call("/api/admin/charity/reject", body.model_dump())


@app.post("/admin/vendor/approve")
async def admin_approve_vendor(body: AdminActionRequest):
    """Approve a pending vendor account. Requires OUTSYSTEMS_ADMIN_API_KEY."""
    if MOCK_OUTSYSTEMS:
        logger.info("MOCK approve vendor UserId=%s", body.UserId)
        return {"message": f"Vendor {body.UserId} approved."}

    return await _outsystems_admin_call("/api/admin/vendor/approve", body.model_dump())


@app.post("/admin/vendor/reject")
async def admin_reject_vendor(body: AdminActionRequest):
    """Reject a pending vendor account. Requires OUTSYSTEMS_ADMIN_API_KEY."""
    if MOCK_OUTSYSTEMS:
        logger.info("MOCK reject vendor UserId=%s reason=%s", body.UserId, body.RejectionReason)
        return {"message": f"Vendor {body.UserId} rejected."}

    return await _outsystems_admin_call("/api/admin/vendor/reject", body.model_dump())
