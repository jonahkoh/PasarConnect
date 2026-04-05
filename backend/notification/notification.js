/**
 * Notification Service — testing stub
 *
 * Subscribes to two RabbitMQ feeds:
 *   1. pasarconnect.events  / listing.created     → a new listing went live
 *   2. pasarconnect.dlx     / listing.window.closed → queue window has expired (after 3-min TTL)
 *
 * All received messages are stored in an in-memory ring buffer (last 100 entries).
 * GET /debug/messages  — returns everything received so far (for Postman / smoke tests)
 * GET /health          — liveness probe
 *
 * NOTE: This is a testing skeleton only. Socket.io live notification to clients
 * will be wired in once listing + payment services are stable.
 */

"use strict";

const amqp    = require("amqplib");
const express = require("express");

// ── Config ────────────────────────────────────────────────────────────────────
const RABBITMQ_HOST = process.env.RABBITMQ_HOST || "localhost";
const RABBITMQ_USER = process.env.RABBITMQ_USER || "guest";
const RABBITMQ_PASS = process.env.RABBITMQ_PASS || "guest";
const AMQP_URL      = `amqp://${RABBITMQ_USER}:${RABBITMQ_PASS}@${RABBITMQ_HOST}`;
const HTTP_PORT     = parseInt(process.env.PORT || "8007", 10);

const EVENT_EXCHANGE  = "pasarconnect.events";
const DLX_EXCHANGE    = "pasarconnect.dlx";
const CREATED_QUEUE   = "notification.listing.created";
const WINDOW_QUEUE    = "notification.listing.window.closed";

// ── In-memory ring buffer ─────────────────────────────────────────────────────
const MAX_MESSAGES = 100;
const receivedMessages = [];

function storeMessage(source, payload) {
  const entry = { received_at: new Date().toISOString(), source, payload };
  receivedMessages.push(entry);
  if (receivedMessages.length > MAX_MESSAGES) {
    receivedMessages.shift();
  }
  console.log(`[${source}]`, JSON.stringify(payload));
}

// ── RabbitMQ consumer ─────────────────────────────────────────────────────────
async function startConsumer() {
  // Retry loop — RabbitMQ may not be immediately ready on container start
  let conn;
  for (let attempt = 1; attempt <= 10; attempt++) {
    try {
      conn = await amqp.connect(AMQP_URL);
      console.log("Connected to RabbitMQ");
      break;
    } catch (err) {
      console.warn(`RabbitMQ not ready (attempt ${attempt}/10): ${err.message}`);
      await new Promise(r => setTimeout(r, 3000));
    }
  }
  if (!conn) {
    console.error("Could not connect to RabbitMQ after 10 attempts. Exiting.");
    process.exit(1);
  }

  conn.on("error", err => console.error("RabbitMQ connection error:", err.message));
  conn.on("close", () => {
    console.warn("RabbitMQ connection closed. Retrying in 5s...");
    setTimeout(startConsumer, 5000);
  });

  const ch = await conn.createChannel();

  // Declare both exchanges so this service is self-contained even if listing-service
  // hasn't run yet (RabbitMQ is idempotent on declare).
  await ch.assertExchange(EVENT_EXCHANGE, "topic", { durable: true });
  await ch.assertExchange(DLX_EXCHANGE,   "topic", { durable: true });

  // Queue 1: listing.created — fires immediately when a listing goes live
  await ch.assertQueue(CREATED_QUEUE, { durable: true });
  await ch.bindQueue(CREATED_QUEUE, EVENT_EXCHANGE, "listing.created");
  ch.consume(CREATED_QUEUE, msg => {
    if (!msg) return;
    try {
      const payload = JSON.parse(msg.content.toString());
      storeMessage("listing.created", payload);
    } catch {
      console.error("Failed to parse listing.created message");
    }
    ch.ack(msg);
  });

  // Queue 2: listing.window.closed — fires after 3-min TTL via DLX
  await ch.assertQueue(WINDOW_QUEUE, { durable: true });
  await ch.bindQueue(WINDOW_QUEUE, DLX_EXCHANGE, "listing.window.closed");
  ch.consume(WINDOW_QUEUE, msg => {
    if (!msg) return;
    try {
      const payload = JSON.parse(msg.content.toString());
      storeMessage("listing.window.closed", payload);
    } catch {
      console.error("Failed to parse listing.window.closed message");
    }
    ch.ack(msg);
  });

  console.log(`Listening on: ${CREATED_QUEUE}, ${WINDOW_QUEUE}`);
}

// ── HTTP server ───────────────────────────────────────────────────────────────
const app = express();

app.get("/health", (_req, res) => {
  res.json({ status: "healthy", service: "notification" });
});

app.get("/debug/messages", (_req, res) => {
  res.json({ count: receivedMessages.length, messages: receivedMessages });
});

app.listen(HTTP_PORT, () => {
  console.log(`Notification service HTTP on port ${HTTP_PORT}`);
});

// ── Boot ──────────────────────────────────────────────────────────────────────
startConsumer().catch(err => {
  console.error("startConsumer failed:", err);
  process.exit(1);
});
