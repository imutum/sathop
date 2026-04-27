# syntax=docker/dockerfile:1.7

# Receiver image (Linux). Pull-only client — no inbound ports.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra receiver

COPY src src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra receiver

ENV PATH="/app/.venv/bin:$PATH" \
    SATHOP_STORAGE_DIR=/data/archive

CMD ["python", "-m", "sathop.receiver.main"]
