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


async def publish_payment_success(transaction_id: str, listing_id: int) -> None:
    """Publishes a payment.success event.  Routing key: payment.success"""
    await _publish(
        "payment.success",
        {
            "event"          : "payment.success",
            "transaction_id" : transaction_id,
            "listing_id"     : listing_id,
        },
    )


async def publish_payment_failure(
    transaction_id: str,
    listing_id: int,
    reason: str,
) -> None:
    """Publishes a payment.failure event.  Routing key: payment.failure"""
    await _publish(
        "payment.failure",
        {
            "event"          : "payment.failure",
            "transaction_id" : transaction_id,
            "listing_id"     : listing_id,
            "reason"         : reason,
        },
    )
