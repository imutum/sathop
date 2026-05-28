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

git config --global --add safe.directory "$REPO_DIR"

# ── Helper: clone or pull ────────────────────────────────────────────
update_repo() {
  if [ -d "$REPO_DIR/.git" ]; then
    echo "[entrypoint] Pulling $GIT_REF ..."
    cd "$REPO_DIR"
    git remote set-url origin "$GIT_REPO"
    git fetch origin "$GIT_REF" --depth=1 --quiet
    git checkout FETCH_HEAD --quiet
    git clean -fd --quiet
  else
    echo "[entrypoint] Cloning $GIT_REF ..."
    git clone --depth=1 --branch "$GIT_REF" "$GIT_REPO" "$REPO_DIR" --quiet
    cd "$REPO_DIR"
  fi
}

# ── Helper: dependency sync ──────────────────────────────────────────
sync_deps() {
  if [ -f /app/.uv-lock-hash ]; then
    CURRENT=$(sha256sum uv.lock | awk '{print $1}')
    BAKED=$(awk '{print $1}' /app/.uv-lock-hash)
    if [ "$CURRENT" != "$BAKED" ]; then
      echo "[entrypoint] WARNING: uv.lock changed — rebuild runtime image for faster starts"
    fi
  fi
  echo "[entrypoint] uv sync --extra $ROLE ..."
  uv sync --frozen --extra "$ROLE" --quiet
}

# ── Helper: frontend (orchestrator only, first time) ─────────────────
fetch_frontend() {
  [ "$ROLE" = "orchestrator" ] || return 0
  [ ! -d "$REPO_DIR/frontend/dist" ] || return 0

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
    if curl -fsSL "$FRONTEND_URL" | tar -xz -C "$REPO_DIR/frontend/"; then
      echo "[entrypoint] Frontend ready."
    else
      echo "[entrypoint] Frontend download failed — running without Web UI."
    fi
  else
    echo "[entrypoint] No frontend dist — running without Web UI."
  fi
}

# ── Supervisor loop ──────────────────────────────────────────────────
# Python exits → loop pulls latest code and restarts. No container
# restart needed. API restart endpoints just kill the Python process;
# the loop picks up from git pull.
export PATH="$REPO_DIR/.venv/bin:$PATH"

while true; do
  update_repo
  sync_deps
  fetch_frontend

  echo "[entrypoint] Starting sathop.$ROLE ..."
  cd /app
  set +e
  python -m "sathop.$ROLE.main"
  EXIT_CODE=$?
  set -e

  if [ "$EXIT_CODE" -ne 0 ]; then
    echo "[entrypoint] Process exited with code $EXIT_CODE, restarting in 3s ..."
    sleep 3
  else
    echo "[entrypoint] Process exited cleanly, restarting ..."
  fi
done
