from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# ── Key loading ───────────────────────────────────────────────────────────────
# Read once at startup via lru_cache — never re-read on every request.
# PUBLIC_KEY_PATH is injected via environment variable in docker-compose.

_bearer = HTTPBearer()


@lru_cache(maxsize=1)
def _load_public_key() -> str:
    path = os.environ["PUBLIC_KEY_PATH"]
    with open(path, "r") as fh:
        return fh.read()


# ── Dependency ────────────────────────────────────────────────────────────────

async def verify_jwt_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Security(_bearer)],
) -> dict:
    """
    FastAPI dependency — verifies an RS256 JWT from the Authorization header.

    Usage:
        @app.post("/claims")
        async def create_claim(
            body: ClaimCreate,
            token_payload: Annotated[dict, Depends(verify_jwt_token)],
        ): ...

    Returns the decoded JWT payload dict on success.
    Raises HTTP 401 on any verification failure.
    """
    try:
        payload = jwt.decode(
            credentials.credentials,
            _load_public_key(),
            algorithms=["RS256"],
            options={"require": ["exp", "iat", "sub"]},
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")