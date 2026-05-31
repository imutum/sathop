# syntax=docker/dockerfile:1.7

# Unified runtime shell: all three components in one image.
# Source + frontend arrive at startup as a per-version release bundle the
# entrypoint downloads + extracts (sathop-bundle.tar.gz), not baked in.
# Rebuild only when pyproject.toml / uv.lock change (new deps).
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_CACHE_DIR=/app/.uv-cache \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates git curl tini minisign \
    && rm -rf /var/lib/apt/lists/*

# Release signing trust root: the entrypoint verifies every downloaded bundle
# against this ed25519 public key (minisign) before extracting. The matching
# secret key lives only in the CI signing secret; baking the public half makes
# the image itself the trust anchor (TUF-lite, same discipline as per-granule SHA256).
COPY deploy/runtime/sathop-release.pub /app/sathop-release.pub

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

# tini as PID 1: reaps zombies (worker forks bundle subprocesses) and forwards
# SIGTERM to the supervisor, which re-forwards it to the running component so its
# graceful-drain handler fires on `docker stop` instead of being SIGKILLed.
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
