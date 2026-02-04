pasar connect/
├── docker-compose.yml       # Launches everything (Postgres, RabbitMQ, all MS)
├── backend/
│   ├── inventory/        # FastAPI (Vendors)
│   ├── claim/            # FastAPI (The Race Referee)
│   ├── notification/     # Node.js (Email/Telegram/Strikes)
│   └── outsystems/   # Logic to connect your local code to OutSystems
├── frontend/
│   ├── vendor-app/          # Vue.js (Mobile UI)
│   └── charity-dashboard/   # Vue.js (Monitor UI with WebSockets)