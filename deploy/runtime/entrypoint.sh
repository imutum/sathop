#!/usr/bin/env bash
set -euo pipefail

# ── Validate SATHOP_ROLE ──────────────────────────────────────────────
ROLE="${SATHOP_ROLE:?SATHOP_ROLE must be set to orchestrator, worker, or receiver}"
case "$ROLE" in
  orchestrator|worker|receiver) ;;
  *) echo "ERROR: SATHOP_ROLE=$ROLE is not valid (orchestrator / worker / receiver)" >&2; exit 1 ;;
esac

# ── Release bundle configuration ──────────────────────────────────────
# One self-contained tarball per version (backend src + uv.lock + prebuilt
# frontend/dist), so frontend and backend can never drift. NO git pull, NO hot
# update: a (re)start installs a *pinned* version and sticks with it.
REPO_DIR="/app/repo"
GIT_REPO="${SATHOP_GIT_REPO:-https://github.com/imutum/sathop.git}"
ASSET_BASE="${GIT_REPO%.git}"                 # → https://github.com/<owner>/<repo>
ASSET_NAME="sathop-bundle.tar.gz"
INSTALLED_STAMP="$REPO_DIR/.sathop-version"   # concrete version currently extracted
PENDING_STAMP="$REPO_DIR/.pending-version"    # one-shot upgrade target written by the UI

# curl auth header for a private release asset (public repo needs none).
CURL_AUTH=()
if [ -n "${SATHOP_GIT_TOKEN:-}" ]; then
  CURL_AUTH=(-H "Authorization: token ${SATHOP_GIT_TOKEN}")
fi

# ── Helper: asset URL for a version ("latest" or a concrete X) ────────
asset_url() {
  local ver="$1"
  if [ "$ver" = "latest" ]; then
    echo "${ASSET_BASE}/releases/latest/download/${ASSET_NAME}"
  else
    echo "${ASSET_BASE}/releases/download/v${ver#v}/${ASSET_NAME}"
  fi
}

# ── Helper: download + extract a version into REPO_DIR (atomic-ish) ───
# Downloads to a tmp file, extracts to a staging dir, then replaces the
# version-owned trees in REPO_DIR. The process isn't running yet during install,
# so there's no concurrent reader to protect — staging just guards against a
# half-downloaded archive clobbering a working install.
install_bundle() {
  local ver="$1" url tmp staging
  url="$(asset_url "$ver")"
  tmp="$REPO_DIR/.bundle.tgz.tmp"
  staging="$REPO_DIR/.staging"

  echo "[entrypoint] Fetching $ASSET_NAME ($ver) ..."
  if ! curl -fSL "${CURL_AUTH[@]}" "$url" -o "$tmp"; then
    echo "[entrypoint] download failed: $url" >&2
    rm -f "$tmp"
    return 1
  fi

  rm -rf "$staging"
  mkdir -p "$staging"
  if ! tar -xzf "$tmp" -C "$staging"; then
    echo "[entrypoint] archive extract failed" >&2
    rm -rf "$tmp" "$staging"
    return 1
  fi
  rm -f "$tmp"
  if [ ! -f "$staging/pyproject.toml" ] || [ ! -d "$staging/src" ]; then
    echo "[entrypoint] bundle missing src/ or pyproject.toml" >&2
    rm -rf "$staging"
    return 1
  fi

  # Swap version-owned trees; keep everything else in REPO_DIR (e.g. stamps).
  rm -rf "$REPO_DIR/src" "$REPO_DIR/frontend"
  cp -a "$staging/." "$REPO_DIR/"
  rm -rf "$staging"

  # Record the concrete version (resolves "latest" to its real number).
  local concrete
  concrete=$(grep -m1 '^version' "$REPO_DIR/pyproject.toml" | sed -E 's/.*"([^"]+)".*/\1/')
  echo "${concrete:-$ver}" > "$INSTALLED_STAMP"
  echo "[entrypoint] Installed v${concrete:-$ver}."
}

# ── Helper: ensure the desired version is installed ───────────────────
# Precedence: a one-shot UI upgrade (.pending-version) wins once, then we stick
# with whatever is installed (so restarts/crashes never change version), and only
# fall back to $SATHOP_VERSION on a truly empty first boot.
ensure_bundle() {
  local desired installed
  installed=$(cat "$INSTALLED_STAMP" 2>/dev/null || echo "")

  if [ -f "$PENDING_STAMP" ]; then
    desired=$(cat "$PENDING_STAMP")
    rm -f "$PENDING_STAMP"            # consume: a UI upgrade is a one-time action
    echo "[entrypoint] UI upgrade requested → v${desired#v}"
  elif [ -n "$installed" ]; then
    desired="$installed"             # stick with the installed version on restart
  else
    desired="${SATHOP_VERSION:-latest}"  # first boot bootstrap
  fi

  # "latest" is only resolved on first boot; once something is installed we keep
  # it, so a restart can't silently jump to a newer release.
  if [ "$desired" = "latest" ] && [ -n "$installed" ]; then
    return 0
  fi
  if [ "${desired#v}" = "$installed" ] && [ -d "$REPO_DIR/src" ]; then
    return 0
  fi

  if ! install_bundle "$desired"; then
    if [ -d "$REPO_DIR/src" ]; then
      echo "[entrypoint] keeping installed v${installed} (upgrade to v${desired#v} failed)" >&2
      return 0                       # soft-fail: stay on the working version
    fi
    return 1                         # first boot, no fallback → caller retries
  fi
}

# ── Helper: dependency sync ──────────────────────────────────────────
sync_deps() {
  if [ -f /app/.uv-lock-hash ]; then
    CURRENT=$(sha256sum "$REPO_DIR/uv.lock" | awk '{print $1}')
    BAKED=$(awk '{print $1}' /app/.uv-lock-hash)
    if [ "$CURRENT" != "$BAKED" ]; then
      echo "[entrypoint] WARNING: uv.lock changed — rebuild runtime image for faster starts"
    fi
  fi
  echo "[entrypoint] uv sync --extra $ROLE ..."
  ( cd "$REPO_DIR" && uv sync --frozen --extra "$ROLE" --quiet )
}

# ── Supervisor loop ──────────────────────────────────────────────────
# Each iteration: ensure version → dep sync → start. Exit codes:
#   0   = restart requested (re-evaluates .pending-version → applies a UI upgrade)
#   42  = removed by orchestrator (break loop → container stops)
#   other = crash (exponential backoff, then retry)
export PATH="$REPO_DIR/.venv/bin:$PATH"

# tini (PID 1) forwards SIGTERM here on `docker stop`. Re-forward it to the
# running component so its graceful-drain handler fires, and set STOPPING so a
# TERM-initiated exit stops the container rather than looping into a restart.
STOPPING=
on_term() { STOPPING=1; [ -n "${CHILD:-}" ] && kill -TERM "$CHILD" 2>/dev/null || true; }
trap on_term TERM INT

BACKOFF=1
MAX_BACKOFF=60
STABLE_THRESHOLD=30

while true; do
  if ! ensure_bundle; then
    echo "[entrypoint] no usable bundle yet, retrying in ${BACKOFF}s ..." >&2
    sleep "$BACKOFF"
    BACKOFF=$(( BACKOFF * 2 )); [ "$BACKOFF" -gt "$MAX_BACKOFF" ] && BACKOFF=$MAX_BACKOFF
    continue
  fi
  sync_deps

  [ -n "$STOPPING" ] && exit 0   # TERM arrived during install — don't start
  echo "[entrypoint] Starting sathop.$ROLE ..."
  cd "$REPO_DIR"
  START_TS=$(date +%s)
  set +e
  # Background + wait (not a foreground exec) so on_term can deliver SIGTERM to
  # the component for a graceful drain. `wait` returns 128+signo when a trapped
  # signal interrupts it, so re-wait until the child actually exits.
  python -m "sathop.$ROLE.main" &
  CHILD=$!
  [ -n "$STOPPING" ] && kill -TERM "$CHILD" 2>/dev/null || true  # TERM raced the start
  wait "$CHILD"; EXIT_CODE=$?
  # A trapped signal makes `wait` return early (128+signo) while the child keeps
  # draining — re-wait until it's actually gone so EXIT_CODE is the child's own.
  while kill -0 "$CHILD" 2>/dev/null; do wait "$CHILD"; EXIT_CODE=$?; done
  CHILD=
  set -e
  ELAPSED=$(( $(date +%s) - START_TS ))

  if [ -n "$STOPPING" ]; then
    echo "[entrypoint] SIGTERM received — container stopping after drain."
    exit 0
  fi

  if [ "$EXIT_CODE" -eq 42 ]; then
    echo "[entrypoint] Process removed (exit 42) — stopping container."
    break
  elif [ "$EXIT_CODE" -eq 0 ]; then
    echo "[entrypoint] Restart requested ..."
    BACKOFF=1
  else
    if [ "$ELAPSED" -ge "$STABLE_THRESHOLD" ]; then
      BACKOFF=1
    fi
    echo "[entrypoint] Process crashed (exit $EXIT_CODE), retrying in ${BACKOFF}s ..."
    sleep "$BACKOFF"
    BACKOFF=$(( BACKOFF * 2 )); [ "$BACKOFF" -gt "$MAX_BACKOFF" ] && BACKOFF=$MAX_BACKOFF
  fi
done
