# syntax=docker/dockerfile:1.7

# Orchestrator image: single-package project, installs only the `orchestrator` extra.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# --- dependency layer ------------------------------------------------------
# Install the `orchestrator` extra's deps without the project source, so this
# layer stays cached until pyproject.toml or uv.lock changes.
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra orchestrator

# --- source layer ---------------------------------------------------------
COPY src src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra orchestrator

# Prebuilt Vue UI (produced by the release workflow's npm-build step or a
# local `cd frontend-vue && npm run build`). The image still works without
# it — orchestrator just won't serve "/" routes.
COPY frontend-vue/dist ./frontend-vue/dist

# --- runtime --------------------------------------------------------------
ENV PATH="/app/.venv/bin:$PATH" \
    SATHOP_HOST=0.0.0.0 \
    SATHOP_PORT=8000 \
    SATHOP_DB=/app/data/orchestrator.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status == 200 else 1)"

CMD ["python", "-m", "sathop.orchestrator.main"]
