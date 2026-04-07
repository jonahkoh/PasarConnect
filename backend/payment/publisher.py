"""
Async RabbitMQ publisher using aio-pika.

Publishes payment.failure and payment.success events to the 'PasarConnect'
topic exchange so the Auditor Service (and any future subscribers) can react.

Failure to publish is NON-FATAL — the compensating transaction (refund) has
already been executed.  We log the error so ops can investigate.
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


async def _publish(routing_key: str, message_body: dict) -> None:
    """Internal helper — opens a connection, publishes one message, closes."""
    try:
        connection = await aio_pika.connect_robust(
            f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}/"
        )
        async with connection:
            channel  = await connection.channel()
            exchange = await channel.declare_exchange(
                EXCHANGE_NAME,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
            )
            await exchange.publish(
                aio_pika.Message(
                    body          = json.dumps(message_body).encode(),
                    delivery_mode = aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=routing_key,
            )
        logger.info("Published %s — %s", routing_key, message_body)
    except Exception as exc:
        logger.warning("RabbitMQ publish failed (%s): %s", routing_key, exc)


async def publish_payment_success(
    transaction_id: str,
    listing_id: int,
    user_id: int,
) -> None:
    """
    Buyer's card was charged and the listing is now SOLD_PENDING_COLLECTION.
    Routing key: payment.success
    Receivers: listing:{listing_id} (vendor) + user:{user_id} (buyer confirmation).
    """
    await _publish(
        "payment.success",
        {
            "event"          : "payment.success",
            "transaction_id" : transaction_id,
            "listing_id"     : listing_id,
            "user_id"        : user_id,
        },
    )


async def publish_payment_collected(
    transaction_id: str,
    listing_id: int,
) -> None:
    """
    Vendor approved collection — listing is now SOLD.
    Routing key: payment.collected
    Receivers: listing:{listing_id} (vendor dashboard update).
    """
    await _publish(
        "payment.collected",
        {
            "event"          : "payment.collected",
            "transaction_id" : transaction_id,
            "listing_id"     : listing_id,
        },
    )


async def publish_payment_refunded(
    transaction_id: str,
    listing_id: int,
    user_id: int,
    reason: str,
) -> None:
    """
    Payment was refunded (vendor reject OR noshow within window).
    Routing key: payment.refunded
    Receivers: user:{user_id} (buyer) + listing:{listing_id} (vendor + watchers).
    """
    await _publish(
        "payment.refunded",
        {
            "event"          : "payment.refunded",
            "transaction_id" : transaction_id,
            "listing_id"     : listing_id,
            "user_id"        : user_id,
            "reason"         : reason,
        },
    )


async def publish_payment_cancelled(
    transaction_id: str,
    listing_id: int,
    user_id: int,
) -> None:
    """
    User cancelled within the cancellation window.
    Routing key: payment.cancelled
    Receivers: user:{user_id} (buyer confirmation) + listing:{listing_id}.
    """
    await _publish(
        "payment.cancelled",
        {
            "event"          : "payment.cancelled",
            "transaction_id" : transaction_id,
            "listing_id"     : listing_id,
            "user_id"        : user_id,
        },
    )


async def publish_payment_forfeited(
    transaction_id: str,
    listing_id: int,
    user_id: int,
) -> None:
    """
    Vendor recorded a no-show past the leniency window — payment forfeited.
    Routing key: payment.forfeited
    Receivers: user:{user_id} (buyer notification) + listing:{listing_id}.
    """
    await _publish(
        "payment.forfeited",
        {
            "event"          : "payment.forfeited",
            "transaction_id" : transaction_id,
            "listing_id"     : listing_id,
            "user_id"        : user_id,
        },
    )


async def publish_payment_failure(
    transaction_id: str,
    listing_id: int,
    reason: str,
) -> None:
    """
    Unexpected system error during payment processing (compensating transaction).
    Routing key: payment.failure — ops/auditor only, no user-facing socket emit.
    """
    await _publish(
        "payment.failure",
        {
            "event"          : "payment.failure",
            "transaction_id" : transaction_id,
            "listing_id"     : listing_id,
            "reason"         : reason,
        },
    )


async def publish_payment_arrived(
    transaction_id: str,
    listing_id: int,
    user_id: int,
) -> None:
    """
    Buyer has arrived on-site and is ready for item collection.
    Routing key: payment.arrived
    Receivers: listing:{listing_id} (vendor gets notified to confirm/reject).
    """
    await _publish(
        "payment.arrived",
        {
            "event"          : "payment.arrived",
            "transaction_id" : transaction_id,
            "listing_id"     : listing_id,
            "user_id"        : user_id,
        },
    )
