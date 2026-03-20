from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from grpc_server import start_grpc_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GRPC_PORT = int(os.getenv("VERIFICATION_GRPC_PORT", "50052"))


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