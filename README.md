# PasarConnect

> **Bridging food waste and food insecurity through a tiered, real-time marketplace.**

PasarConnect is a social enterprise platform that connects food vendors (bakeries, supermarkets, cafés) with registered charities and the general public to redistribute surplus food before it is wasted. Built on a microservices architecture, it demonstrates enterprise SOA principles using REST, gRPC, RabbitMQ, and real-time WebSockets.

---

## Table of Contents

- [Business Scenario](#business-scenario)
- [System Architecture](#system-architecture)
- [Service Catalogue](#service-catalogue)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [Port Reference](#port-reference)
- [Event Taxonomy](#event-taxonomy)
- [Audit Service & MongoDB](#audit-service--mongodb)
- [Running Tests](#running-tests)

---

## Business Scenario

Food vendors list surplus items on PasarConnect. The system enforces a **priority-tier model**:

| Phase | Who | Price | Duration |
|---|---|---|---|
| **Charity Tier** | Registered charities only | Free | First 30 minutes |
| **Public Tier** | General public | Steep discount | After 30 minutes |

User scenarios covered:

- **Vendor** — list surplus food with photos, price, and pickup window
- **Charity** — claim food (with legal verification & no-show tracking)
- **Public** — purchase discounted food via Stripe payment gateway
- **Auditor** — real-time event audit trail persisted to MongoDB

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (Vue.js)                       │
│          vendor-app (port 5173)  │  charity-dashboard           │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTP via Kong (port 8000)
┌──────────────────────▼──────────────────────────────────────────┐
│                     API Gateway — Kong                          │
└──┬───────────┬──────────┬───────────┬──────────────┬────────────┘
   │ REST      │ REST     │ REST      │ REST         │ REST
   ▼           ▼          ▼           ▼              ▼
Listing     Claim      Payment   OutSystems     Media
Service     Service    Service    Wrapper       Service
   │           │          │
   │  gRPC     │  gRPC    │  gRPC
   ▼           ▼          ▼
Inventory  Claim-Log  Payment-Log   Verification   Waitlist
Service    Service    Service       Service        Service

                    ┌──────────────┐
                    │   RabbitMQ   │  pasarconnect.events (TOPIC)
                    │  (AMQP/MQTT) │
                    └──┬───────────┘
                       │ subscribe
              ┌────────┴────────┐
              ▼                 ▼
       Notification          Auditor
        Service              Service
       (Socket.io)          (MongoDB)
```

### Communication Patterns

| Pattern | Used By |
|---|---|
| **Synchronous REST** | Kong → all services, Stripe webhooks |
| **Synchronous gRPC** | Listing/Claim/Payment → Inventory, Claim-Log, Payment-Log, Verification, Waitlist |
| **Asynchronous RabbitMQ** | Listing, Claim, Payment → `pasarconnect.events` topic exchange |
| **WebSocket (Socket.io)** | Notification service → charity dashboard (live push) |

---

## Service Catalogue

| Service | Port (HTTP) | Port (gRPC) | Language | Role |
|---|---|---|---|---|
| `inventory-service` | 8001 | 50051 | Python / FastAPI | Atomic — food listing CRUD & stock |
| `listing-service` | 8008 | — | Python / FastAPI | Composite — orchestrates inventory + DLX timer |
| `claim-service` | 8002 | — | Python / FastAPI | Composite — charity claim flow + verification |
| `waitlist-service` | 8010 | 50053 | Python / FastAPI | Atomic — waitlist queue management |
| `claim-log-service` | 8006 | 50061 | Python / FastAPI | Atomic — claim history ledger |
| `payment-service` | 8003 | — | Python / FastAPI | Composite — Stripe intent + inventory confirm |
| `stripe-wrapper` | 8004 | — | Python / FastAPI | Atomic — Stripe API proxy |
| `payment-log-service` | 8005 | 50062 | Python / FastAPI | Atomic — payment transaction ledger |
| `verification-service` | 8009 | 50052 | Python / FastAPI | Atomic — charity verification + no-show policy |
| `outsystems-service` | 8007 | — | Python / FastAPI | Adapter — OutSystems auth bridge + JWT issuance |
| `media-service` | 8080 | — | Node.js | Atomic — S3 image upload/serve |
| `notification-service` | 8011 | — | Node.js | Consumer — RabbitMQ → Socket.io live push |
| `auditor-service` | — | — | Node.js | Consumer — RabbitMQ → MongoDB event store |
| `kong` | 8000 | — | Kong 3.6 | API Gateway — single entry point |

### Databases

| Container | Engine | Host Port | Used By |
|---|---|---|---|
| `inventory-db` | PostgreSQL 16 | 5433 | inventory-service |
| `claim-log-db` | PostgreSQL 16 | 5434 | claim-log-service |
| `payment-log-db` | PostgreSQL 16 | 5435 | payment-log-service |
| `verification-db` | PostgreSQL 16 | 5436 | verification-service |
| `waitlist-db` | PostgreSQL 16 | 5437 | waitlist-service |
| `mongo` | MongoDB 7 | 27017 | auditor-service |
| `rabbitmq` | RabbitMQ 3.13 | 5672 / 15672 | all async services |

---

## Tech Stack

- **Backend** — Python 3.12, FastAPI, SQLAlchemy, gRPC, amqplib
- **Frontend** — Vue 3, Vite, Leaflet, Socket.io-client
- **Messaging** — RabbitMQ 3.13 (TOPIC exchange + Dead-Letter Exchange for timed window)
- **Databases** — PostgreSQL 16 (transactional), MongoDB 7 (audit log)
- **Payments** — Stripe (test mode)
- **Auth** — OutSystems (JWT RS256)
- **Media** — AWS S3
- **Gateway** — Kong 3.6 (DB-less declarative)
- **Containerisation** — Docker Compose

---

## Prerequisites

| Tool | Minimum Version |
|---|---|
| Docker Desktop | 24.x |
| Docker Compose | 2.x (included with Docker Desktop) |
| Node.js | 20.x (frontend only, optional) |
| Stripe CLI | latest (for local webhook forwarding) |

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/jonahkoh/PasarConnect.git
cd PasarConnect
```

### 2. Create your environment file

```bash
cp .env.example .env
```

Open `.env` and fill in the values marked `← CHANGE THIS`:

```env
STRIPE_SECRET_KEY=sk_test_...       # from stripe.com/dashboard
STRIPE_WEBHOOK_SECRET=whsec_...     # generated by Stripe CLI (see step 5)
OUTSYSTEMS_API_URL=https://...      # your OutSystems environment URL
OUTSYSTEMS_API_KEY=...              # your OutSystems API key
```

> **Local dev shortcut**: leave `MOCK_OUTSYSTEMS=true` to skip real OutSystems calls. The mock always returns an approved charity.

### 3. Add your RSA public key

The platform uses RS256 JWTs signed by OutSystems. Place the exported public key at:

```
keys/public.pem
```

> If you are using mock mode only, create an empty placeholder:
> ```bash
> mkdir keys && touch keys/public.pem
> ```

### 4. Start all services

```bash
docker compose up -d --build
```

Wait ~30 seconds for all health checks to pass, then verify:

```
http://localhost:8000        → Kong API Gateway (main entry point)
http://localhost:15672       → RabbitMQ Management UI  (guest / guest)
http://localhost:27017       → MongoDB (connect via Compass)
```

### 5. Forward Stripe webhooks (payments only)

In a separate terminal, run the Stripe CLI to relay webhook events to your local payment service:

```bash
stripe listen --forward-to localhost:8000/api/payments/webhook
```

Copy the `whsec_...` secret printed by the CLI into your `.env` as `STRIPE_WEBHOOK_SECRET`, then restart the payment service:

```bash
docker compose restart payment-service stripe-wrapper
```

### 6. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

The app is available at `http://localhost:5173`.

---

## Environment Variables

All variables live in a single root `.env` file. The full reference with defaults is in [`.env.example`](.env.example).

| Variable | Description | Default |
|---|---|---|
| `POSTGRES_USER` | Shared Postgres username | `postgres` |
| `POSTGRES_PASSWORD` | Shared Postgres password | `postgres` |
| `RABBITMQ_HOST` | RabbitMQ hostname (internal) | `rabbitmq` |
| `STRIPE_SECRET_KEY` | Stripe secret key | ← **required** |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret | ← **required** |
| `OUTSYSTEMS_API_URL` | OutSystems environment base URL | ← **required** |
| `MOCK_OUTSYSTEMS` | Skip real OutSystems HTTP calls | `true` |
| `QUEUE_WINDOW_MINUTES` | Charity-exclusive window duration | `0.5` (30 s for dev) |
| `MAX_DAILY_CLAIMS` | Max claims per charity per day | `5` |
| `MAX_NOSHOWS` | No-shows before cooldown triggers | `3` |
| `AWS_S3_BUCKET` | S3 bucket for food photos | ← required for media |

---

## Port Reference

| Port | Service | Notes |
|---|---|---|
| **8000** | Kong proxy | Single entry point for all API calls |
| **8100** | Kong Admin API | Dev/debugging only |
| **8200** | Kong Manager GUI | Dev/debugging only |
| **8001** | inventory-service HTTP | — |
| **8002** | claim-service | — |
| **8003** | payment-service | — |
| **8004** | stripe-wrapper | — |
| **8005** | payment-log-service | — |
| **8006** | claim-log-service | — |
| **8007** | outsystems-service | — |
| **8008** | listing-service | — |
| **8009** | verification-service | — |
| **8010** | waitlist-service | — |
| **8011** | notification-service | Socket.io |
| **8080** | media-service | S3 proxy |
| **5672** | RabbitMQ AMQP | — |
| **15672** | RabbitMQ Management UI | `guest` / `guest` |
| **27017** | MongoDB | `pasarconnect_audit` DB |
| **50051** | inventory-service gRPC | — |
| **50052** | verification-service gRPC | — |
| **50053** | waitlist-service gRPC | — |

---

## Event Taxonomy

All services publish to the `pasarconnect.events` TOPIC exchange using the `<service>.<noun>.<verb>` routing key convention. Every message envelope includes:

```json
{
  "event": "claim.created",
  "service": "claim",
  "timestamp": "2026-04-09T10:00:00.000Z",
  ...domain fields...
}
```

| Routing Key | Publisher | Description |
|---|---|---|
| `listing.created` | listing | New food listing published |
| `listing.window.opened` | listing | Charity-exclusive window started |
| `listing.window.closed` | listing (via DLX) | Window expired — food goes public |
| `listing.failed` | listing | Listing creation error |
| `payment.intent.created` | payment | Stripe payment intent initiated |
| `payment.success` | payment | Payment confirmed by Stripe |
| `payment.collected` | payment | Food physically collected |
| `payment.refunded` | payment | Payment refunded |
| `payment.cancelled` | payment | Payment cancelled |
| `payment.forfeited` | payment | Uncollected — forfeit triggered |
| `payment.arrived` | payment | Vendor marked as arrived |
| `payment.fulfillment.failed` | payment | Post-payment inventory error |
| `claim.created` | claim | Charity claim accepted |
| `claim.failed` | claim | Claim could not be created |
| `claim.cancelled` | claim | Charity cancelled their claim |
| `claim.noshow` | claim | Charity marked as no-show |
| `claim.arrived` | claim | Charity arrived for pickup |
| `claim.completed` | claim | Claim fulfilled |
| `claim.waitlist.offered` | claim | Waitlist slot offered |
| `claim.waitlist.position` | claim | Waitlist position update |
| `claim.waitlist.promoted` | claim | Promoted from waitlist |
| `claim.waitlist.cancelled` | claim | Waitlist entry cancelled |

---

## Audit Service & MongoDB

Every event published to `pasarconnect.events` is automatically persisted to MongoDB by the `auditor-service`.

**Collection**: `pasarconnect_audit.auditevents`

Connect via MongoDB Compass at `localhost:27017`.

Useful queries in Compass:

```json
// All failure events
{ "event": { "$regex": "failed|noshow" } }

// Full trace for a listing
{ "listing_id": 55 }

// Failures by service (Aggregation tab)
[
  { "$match": { "event": { "$regex": "failed" } } },
  { "$group": { "_id": "$service", "count": { "$sum": 1 } } },
  { "$sort": { "count": -1 } }
]
```

---

## Running Tests

```bash
# From the project root (Python services)
pip install -r backend/requirements.txt
pytest backend/tests/ -v

# Individual service
pytest backend/tests/test_claim.py -v
```

RabbitMQ and Postgres must be running for integration tests. Start infrastructure only:

```bash
docker compose up -d rabbitmq inventory-db claim-log-db payment-log-db verification-db waitlist-db
```