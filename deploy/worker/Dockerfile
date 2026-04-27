# syntax=docker/dockerfile:1.7

# Worker image: single-package project, installs only the `worker` extra.
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
    uv sync --frozen --no-install-project --extra worker

COPY src src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra worker

ENV PATH="/app/.venv/bin:$PATH" \
    SATHOP_WORK_ROOT=/app/data/work \
    SATHOP_BUNDLE_CACHE=/app/data/bundles \
    SATHOP_VENV_CACHE=/app/data/venvs \
    SATHOP_SHARED_CACHE=/app/data/shared \
    SATHOP_STORAGE_ROOT=/app/data/storage \
    SATHOP_STORAGE_PORT=9000

EXPOSE 9000

CMD ["python", "-m", "sathop.worker.main"]
