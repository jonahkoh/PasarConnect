"use strict";

require("dotenv").config();
const amqplib  = require("amqplib");
const mongoose = require("mongoose");

// ── Config ──────────────────────────────────────────────────────────────────

const {
  RABBITMQ_HOST = "localhost",
  RABBITMQ_USER = "guest",
  RABBITMQ_PASS = "guest",
  MONGO_URI     = "mongodb://localhost:27017/pasarconnect_audit",
} = process.env;

const AMQP_URL = `amqp://${RABBITMQ_USER}:${RABBITMQ_PASS}@${RABBITMQ_HOST}`;
const EXCHANGE = "pasarconnect.events";
const QUEUE    = "auditor.all";

// ── Mongoose Schema ──────────────────────────────────────────────────────────

const auditSchema = new mongoose.Schema(
  {
    event:          { type: String, index: true },
    service:        { type: String, index: true },
    timestamp:      { type: Date,   index: true },
    routing_key:    { type: String },
    transaction_id: { type: String, index: true },
    listing_id:     { type: Number, index: true },
    user_id:        { type: Number },
    claim_id:       { type: Number },
    charity_id:     { type: Number },
    reason_code:    { type: String },
    reason:         { type: String },
  },
  { strict: false }  // also persists any extra payload fields
);

const AuditEvent = mongoose.model("AuditEvent", auditSchema);

// ── RabbitMQ consumer ────────────────────────────────────────────────────────

async function start() {
  // Connect MongoDB
  await mongoose.connect(MONGO_URI);
  console.log("[auditor] MongoDB connected:", MONGO_URI);

  // Connect RabbitMQ with simple retry
  let conn;
  for (let attempt = 1; attempt <= 10; attempt++) {
    try {
      conn = await amqplib.connect(AMQP_URL);
      break;
    } catch {
      console.log(`[auditor] RabbitMQ not ready (attempt ${attempt}/10), retrying in 3s…`);
      await new Promise((r) => setTimeout(r, 3000));
    }
  }
  if (!conn) throw new Error("Could not connect to RabbitMQ after 10 attempts");

  const ch = await conn.createChannel();
  await ch.assertExchange(EXCHANGE, "topic", { durable: true });
  const { queue } = await ch.assertQueue(QUEUE, { durable: true });
  await ch.bindQueue(queue, EXCHANGE, "#");  // catch every routing key

  ch.prefetch(1);
  console.log(`[auditor] Listening  exchange="${EXCHANGE}"  queue="${QUEUE}"  binding="#"`);

  ch.consume(queue, async (msg) => {
    if (!msg) return;
    try {
      const payload = JSON.parse(msg.content.toString());
      const doc = new AuditEvent({
        ...payload,
        routing_key: msg.fields.routingKey,
        timestamp:   payload.timestamp ? new Date(payload.timestamp) : new Date(),
      });
      await doc.save();
      console.log(`[auditor] saved  routing_key=${msg.fields.routingKey}  event=${payload.event}`);
      ch.ack(msg);
    } catch (err) {
      console.error("[auditor] error processing message:", err.message);
      ch.nack(msg, false, false);  // discard malformed — do not requeue
    }
  });

  conn.on("error", (err) => console.error("[auditor] AMQP connection error:", err.message));
}

start().catch((err) => {
  console.error("[auditor] Fatal:", err.message);
  process.exit(1);
});
