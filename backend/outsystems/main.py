from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import httpx
import jwt as pyjwt
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from grpc_server import start_grpc_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GRPC_PORT = int(os.getenv("VERIFICATION_GRPC_PORT", "50052"))

# OutSystems login endpoint — returns a signed JWT on successful charity login
OUTSYSTEMS_API_URL = os.getenv("OUTSYSTEMS_API_URL", "")
OUTSYSTEMS_API_KEY = os.getenv("OUTSYSTEMS_API_KEY", "")
_TIMEOUT_SECONDS = float(os.getenv("OUTSYSTEMS_TIMEOUT_SECONDS", "5.0"))
MOCK_OUTSYSTEMS = os.getenv("MOCK_OUTSYSTEMS", "false").lower() == "true"

# ── Request / Response schemas ─────────────────────────────────────────────────

class CharityLoginRequest(BaseModel):
    """Credentials the charity submits to log in."""
    email: str
    password: str


class CharityLoginResponse(BaseModel):
    """Returned to the client after a successful OutSystems login."""
    access_token: str   # RS256 JWT signed by OutSystems — pass as Authorization: Bearer <token>
    token_type: str = "bearer"
    charity_id: int     # decoded from the JWT 'sub' claim for convenience



# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Starts the gRPC server on the same event loop as FastAPI.
    Mirrors the pattern used in inventory/inventory.py.
    """
    logger.info("Starting Verification gRPC server on port %s", GRPC_PORT)
    grpc_server = await start_grpc_server(port=GRPC_PORT)

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Stopping Verification gRPC server...")
    await grpc_server.stop(grace=5)


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PasarConnect — Verification Service",
    description="Stateless gatekeeper. Proxies charity eligibility checks to OutSystems.",
    lifespan=lifespan,
)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "verification"}


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
    extract the charity_id from the 'sub' claim and return it alongside the
    token for UI convenience.

    The token is then stored client-side (browser localStorage or app memory)
    and attached as 'Authorization: Bearer <token>' on every subsequent request
    to the claim service.

    MOCK MODE (MOCK_OUTSYSTEMS=true):
    Returns a hardcoded mock token for local dev without real OutSystems access.
    """
    if MOCK_OUTSYSTEMS:
        # In mock mode, return a placeholder token string.
        # The real public key in keys/public.pem won't verify this — it's just
        # for wiring up the UI flow during development.
        logger.info("MOCK login for email=%s", body.email)
        mock_token = "mock.jwt.token"
        return CharityLoginResponse(
            access_token=mock_token,
            charity_id=1,
        )

    # ── Real OutSystems call ───────────────────────────────────────────────────
    # OutSystems exposes a REST login action that validates credentials and
    # returns a signed JWT.  The exact endpoint path must match what your
    # groupmate configured in the OutSystems module.
    url = f"{OUTSYSTEMS_API_URL}/api/charity/login"   # placeholder — replace with real path
    headers = {"X-API-Key": OUTSYSTEMS_API_KEY}
    payload = {"email": body.email, "password": body.password}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            logger.error("OutSystems login failed HTTP %s for email=%s", response.status_code, body.email)
            raise HTTPException(status_code=401, detail="Invalid credentials")

        data = response.json()
        # OutSystems returns the JWT under a key — adjust field name to match
        # your OutSystems module's output parameter name.
        token: str = data.get("token") or data.get("access_token") or data.get("jwt")
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