FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock /app/
COPY backend/pyproject.toml /app/backend/
COPY backend/src /app/backend/src
COPY data/ratings.json /app/data/ratings.json

RUN uv sync --package bond-monitor-backend --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl --fail http://localhost:8000/health || exit 1

CMD ["uvicorn", "bond_monitor.main:app", "--host", "0.0.0.0", "--port", "8000"]
