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

# ── Helper: frontend (orchestrator, first boot only) ────────────────
# Subsequent updates are operator-triggered via Settings → "更新并重启".
fetch_frontend() {
  [ "$ROLE" = "orchestrator" ] || return 0

  if [ -f "$REPO_DIR/frontend/dist/index.html" ]; then
    return 0
  fi

  VERSION=$("$REPO_DIR/.venv/bin/python" -c "
import tomllib
with open('$REPO_DIR/pyproject.toml','rb') as f:
    print(tomllib.load(f)['project']['version'])
" 2>/dev/null || echo "")

  [ -n "$VERSION" ] || return 0

  CLEAN_REPO=$(echo "${SATHOP_GIT_REPO:-https://github.com/imutum/sathop.git}" | sed 's|\.git$||')
  FRONTEND_URL="${SATHOP_FRONTEND_URL:-${CLEAN_REPO}/releases/download/v${VERSION}/frontend-dist.tar.gz}"

  CURL_OPTS=(-fsSL)
  if [ -n "${SATHOP_GIT_TOKEN:-}" ] && echo "$FRONTEND_URL" | grep -q "github.com"; then
    CURL_OPTS+=(-H "Authorization: token ${SATHOP_GIT_TOKEN}")
  fi

  echo "[entrypoint] First boot — downloading frontend v${VERSION} ..."
  if curl "${CURL_OPTS[@]}" "$FRONTEND_URL" | tar -xz -C "$REPO_DIR/frontend/"; then
    echo "$VERSION" > "$REPO_DIR/frontend/dist/.version"
    echo "[entrypoint] Frontend ready."
  else
    echo "[entrypoint] Frontend download failed — use Settings UI to retry."
  fi
}

# ── Supervisor loop ──────────────────────────────────────────────────
# Each iteration: git pull → dep sync → (orchestrator: frontend check) → start.
# Exit codes:
#   0   = update requested (git pull + restart process)
#   42  = removed by orchestrator (break loop → container stops)
#   other = crash (exponential backoff, then retry)
export PATH="$REPO_DIR/.venv/bin:$PATH"

BACKOFF=1
MAX_BACKOFF=60
STABLE_THRESHOLD=30

while true; do
  update_repo
  sync_deps
  fetch_frontend

  echo "[entrypoint] Starting sathop.$ROLE ..."
  cd /app
  START_TS=$(date +%s)
  set +e
  python -m "sathop.$ROLE.main"
  EXIT_CODE=$?
  set -e
  ELAPSED=$(( $(date +%s) - START_TS ))

  if [ "$EXIT_CODE" -eq 42 ]; then
    echo "[entrypoint] Process removed (exit 42) — stopping container."
    break
  elif [ "$EXIT_CODE" -eq 0 ]; then
    echo "[entrypoint] Update requested — pulling latest code ..."
    BACKOFF=1
  else
    if [ "$ELAPSED" -ge "$STABLE_THRESHOLD" ]; then
      BACKOFF=1
    fi
    echo "[entrypoint] Process crashed (exit $EXIT_CODE), retrying in ${BACKOFF}s ..."
    sleep "$BACKOFF"
    BACKOFF=$(( BACKOFF * 2 ))
    if [ "$BACKOFF" -gt "$MAX_BACKOFF" ]; then
      BACKOFF=$MAX_BACKOFF
    fi
  fi
done
