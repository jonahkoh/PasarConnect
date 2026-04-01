"""
Best-effort RabbitMQ publisher.
Failure to publish does NOT fail the claim — it just logs a warning.
Consumers: Notification Service, Auditor Service.
"""
import json
import logging
import os

import aio_pika

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
EXCHANGE_NAME = "PasarConnect"

logger = logging.getLogger(__name__)


async def _publish(routing_key: str, payload: dict) -> None:
    """Publish a durable JSON event to RabbitMQ; logs warning on any failure."""
    try:
        connection = await aio_pika.connect_robust(f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}/")
        async with connection:
            channel = await connection.channel()
            exchange = await channel.declare_exchange(
                EXCHANGE_NAME,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
            )

            await exchange.publish(
                aio_pika.Message(
                    body=json.dumps(payload).encode("utf-8"),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    content_type="application/json",
                ),
                routing_key=routing_key,
            )
            logger.info("Published %s event", routing_key)
    except Exception as exc:
        logger.warning("RabbitMQ publish failed (routing_key=%s): %s", routing_key, exc)


async def publish_claim_success(claim_id: int, listing_id: int, charity_id: int) -> None:
    payload = {
        "event": "claim.success",
        "claim_id": claim_id,
        "listing_id": listing_id,
        "charity_id": charity_id,
    }
    await _publish("claim.success", payload)


async def publish_claim_failure(listing_id: int, charity_id: int, reason: str) -> None:
    payload = {
        "event": "claim.failure",
        "listing_id": listing_id,
        "charity_id": charity_id,
        "reason": reason,
    }
    await _publish("claim.failure", payload)


async def publish_claim_cancelled(claim_id: int, listing_id: int, charity_id: int) -> None:
    """
    Fired when a charity cancels their active claim and the waitlist is empty.
    Auditor Service logs it; Notification Service may alert nearby charities.
    """
    payload = {
        "event": "claim.cancelled",
        "claim_id": claim_id,
        "listing_id": listing_id,
        "charity_id": charity_id,
    }
    await _publish("claim.cancelled", payload)


async def publish_waitlist_promoted(claim_id: int, listing_id: int, charity_id: int) -> None:
    """
    Fired when the waitlist system auto-assigns a listing to the next eligible charity.

    Notification Service consumes routing key 'claim.waitlist.promoted' and sends
    a WebSocket message directly to the promoted charity's session:

      "Great news! The item you were waiting for has been reserved for you.
       Head to the app to confirm your collection."

    Auditor Service also consumes this for compliance logging.
    """
    payload = {
        "event": "claim.waitlist.promoted",
        "claim_id": claim_id,
        "listing_id": listing_id,
        "charity_id": charity_id,           # Notification Service targets this charity's WS session
        "message": (
            "Great news! The item you were waiting for has been reserved for you. "
            "Head to the app to confirm your collection."
        ),
    }
    await _publish("claim.waitlist.promoted", payload)
