import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated

import aio_pika
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from shared.jwt_auth import verify_jwt_token

import inventory_client

load_dotenv()

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")

EVENT_EXCHANGE = "pasarconnect.events"
EVENT_ROUTING_KEY = "listing.created"
ERROR_ROUTING_KEY = "listing.failed"    # published when listing creation partially fails
DELAY_QUEUE = "listing.delay.window"    # name is TTL-agnostic; actual TTL driven by QUEUE_WINDOW_MINUTES
# TTL derived from the same env var as Claim/Payment Services so all three stay in sync.
_QUEUE_WINDOW_MINUTES = float(os.getenv("QUEUE_WINDOW_MINUTES", "5"))
DELAY_TTL_MS = int(_QUEUE_WINDOW_MINUTES * 60 * 1000)
DLX_EXCHANGE = "pasarconnect.dlx"      # dead-letter exchange — receives messages after TTL
DLX_ROUTING_KEY = "listing.window.closed"  # key used when delay queue dead-letters a message

# Shared RabbitMQ connection + channel + exchange — held open for the app lifetime (Gap 7 fix)
_mq_connection: aio_pika.abc.AbstractRobustConnection | None = None
_mq_channel: aio_pika.abc.AbstractChannel | None = None
_mq_exchange: aio_pika.abc.AbstractExchange | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _mq_connection, _mq_channel, _mq_exchange
    _mq_connection = await aio_pika.connect_robust(
        f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}/"
    )
    _mq_channel = await _mq_connection.channel()
    # Pre-declare exchanges and store the event exchange object for publishing
    _mq_exchange = await _mq_channel.declare_exchange(EVENT_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
    await _mq_channel.declare_exchange(DLX_EXCHANGE,   aio_pika.ExchangeType.TOPIC, durable=True)
    await _mq_channel.declare_queue(
        DELAY_QUEUE,
        durable=True,
        arguments={
            "x-message-ttl": DELAY_TTL_MS,
            "x-dead-letter-exchange": DLX_EXCHANGE,
            "x-dead-letter-routing-key": DLX_ROUTING_KEY,
        },
    )
    yield
    await _mq_connection.close()


app = FastAPI(title="PasarConnect - Listing Service", lifespan=lifespan)


class ListingCreateRequest(BaseModel):
    # vendor_id is no longer in the body — it is extracted from the JWT sub claim.
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    quantity: int | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    expiry: datetime
    image_url: str = Field(..., min_length=1, max_length=1024)
    price: float | None = Field(default=None, gt=0)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("expiry")
    @classmethod
    def expiry_must_be_future(cls, v: datetime) -> datetime:
        from datetime import timezone as _tz
        v_utc = v if v.tzinfo else v.replace(tzinfo=_tz.utc)
        if v_utc <= datetime.now(tz=_tz.utc):
            raise ValueError("expiry must be in the future")
        return v

    @model_validator(mode="after")
    def validate_pairs(self):
        if self.quantity is None and self.weight_kg is None:
            raise ValueError("Either quantity or weight_kg must be provided")
        return self


class ListingCreateResponse(BaseModel):
    listing_id: int
    listed_at: str  # ISO-8601 UTC timestamp when the listing was created in Inventory


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "listing"}


async def _publish_error_event(error_type: str, detail: str, listing_id: int | None = None) -> None:
    """
    Publish a listing.error event to pasarconnect.events so the notification
    service /debug/messages endpoint captures failures for easier debugging.
    Best-effort: silently skips if the MQ channel is not available.
    """
    if _mq_exchange is None:
        return
    try:
        ts = datetime.now(tz=timezone.utc).isoformat()
        payload = {"event": "listing.failed", "service": "listing", "timestamp": ts, "error_type": error_type, "detail": detail}
        if listing_id is not None:
            payload["listing_id"] = listing_id
        await _mq_exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload).encode("utf-8"),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=ERROR_ROUTING_KEY,
        )
    except Exception as exc:
        # Log only — never let error reporting break the response
        import logging
        logging.getLogger(__name__).warning("Failed to publish error event: %s", exc)


async def _publish_created_events(listing_id: int) -> None:
    ts = datetime.now(tz=timezone.utc).isoformat()

    def _msg(body: dict) -> aio_pika.Message:
        return aio_pika.Message(
            body=json.dumps(body).encode("utf-8"),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )

    await asyncio.gather(
        # Immediate: listing.created — notification.js routes to charities room
        _mq_exchange.publish(
            _msg({"event": "listing.created",       "service": "listing", "timestamp": ts, "listing_id": listing_id}),
            routing_key=EVENT_ROUTING_KEY,
        ),
        # Immediate: listing.window.opened — auditor window-start marker
        _mq_exchange.publish(
            _msg({"event": "listing.window.opened", "service": "listing", "timestamp": ts, "listing_id": listing_id}),
            routing_key="listing.window.opened",
        ),
        # Delayed: dead-letters to pasarconnect.dlx as listing.window.closed after DELAY_TTL_MS
        _mq_channel.default_exchange.publish(
            _msg({"event": "listing.window.closed", "service": "listing", "timestamp": ts, "listing_id": listing_id}),
            routing_key=DELAY_QUEUE,
        ),
    )


@app.post("/api/listings", response_model=ListingCreateResponse, status_code=201)
async def create_listing(
    payload: ListingCreateRequest,
    token_payload: Annotated[dict, Depends(verify_jwt_token)],
):
    # Vendor identity comes from the signed JWT — never from the request body.
    vendor_id = str(token_payload["sub"])
    try:
        listing_id = await inventory_client.create_listing(
            {**payload.model_dump(mode="json"), "vendor_id": vendor_id}
        )
    except inventory_client.InventoryServiceError as exc:
        await _publish_error_event(
            error_type="inventory_unavailable",
            detail=str(exc),
        )
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    # Fetch listed_at so callers know exactly when the queue window started.
    # Non-fatal: returns empty string if Inventory is momentarily slow.
    try:
        listed_at = await inventory_client.get_listing_created_at(listing_id)
    except inventory_client.InventoryServiceError:
        listed_at = ""

    try:
        await _publish_created_events(listing_id)
    except Exception as exc:
        await _publish_error_event(
            error_type="mq_publish_failed",
            detail=str(exc),
            listing_id=listing_id,
        )
        raise HTTPException(status_code=503, detail="RabbitMQ publish failed")

    return {"listing_id": listing_id, "listed_at": listed_at}
