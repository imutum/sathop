# syntax=docker/dockerfile:1.7

# Unified runtime shell: all three components in one image.
# Source code arrives at startup via git pull, not at build time.
# Rebuild only when pyproject.toml / uv.lock change (new deps).
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_CACHE_DIR=/app/.uv-cache \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- dependency cache layer ------------------------------------------------
# Pre-download all extras' wheels into the uv cache. The venv created here
# is throwaway — at runtime, entrypoint.sh creates a fresh one inside the
# cloned repo. --all-extras ensures orchestrator + worker + receiver deps
# are all cached so any SATHOP_ROLE starts fast.
COPY pyproject.toml uv.lock ./

RUN sha256sum uv.lock > /app/.uv-lock-hash \
    && uv sync --frozen --no-install-project --all-extras \
    && rm -rf /app/.venv

# --- non-root user ---------------------------------------------------------
RUN mkdir -p /app/data /app/repo /data/archive

COPY deploy/runtime/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
