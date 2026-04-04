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

class CharityLoginRequest(BaseModel):
    email: str
    password: str


class CharityLoginResponse(BaseModel):
    access_token: str           # RS256 JWT signed by OutSystems
    token_type: str = "bearer"
    charity_id: int             # decoded from JWT 'sub' for client convenience
    status: dict[str, Any] | None = None  # CharityStanding from verification service


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


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "outsystems"}


@app.post("/auth/charity/login", response_model=CharityLoginResponse)
async def charity_login(body: CharityLoginRequest):
    """
    Step 1 of the whole auth flow.

    The charity's app/browser calls this endpoint with email + password.
    This service forwards the credentials to OutSystems, which:
      - Validates the charity account
      - Signs a JWT with OutSystems' private key (RS256)
      - Returns the signed JWT back

    We decode the JWT (without verifying — we trust OutSystems here) only to
    extract the charity_id from the 'sub' claim and then call the verification
    service to enrich the response with the charity's current standing.

    MOCK MODE (MOCK_OUTSYSTEMS=true):
    Returns a hardcoded mock token for local dev without real OutSystems access.
    """
    if MOCK_OUTSYSTEMS:
        logger.info("MOCK login for email=%s", body.email)
        mock_token = "mock.jwt.token"
        status = await _get_charity_status_grpc(charity_id=1)
        return CharityLoginResponse(
            access_token=mock_token,
            charity_id=1,
            status=status,
        )

    # ── Real OutSystems call ───────────────────────────────────────────────────
    # OutSystems exposes a REST login action that validates credentials and
    # returns a signed JWT.  The exact endpoint path must match what your
    # groupmate configured in the OutSystems module.
    #
    # CONFIRM with OutSystems groupmate:
    #   - Exact URL path (currently /api/auth/login)
    #   - Request field names (currently Email/Password — verify casing)
    #   - Response field name for the JWT (currently "access")
    url = f"{OUTSYSTEMS_API_URL}/api/auth/login"
    headers = {"X-API-Key": OUTSYSTEMS_API_KEY}
    # Field names must match OutSystems REST input parameter names exactly.
    # OutSystems typically uses PascalCase for REST parameters — confirm with groupmate.
    payload = {"Email": body.email, "Password": body.password}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            logger.error("OutSystems login failed HTTP %s for email=%s", response.status_code, body.email)
            raise HTTPException(status_code=401, detail="Invalid credentials")

        data = response.json()
        # OutSystems returns the JWT under the "access" key.
        # Confirm with the OutSystems groupmate if the key name changes.
        token: str = data.get("access")
        if not token:
            raise HTTPException(status_code=502, detail="OutSystems did not return a token")

        # Decode WITHOUT verification — we just want the sub claim for the response.
        # The real signature verification happens in shared/jwt_auth.py on every request.
        decoded = pyjwt.decode(token, options={"verify_signature": False})
        charity_id = int(decoded.get("sub", 0))

        status = await _get_charity_status_grpc(charity_id=charity_id)

        return CharityLoginResponse(access_token=token, charity_id=charity_id, status=status)

    except httpx.TimeoutException:
        raise HTTPException(status_code=503, detail="OutSystems login timed out")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"OutSystems unreachable: {exc}")

        if not token:
            raise HTTPException(status_code=502, detail="OutSystems did not return a token")

        # Decode WITHOUT verification — we just want the sub claim for the response.
        # The real signature verification happens in shared/jwt_auth.py on every request.
        decoded = pyjwt.decode(token, options={"verify_signature": False})
        charity_id = int(decoded.get("sub", 0))

        return CharityLoginResponse(access_token=token, charity_id=charity_id)

    except httpx.TimeoutException:
        raise HTTPException(status_code=503, detail="OutSystems login timed out")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"OutSystems unreachable: {exc}")