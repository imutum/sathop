#!/usr/bin/env bash
set -euo pipefail

# ── Validate SATHOP_ROLE ──────────────────────────────────────────────
ROLE="${SATHOP_ROLE:?SATHOP_ROLE must be set to orchestrator, worker, or receiver}"
case "$ROLE" in
  orchestrator|worker|receiver) ;;
  *) echo "ERROR: SATHOP_ROLE=$ROLE is not valid (orchestrator / worker / receiver)" >&2; exit 1 ;;
esac

# ── Git configuration ─────────────────────────────────────────────────
REPO_DIR="/app/repo"
GIT_REPO="${SATHOP_GIT_REPO:-https://github.com/imutum/sathop.git}"
GIT_REF="${SATHOP_GIT_REF:-main}"

if [ -n "${SATHOP_GIT_TOKEN:-}" ]; then
  GIT_REPO="${GIT_REPO/https:\/\//https://${SATHOP_GIT_TOKEN}@}"
fi

# ── Clone or pull ─────────────────────────────────────────────────────
if [ -d "$REPO_DIR/.git" ]; then
  echo "[entrypoint] Pulling $GIT_REF ..."
  cd "$REPO_DIR"
  git fetch origin "$GIT_REF" --depth=1 --quiet
  git checkout FETCH_HEAD --quiet
  git clean -fd --quiet
else
  echo "[entrypoint] Cloning $GIT_REF ..."
  git clone --depth=1 --branch "$GIT_REF" "$GIT_REPO" "$REPO_DIR" --quiet
  cd "$REPO_DIR"
fi

# ── Dependency sync ───────────────────────────────────────────────────
if [ -f /app/.uv-lock-hash ]; then
  CURRENT=$(sha256sum uv.lock | awk '{print $1}')
  BAKED=$(awk '{print $1}' /app/.uv-lock-hash)
  if [ "$CURRENT" != "$BAKED" ]; then
    echo "[entrypoint] WARNING: uv.lock changed — rebuild runtime image for faster starts"
  fi
fi

echo "[entrypoint] uv sync --extra $ROLE ..."
uv sync --frozen --extra "$ROLE" --quiet

# ── Frontend (orchestrator only) ──────────────────────────────────────
if [ "$ROLE" = "orchestrator" ] && [ ! -d "$REPO_DIR/frontend/dist" ]; then
  VERSION=$(python -c "
import tomllib
with open('pyproject.toml','rb') as f:
    print(tomllib.load(f)['project']['version'])
" 2>/dev/null || echo "")

  FRONTEND_URL="${SATHOP_FRONTEND_URL:-}"
  if [ -z "$FRONTEND_URL" ] && [ -n "$VERSION" ]; then
    CLEAN_REPO=$(echo "${SATHOP_GIT_REPO:-https://github.com/imutum/sathop.git}" | sed 's|\.git$||')
    FRONTEND_URL="${CLEAN_REPO}/releases/download/v${VERSION}/frontend-dist.tar.gz"
  fi

  if [ -n "$FRONTEND_URL" ]; then
    echo "[entrypoint] Downloading frontend from release ..."
    if curl -fsSL "$FRONTEND_URL" | tar -xz -C "$REPO_DIR/frontend/" 2>/dev/null; then
      echo "[entrypoint] Frontend ready."
    else
      echo "[entrypoint] Frontend download failed — running without Web UI."
    fi
  else
    echo "[entrypoint] No frontend dist — running without Web UI."
  fi
fi

# ── Launch ────────────────────────────────────────────────────────────
echo "[entrypoint] Starting sathop.$ROLE ..."
export PATH="$REPO_DIR/.venv/bin:$PATH"
exec python -m "sathop.$ROLE.main"
