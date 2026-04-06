import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
//
// All API traffic is proxied through Kong (port 8000) — same path as production.
// This ensures JWT enforcement and routing rules are exercised during local dev.
// Direct-to-service shortcuts (e.g. :8001) are intentionally avoided.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // All /api/* requests → Kong gateway → correct upstream service
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // Auth endpoints → Kong → outsystems-service (covers /auth/* and /admin/*)
      "/auth": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // Socket.io WebSocket → Kong → notification-service
      "/socket.io": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
})

