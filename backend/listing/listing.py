import asyncio
import json
import os
from datetime import datetime

import aio_pika
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

import inventory_client

load_dotenv()

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")

EVENT_EXCHANGE = "pasarconnect.events"
EVENT_ROUTING_KEY = "listing.created"
DELAY_QUEUE = "listing.delay.30m"
DELAY_TTL_MS = 30 * 60 * 1000

app = FastAPI(title="PasarConnect - Listing Service")


class ListingCreateRequest(BaseModel):
    vendor_id: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    quantity: int | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    expiry: datetime
    image_url: str = Field(..., min_length=1, max_length=1024)

    @model_validator(mode="after")
    def validate_pairs(self):
        if self.quantity is None and self.weight_kg is None:
            raise ValueError("Either quantity or weight_kg must be provided")
        return self


class ListingCreateResponse(BaseModel):
    listing_id: int


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "listing"}


async def _publish_created_events(listing_id: int) -> None:
    message_payload = {
        "event": "listing.created",
        "listing_id": listing_id,
    }
    message = aio_pika.Message(
        body=json.dumps(message_payload).encode("utf-8"),
        content_type="application/json",
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
    )

    connection = await aio_pika.connect_robust(
        f"amqp://{RABBITMQ_USER}:{RABBITMQ_PASS}@{RABBITMQ_HOST}/"
    )
    async with connection:
        channel = await connection.channel()

        exchange = await channel.declare_exchange(
            EVENT_EXCHANGE,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )

        queue = await channel.declare_queue(
            DELAY_QUEUE,
            durable=True,
            arguments={"x-message-ttl": DELAY_TTL_MS},
        )

        await asyncio.gather(
            exchange.publish(message, routing_key=EVENT_ROUTING_KEY),
            channel.default_exchange.publish(message, routing_key=queue.name),
        )


@app.post("/api/listings", response_model=ListingCreateResponse, status_code=201)
async def create_listing(payload: ListingCreateRequest):
    try:
        listing_id = await inventory_client.create_listing(payload.model_dump(mode="json"))
    except inventory_client.InventoryServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    try:
        await _publish_created_events(listing_id)
    except Exception:
        raise HTTPException(status_code=503, detail="RabbitMQ publish failed")

    return {"listing_id": listing_id}
