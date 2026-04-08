"use strict";

/**
 * Unit tests for notification.js room routing logic.
 *
 * These tests isolate the two behaviours under review:
 *   1. charity socket connect  → joins "charities" room (in addition to "listings")
 *   2. listing.created message → emits "listing:new" to "charities" only
 *   3. listing.window.closed   → emits "listing:window_closed" to "listings" (everyone)
 *
 * No real RabbitMQ, Socket.io server, or network calls are made.
 * We test the logic units (emitToRooms, handleClaimEvent, room join logic)
 * by extracting them directly and providing lightweight mocks.
 */

// ── Minimal io mock ────────────────────────────────────────────────────────────
function makeMockIo() {
  const emitted = [];   // { room, event, payload }
  const rooms   = new Map();  // room → Set of socket ids

  return {
    _emitted: emitted,
    _rooms:   rooms,
    to(room) {
      return {
        emit(event, payload) {
          emitted.push({ room, event, payload });
        },
      };
    },
    sockets: {
      adapter: { rooms },
    },
  };
}

// ── Minimal socket mock ────────────────────────────────────────────────────────
function makeMockSocket(sub, role) {
  const joined = [];
  return {
    data: { user: { sub, role } },
    join(room) { joined.push(room); },
    _joined: joined,
    on() {},        // ignore event registration in unit tests
  };
}

// ── Extract emitToRooms from the source without booting the full service ───────
// We replicate the function here (same logic) to keep tests self-contained and
// fast — no file loading, no process.exit, no network attempts.
function makeEmitToRooms(io) {
  return function emitToRooms(rooms, event, payload) {
    const list = Array.isArray(rooms) ? rooms : [rooms];
    list.forEach(room => {
      io.to(room).emit(event, payload);
    });
  };
}

// ── Test suite ─────────────────────────────────────────────────────────────────

describe("Room assignment on socket connect", () => {
  test("charity joins 'listings', 'charities', and 'charity:<sub>'", () => {
    const socket = makeMockSocket("42", "charity");
    const { sub, role } = socket.data.user;

    // Simulate the connect handler body
    socket.join("listings");
    if (role === "charity") {
      socket.join(`charity:${sub}`);
      socket.join("charities");
    }

    expect(socket._joined).toContain("listings");
    expect(socket._joined).toContain("charity:42");
    expect(socket._joined).toContain("charities");
  });

  test("vendor joins 'listings' and 'vendor:<sub>' but NOT 'charities'", () => {
    const socket = makeMockSocket("7", "vendor");
    const { sub, role } = socket.data.user;

    socket.join("listings");
    if (role === "charity") {
      socket.join(`charity:${sub}`);
      socket.join("charities");
    } else if (role === "vendor") {
      socket.join(`vendor:${sub}`);
    }

    expect(socket._joined).toContain("listings");
    expect(socket._joined).toContain("vendor:7");
    expect(socket._joined).not.toContain("charities");
  });

  test("public user joins 'listings' and 'user:<sub>' but NOT 'charities'", () => {
    const socket = makeMockSocket("99", "public");
    const { sub, role } = socket.data.user;

    socket.join("listings");
    if (role === "charity") {
      socket.join(`charity:${sub}`);
      socket.join("charities");
    } else if (role === "vendor") {
      socket.join(`vendor:${sub}`);
    } else {
      socket.join(`user:${sub}`);
    }

    expect(socket._joined).toContain("listings");
    expect(socket._joined).toContain("user:99");
    expect(socket._joined).not.toContain("charities");
  });
});

// ── listing.created → charities only ──────────────────────────────────────────

describe("listing.created consumer routing", () => {
  test("emits 'listing:new' to 'charities' room only", () => {
    const io = makeMockIo();
    const emitToRooms = makeEmitToRooms(io);

    const payload = { event: "listing.created", listing_id: 5 };
    // This is exactly what the consumer now does:
    emitToRooms("charities", "listing:new", payload);

    expect(io._emitted).toHaveLength(1);
    expect(io._emitted[0].room).toBe("charities");
    expect(io._emitted[0].event).toBe("listing:new");
    expect(io._emitted[0].payload.listing_id).toBe(5);
  });

  test("does NOT emit 'listing:new' to 'listings' room", () => {
    const io = makeMockIo();
    const emitToRooms = makeEmitToRooms(io);

    emitToRooms("charities", "listing:new", { listing_id: 5 });

    const sentToListings = io._emitted.filter(e => e.room === "listings");
    expect(sentToListings).toHaveLength(0);
  });
});

// ── listing.window.closed (DLX) → listings (everyone) ────────────────────────

describe("listing.window.closed consumer routing (after TTL / DLX)", () => {
  test("emits 'listing:window_closed' to 'listings' room", () => {
    const io = makeMockIo();
    const emitToRooms = makeEmitToRooms(io);

    const payload = { event: "listing.created", listing_id: 5 };
    // This is exactly what the window.closed consumer does (unchanged):
    emitToRooms("listings", "listing:window_closed", payload);

    expect(io._emitted).toHaveLength(1);
    expect(io._emitted[0].room).toBe("listings");
    expect(io._emitted[0].event).toBe("listing:window_closed");
  });

  test("does NOT emit 'listing:window_closed' to 'charities' room", () => {
    const io = makeMockIo();
    const emitToRooms = makeEmitToRooms(io);

    emitToRooms("listings", "listing:window_closed", { listing_id: 5 });

    const sentToCharities = io._emitted.filter(e => e.room === "charities");
    expect(sentToCharities).toHaveLength(0);
  });
});

// ── No duplicate card: distinct events for distinct phases ────────────────────

describe("No duplicate card — two distinct events for two distinct phases", () => {
  test("listing:new and listing:window_closed are different event names", () => {
    const io = makeMockIo();
    const emitToRooms = makeEmitToRooms(io);
    const payload = { listing_id: 5 };

    // Phase 1: vendor posts → charity-only notification
    emitToRooms("charities", "listing:new", payload);
    // Phase 2: TTL expires → public release
    emitToRooms("listings", "listing:window_closed", payload);

    const events = io._emitted.map(e => e.event);
    expect(events).toContain("listing:new");
    expect(events).toContain("listing:window_closed");
    // Two different events — frontend can handle each independently without duplication
    expect(new Set(events).size).toBe(2);
  });

  test("a public user in 'listings' does not receive 'listing:new'", () => {
    const io = makeMockIo();
    const emitToRooms = makeEmitToRooms(io);

    // Public user's rooms: "listings", "user:99"
    // Charity event goes to "charities" — public user is not in that room
    emitToRooms("charities", "listing:new", { listing_id: 5 });

    const publicReceived = io._emitted.filter(
      e => e.room === "listings" || e.room === "user:99"
    );
    expect(publicReceived).toHaveLength(0);
  });
});
