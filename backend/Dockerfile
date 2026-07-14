# Multi-stage Go build for bond-monitor API and notifier.
FROM golang:1.25-bookworm AS builder

WORKDIR /src
COPY backend/go.mod backend/go.sum ./backend/
WORKDIR /src/backend
RUN go mod download

COPY backend/ ./

RUN CGO_ENABLED=0 go build -o /out/api ./cmd/api
RUN CGO_ENABLED=0 go build -o /out/notifier ./cmd/notifier

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /out/api /app/api
COPY --from=builder /out/notifier /app/notifier
COPY --from=builder /src/backend/migrations /app/backend/migrations

ENV BOND_MONITOR_REPO_ROOT=/app
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl --fail http://localhost:8000/health || exit 1

CMD ["/app/api"]
