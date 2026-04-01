from __future__ import annotations

import logging

import grpc

import verification_pb2
import verification_pb2_grpc
from outsystems_client import OutSystemsVerificationError, check_charity_eligibility

logger = logging.getLogger(__name__)


# ── Servicer ──────────────────────────────────────────────────────────────────

class VerificationServicer(verification_pb2_grpc.VerificationServiceServicer):
    """
    Implements the VerifyCharity RPC defined in verification.proto.

    Flow:
        1. Receive VerifyRequest(charity_id, listing_id) from Claim Service
        2. Call OutSystems REST API via outsystems_client
        3. Return VerifyResponse(approved, rejection_reason)

    Error mapping:
        OutSystemsVerificationError  →  gRPC UNAVAILABLE  (503 equivalent)
        Any unexpected exception     →  gRPC INTERNAL     (500 equivalent)
    """

    async def VerifyCharity(
        self,
        request: verification_pb2.VerifyRequest,
        context: grpc.aio.ServicerContext,
    ) -> verification_pb2.VerifyResponse:

        logger.info(
            "VerifyCharity called charity_id=%s listing_id=%s",
            request.charity_id,
            request.listing_id,
        )

        try:
            approved, rejection_reason = await check_charity_eligibility(
                charity_id=request.charity_id,
                listing_id=request.listing_id,
            )
            return verification_pb2.VerifyResponse(
                approved=approved,
                rejection_reason=rejection_reason,
            )

        except OutSystemsVerificationError as exc:
            # OutSystems is down or timed out — claim flow must not proceed
            logger.error(
                "OutSystems unavailable for charity_id=%s: %s",
                request.charity_id,
                exc,
            )
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                f"Verification service unavailable: {exc}",
            )

        except Exception as exc:
            # Unexpected error — log and surface as INTERNAL
            logger.exception(
                "Unexpected error in VerifyCharity charity_id=%s: %s",
                request.charity_id,
                exc,
            )
            await context.abort(
                grpc.StatusCode.INTERNAL,
                "Internal verification error",
            )


# ── Server factory ────────────────────────────────────────────────────────────

async def start_grpc_server(host: str = "0.0.0.0", port: int = 50052) -> grpc.aio.Server:
    """
    Creates, configures, and starts the async gRPC server.
    Called from main.py lifespan on startup.
    Returns the running server instance so lifespan can stop it on shutdown.
    """
    server = grpc.aio.server()

    verification_pb2_grpc.add_VerificationServiceServicer_to_server(
        VerificationServicer(), server
    )

    listen_addr = f"{host}:{port}"
    server.add_insecure_port(listen_addr)

    await server.start()
    logger.info("Verification gRPC server listening on %s", listen_addr)

    return server