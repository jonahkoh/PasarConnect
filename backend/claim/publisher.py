"""
Best-effort RabbitMQ publisher.
Failure to publish does NOT fail the claim — it just logs a warning.
Consumers: Notification Service, Auditor Service.
"""
import os
import json
import logging
import pika

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
EXCHANGE_NAME = "foodloop"

logger = logging.getLogger(__name__)


def publish_claim_success(claim_id: int, listing_id: int, charity_id: int) -> None:
    """
    Publishes a claim.success event to the 'foodloop' topic exchange.
    Uses a short-lived blocking connection (acceptable for low-volume events).
    """
    message = {
        "event":      "claim.success",
        "claim_id":   claim_id,
        "listing_id": listing_id,
        "charity_id": charity_id,
    }
    try:
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=RABBITMQ_HOST, connection_attempts=2, retry_delay=1)
        )
        channel = connection.channel()
        channel.exchange_declare(exchange=EXCHANGE_NAME, exchange_type="topic", durable=True)
        channel.basic_publish(
            exchange    = EXCHANGE_NAME,
            routing_key = "claim.success",
            body        = json.dumps(message),
            properties  = pika.BasicProperties(delivery_mode=2),  # persistent
        )
        connection.close()
        logger.info("Published claim.success for claim_id=%s", claim_id)
    except Exception as exc:
        # Non-fatal: log and continue so the claim is not rolled back.
        logger.warning("RabbitMQ publish failed (claim_id=%s): %s", claim_id, exc)
