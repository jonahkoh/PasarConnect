"""
Verification Service — FastAPI application entry point.

Responsibilities:
  • Start / stop the async gRPC server inside the FastAPI lifespan.
  • Run DB schema migration (CREATE TABLE IF NOT EXISTS) on startup.
  • Expose HTTP endpoints:
      GET  /health            — liveness probe
      POST /auth/charity/login — proxy charity credentials to OutSystems
                                 and return the signed JWT to the client.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import httpx
import jwt as pyjwt
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from database import init_db
from grpc_server import start_grpc_server
from outsystems_client import MOCK_OUTSYSTEMS, OUTSYSTEMS_API_KEY, OUTSYSTEMS_API_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GRPC_PORT        = int(os.getenv("VERIFICATION_GRPC_PORT", "50052"))
_TIMEOUT_SECONDS = float(os.getenv("OUTSYSTEMS_TIMEOUT_SECONDS", "5.0"))


# ── Schemas ───────────────────────────────────────────────────────────────────

class CharityLoginRequest(BaseModel):
    email:    str
    password: str


class CharityLoginResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    charity_id:   int


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initialising Verification DB schema...")
    await init_db()

    logger.info("Starting Verification gRPC server on port %s", GRPC_PORT)
    grpc_server = await start_grpc_server(port=GRPC_PORT)

    yield

    logger.info("Stopping Verification gRPC server...")
    await grpc_server.stop(grace=5)


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PasarConnect — Verification Service",
    description="Quota enforcement + OutSystems legal checks. Exposes gRPC on port 50052.",
    lifespan=lifespan,
)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "verification"}


@app.post("/auth/charity/login", response_model=CharityLoginResponse)
async def charity_login(body: CharityLoginRequest):
    """
    Step 1 of the charity auth flow.

    Forwards email + password to OutSystems, which validates the account
    and returns a signed RS256 JWT.  We decode the JWT without verification
    only to extract the charity_id from the 'sub' claim for UI convenience.

    The token is stored client-side and attached as 'Authorization: Bearer <token>'
    to every subsequent call to the Claim Service.

    MOCK MODE (MOCK_OUTSYSTEMS=true):
    Returns a placeholder token for local dev without real OutSystems access.
    """
    if MOCK_OUTSYSTEMS:
        logger.info("MOCK login for email=%s", body.email)
        return CharityLoginResponse(access_token="mock.jwt.token", charity_id=1)

    url     = f"{OUTSYSTEMS_API_URL}/api/charity/login"
    headers = {"X-API-Key": OUTSYSTEMS_API_KEY}
    payload = {"email": body.email, "password": body.password}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            logger.warning(
                "OutSystems login returned HTTP %s for email=%s",
                response.status_code, body.email,
            )
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials or OutSystems error",
            )

        data  = response.json()
        token = data.get("access_token") or data.get("token") or ""
        if not token:
            raise HTTPException(status_code=502, detail="OutSystems returned no token")

        # Decode without verification — we trust OutSystems' RS256 signature
        claims     = pyjwt.decode(token, options={"verify_signature": False})
        charity_id = int(claims.get("sub", 0))

        return CharityLoginResponse(access_token=token, charity_id=charity_id)

    except httpx.TimeoutException:
        raise HTTPException(status_code=503, detail="OutSystems login timed out")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"OutSystems HTTP error: {exc}")
