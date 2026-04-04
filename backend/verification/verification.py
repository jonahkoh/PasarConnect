"""
Verification Service — FastAPI application entry point.

Responsibilities:
  • Run DB schema migration (CREATE TABLE IF NOT EXISTS) on startup.
  • Start the async gRPC server inside the FastAPI lifespan.
  • Expose GET /health for the docker-compose health check.

Auth (login / JWT provisioning) is handled by the OutSystems service — not here.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from database import init_db
from grpc_server import start_grpc_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GRPC_PORT = int(os.getenv("VERIFICATION_GRPC_PORT", "50052"))


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
    description="Quota (anti-hoarding) and no-show pattern checks via gRPC. No OutSystems calls.",
    lifespan=lifespan,
)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "verification"}

