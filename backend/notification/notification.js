/**
 * PasarConnect — Notification Service v2
 *
 * Architecture:
 *   - Express + Socket.io on the same http.Server (port 8011)
 *   - RabbitMQ consumer: two exchanges
 *       pasarconnect.events   (listing-service events)
 *       PasarConnect          (claim + payment events)
 *   - JWT auth on every Socket.io handshake (RS256, same key as all other services)
 *
 * Socket.io rooms:
 *   listings             — all authenticated users (live listing feed)
 *   charity:{sub}        — private channel for a charity user
 *   vendor:{sub}         — private channel for a vendor user
 *   listing:{listing_id} — per-listing room; client emits "subscribe:listing"
 *
 * Emit mapping (RabbitMQ routing key → Socket.io event → room):
 *   listing.created          → listing:new           → listings
 *   listing.window.closed    → listing:window_closed  → listings
 *   claim.success            → claim:success          → charity:{charity_id} + listing:{listing_id}
 *   claim.cancelled          → claim:cancelled        → charity:{charity_id} + listing:{listing_id}
 *   claim.waitlist.promoted  → claim:promoted         → charity:{charity_id}
 *   claim.waitlist.offered   → claim:offered          → charity:{charity_id}
 *   claim.waitlist.cancelled → claim:waitlist_closed  → listing:{listing_id}
 *   payment.success          → payment:success        → listing:{listing_id}
 *   payment.failure          → (log only)
 *
 * HTTP endpoints:
 *   GET /health       — liveness probe (also exposes connected socket count)
 *   GET /debug/rooms  — room occupancy map (internal, not exposed through Kong)
 */

"use strict";

const http  = require("http");
const fs    = require("fs");
const ppath = require("path");
const amqp    = require("amqplib");
const express = require("express");
const jwt     = require("jsonwebtoken");
const { Server } = require("socket.io");

// ── Config ─────────────────────────────────────────────────────────────────────
const RABBITMQ_HOST   = process.env.RABBITMQ_HOST  || "localhost";
const RABBITMQ_USER   = process.env.RABBITMQ_USER  || "guest";
const RABBITMQ_PASS   = process.env.RABBITMQ_PASS  || "guest";
const AMQP_URL        = `amqp://${RABBITMQ_USER}:${RABBITMQ_PASS}@${RABBITMQ_HOST}`;
const HTTP_PORT       = parseInt(process.env.PORT  || "8011", 10);
const PUBLIC_KEY_PATH = process.env.PUBLIC_KEY_PATH || ppath.join(__dirname, "../../keys/public.pem");

// ── Load RS256 public key for JWT verification ─────────────────────────────────
let PUBLIC_KEY;
try {
  PUBLIC_KEY = fs.readFileSync(PUBLIC_KEY_PATH, "utf8");
  console.log(`[jwt] Loaded RS256 public key from ${PUBLIC_KEY_PATH}`);
} catch (err) {
  console.error(`[jwt] FATAL: Cannot load public key at ${PUBLIC_KEY_PATH}: ${err.message}`);
  process.exit(1);
}

// ── Exchange / queue names ─────────────────────────────────────────────────────
const EVENT_EXCHANGE        = "pasarconnect.events";  // listing-service
const DLX_EXCHANGE          = "pasarconnect.dlx";     // listing TTL dead-letter
const PASARCONNECT_EXCHANGE = "PasarConnect";          // claim + payment services

const QUEUES = {
  listingCreated:      "notification.listing.created",
  listingWindowClosed: "notification.listing.window.closed",
  listingError:        "notification.listing.error",
  claimEvents:         "notification.claim.events",
  paymentEvents:       "notification.payment.events",
};

// ── Express + HTTP server + Socket.io ──────────────────────────────────────────
const expressApp = express();
const httpServer = http.createServer(expressApp);

const io = new Server(httpServer, {
  cors:       { origin: "*", methods: ["GET", "POST"] },
  transports: ["polling", "websocket"],
});

// ── Socket.io JWT auth middleware ──────────────────────────────────────────────
io.use((socket, next) => {
  const token = socket.handshake.auth?.token;
  if (!token) {
    return next(new Error("Authentication required: no token provided."));
  }
  try {
    const payload = jwt.verify(token, PUBLIC_KEY, { algorithms: ["RS256"] });
    socket.data.user = payload;   // { sub, role, iss, exp, iat }
    next();
  } catch (err) {
    next(new Error(`Authentication failed: ${err.message}`));
  }
});

// ── Socket.io connection handler ───────────────────────────────────────────────
io.on("connection", (socket) => {
  const { sub, role } = socket.data.user;
  console.log(`[socket] connected sub=${sub} role=${role} id=${socket.id}`);

  socket.join("listings");

  if (role === "charity") {
    socket.join(`charity:${sub}`);
    console.log(`[socket] sub=${sub} joined: listings, charity:${sub}`);
  } else if (role === "vendor") {
    socket.join(`vendor:${sub}`);
    console.log(`[socket] sub=${sub} joined: listings, vendor:${sub}`);
  } else {
    console.log(`[socket] sub=${sub} joined: listings`);
  }

  // Vendor (or charity) can subscribe to a specific listing for real-time alerts
  socket.on("subscribe:listing", ({ listing_id }) => {
    if (!listing_id) return;
    socket.join(`listing:${listing_id}`);
    console.log(`[socket] sub=${sub} subscribed to listing:${listing_id}`);
  });

  socket.on("unsubscribe:listing", ({ listing_id }) => {
    if (listing_id) socket.leave(`listing:${listing_id}`);
  });

  socket.on("disconnect", (reason) => {
    console.log(`[socket] disconnected sub=${sub} reason=${reason}`);
  });
});

// ── HTTP endpoints ─────────────────────────────────────────────────────────────
expressApp.get("/health", (_req, res) => {
  res.json({ status: "healthy", service: "notification", connections: io.engine.clientsCount });
});

expressApp.get("/debug/rooms", (_req, res) => {
  const rooms = {};
  io.sockets.adapter.rooms.forEach((sockets, room) => { rooms[room] = sockets.size; });
  res.json(rooms);
});

// ── Emit helper ────────────────────────────────────────────────────────────────
function emitToRooms(rooms, event, payload) {
  const list = Array.isArray(rooms) ? rooms : [rooms];
  list.forEach(room => {
    const count = io.sockets.adapter.rooms.get(room)?.size || 0;
    io.to(room).emit(event, payload);
    console.log(`[emit] ${event} → ${room} (${count} clients)`);
  });
}

// ── Claim event dispatcher ─────────────────────────────────────────────────────
function handleClaimEvent(routingKey, payload) {
  switch (routingKey) {
    case "claim.success":
      emitToRooms([`charity:${payload.charity_id}`, `listing:${payload.listing_id}`], "claim:success", payload);
      break;
    case "claim.cancelled":
      emitToRooms([`charity:${payload.charity_id}`, `listing:${payload.listing_id}`], "claim:cancelled", payload);
      break;
    case "claim.waitlist.promoted":
      emitToRooms(`charity:${payload.charity_id}`, "claim:promoted", payload);
      break;
    case "claim.waitlist.offered":
      emitToRooms(`charity:${payload.charity_id}`, "claim:offered", payload);
      break;
    case "claim.waitlist.position":
      emitToRooms(`charity:${payload.charity_id}`, "claim:queued", payload);
      break;
    case "claim.waitlist.cancelled":
      emitToRooms(`listing:${payload.listing_id}`, "claim:waitlist_closed", payload);
      break;
    case "claim.arrived":
      // Charity is on-site; notify the vendor via the per-listing room they subscribed to.
      emitToRooms(`listing:${payload.listing_id}`, "claim:arrived", payload);
      break;
    case "claim.completed":
      // Vendor approved collection; notify the charity.
      emitToRooms(`charity:${payload.charity_id}`, "claim:completed", payload);
      break;
    case "claim.failure":
      console.warn("[claim.failure]", JSON.stringify(payload));
      break;
    default:
      console.warn("[amqp] Unhandled claim key:", routingKey);
  }
}

// ── Payment event dispatcher ───────────────────────────────────────────────────
function handlePaymentEvent(routingKey, payload) {
  switch (routingKey) {
    case "payment.success":
      emitToRooms(`listing:${payload.listing_id}`, "payment:success", payload);
      break;
    case "payment.failure":
      console.warn("[payment.failure]", JSON.stringify(payload));
      break;
    default:
      console.warn("[amqp] Unhandled payment key:", routingKey);
  }
}

// ── RabbitMQ consumer ──────────────────────────────────────────────────────────
async function startConsumer() {
  let conn;
  for (let attempt = 1; attempt <= 10; attempt++) {
    try {
      conn = await amqp.connect(AMQP_URL);
      console.log("[amqp] Connected to RabbitMQ");
      break;
    } catch (err) {
      console.warn(`[amqp] Not ready (attempt ${attempt}/10): ${err.message}`);
      await new Promise(r => setTimeout(r, 3000));
    }
  }
  if (!conn) {
    console.error("[amqp] Could not connect after 10 attempts. Exiting.");
    process.exit(1);
  }

  conn.on("error", err => console.error("[amqp] Error:", err.message));
  conn.on("close", () => {
    console.warn("[amqp] Closed — reconnecting in 5s...");
    setTimeout(startConsumer, 5000);
  });

  const ch = await conn.createChannel();

  await ch.assertExchange(EVENT_EXCHANGE,        "topic", { durable: true });
  await ch.assertExchange(DLX_EXCHANGE,          "topic", { durable: true });
  await ch.assertExchange(PASARCONNECT_EXCHANGE, "topic", { durable: true });

  // Queue: listing.created
  await ch.assertQueue(QUEUES.listingCreated, { durable: true });
  await ch.bindQueue(QUEUES.listingCreated, EVENT_EXCHANGE, "listing.created");
  ch.consume(QUEUES.listingCreated, (msg) => {
    if (!msg) return;
    try { emitToRooms("listings", "listing:new", JSON.parse(msg.content.toString())); }
    catch (e) { console.error("[amqp] listing.created parse error:", e.message); }
    ch.ack(msg);
  });

  // Queue: listing.window.closed (via DLX)
  await ch.assertQueue(QUEUES.listingWindowClosed, { durable: true });
  await ch.bindQueue(QUEUES.listingWindowClosed, DLX_EXCHANGE, "listing.window.closed");
  ch.consume(QUEUES.listingWindowClosed, (msg) => {
    if (!msg) return;
    try { emitToRooms("listings", "listing:window_closed", JSON.parse(msg.content.toString())); }
    catch (e) { console.error("[amqp] listing.window.closed parse error:", e.message); }
    ch.ack(msg);
  });

  // Queue: listing.error (ops only, not forwarded to clients)
  await ch.assertQueue(QUEUES.listingError, { durable: true });
  await ch.bindQueue(QUEUES.listingError, EVENT_EXCHANGE, "listing.error");
  ch.consume(QUEUES.listingError, (msg) => {
    if (!msg) return;
    try { console.error("[listing.error]", msg.content.toString()); }
    catch (e) { console.error("[amqp] listing.error parse:", e.message); }
    ch.ack(msg);
  });

  // Queue: claim events (claim.success, claim.cancelled, claim.waitlist.*)
  await ch.assertQueue(QUEUES.claimEvents, { durable: true });
  for (const key of ["claim.success", "claim.cancelled", "claim.failure",
                     "claim.arrived", "claim.completed",
                     "claim.waitlist.promoted", "claim.waitlist.offered",
                     "claim.waitlist.position", "claim.waitlist.cancelled"]) {
    await ch.bindQueue(QUEUES.claimEvents, PASARCONNECT_EXCHANGE, key);
  }
  ch.consume(QUEUES.claimEvents, (msg) => {
    if (!msg) return;
    try { handleClaimEvent(msg.fields.routingKey, JSON.parse(msg.content.toString())); }
    catch (e) { console.error(`[amqp] ${msg.fields.routingKey} parse error:`, e.message); }
    ch.ack(msg);
  });

  // Queue: payment events
  await ch.assertQueue(QUEUES.paymentEvents, { durable: true });
  for (const key of ["payment.success", "payment.failure"]) {
    await ch.bindQueue(QUEUES.paymentEvents, PASARCONNECT_EXCHANGE, key);
  }
  ch.consume(QUEUES.paymentEvents, (msg) => {
    if (!msg) return;
    try { handlePaymentEvent(msg.fields.routingKey, JSON.parse(msg.content.toString())); }
    catch (e) { console.error(`[amqp] ${msg.fields.routingKey} parse error:`, e.message); }
    ch.ack(msg);
  });

  console.log("[amqp] All queues bound and consuming.");
}

// ── Boot ───────────────────────────────────────────────────────────────────────
httpServer.listen(HTTP_PORT, () => {
  console.log(`[http] Notification service on port ${HTTP_PORT}`);
});

startConsumer().catch(err => {
  console.error("[amqp] startConsumer fatal:", err);
  process.exit(1);
});

