# ── Stage 1: Build ─────────────────────────────────────────────────────────────
# Use the official Go builder image. `go mod tidy` fetches dependencies and
# generates go.sum during the build so we don't need to commit go.sum.
FROM golang:1.22-alpine AS builder

WORKDIR /app

# Copy module manifest and source first, then resolve + download deps.
COPY go.mod ./
COPY main.go ./

# go mod tidy: resolves transitive deps, generates go.sum, downloads modules.
# Network access is available during `docker build` by default.
RUN go mod tidy

# Compile a static binary (no libc dependency → can run on plain alpine).
RUN CGO_ENABLED=0 GOOS=linux go build -o media-service .

# ── Stage 2: Runtime ───────────────────────────────────────────────────────────
# Minimal Alpine image — ca-certificates is required for HTTPS calls to AWS.
FROM alpine:3.19

RUN apk add --no-cache ca-certificates tzdata

WORKDIR /app
COPY --from=builder /app/media-service .

EXPOSE 8080
CMD ["./media-service"]
