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
# frontend/dist), so frontend and backend can never drift. NO git pull: a
# (re)start installs a *pinned* version and sticks with it.
#
# A/B slots: each version installs into its own slots/<version>/ with its own
# venv. `committed` names the last version proven healthy (the rollback target);
# `intent` names a version we are currently bringing up. A worker/receiver whose
# candidate dies before passing the health gate auto-rolls-back to `committed`.
# The orchestrator never auto-rolls-back (rolling it back to an older version
# after a forward schema migration would invert the orch-before-worker contract);
# it commits on start and a bad release is recovered by an explicit re-upgrade.
REPO_DIR="/app/repo"
SLOTS_DIR="$REPO_DIR/slots"
COMMITTED_FILE="$REPO_DIR/committed"   # concrete version proven healthy (rollback target)
INTENT_FILE="$REPO_DIR/intent"         # concrete version currently being brought up
PENDING_STAMP="$REPO_DIR/.pending-version"  # one-shot upgrade target written by the UI/worker
GIT_REPO="${SATHOP_GIT_REPO:-https://github.com/imutum/sathop.git}"
ASSET_BASE="${GIT_REPO%.git}"
ASSET_NAME="sathop-bundle.tar.gz"
GATE_SEC="${SATHOP_HEALTH_GATE_SEC:-60}"    # candidate must stay alive this long to commit

CURL_AUTH=()
if [ -n "${SATHOP_GIT_TOKEN:-}" ]; then
  CURL_AUTH=(-H "Authorization: token ${SATHOP_GIT_TOKEN}")
fi

# ── Small helpers ─────────────────────────────────────────────────────
write_atomic() { printf '%s' "$2" > "$1.tmp" && mv -f "$1.tmp" "$1"; }   # $1=file $2=content
slot_dir() { echo "$SLOTS_DIR/$1"; }                                     # $1=concrete version

asset_url() {
  local ver="$1"
  if [ "$ver" = "latest" ]; then
    echo "${ASSET_BASE}/releases/latest/download/${ASSET_NAME}"
  else
    echo "${ASSET_BASE}/releases/download/v${ver#v}/${ASSET_NAME}"
  fi
}

# ── Download + extract + sync a version into its slot ─────────────────
# Echoes the resolved concrete version on success; returns 1 on any failure
# (leaves no partial slot behind). Idempotent: re-running for an existing
# complete slot is cheap (skips download, returns the version).
install_slot() {
  local ver="$1" url tmp staging concrete dest
  url="$(asset_url "$ver")"
  tmp="$SLOTS_DIR/.bundle.tgz.tmp"
  staging="$SLOTS_DIR/.staging"
  mkdir -p "$SLOTS_DIR"

  echo "[entrypoint] Fetching $ASSET_NAME ($ver) ..." >&2
  if ! curl -fSL "${CURL_AUTH[@]}" "$url" -o "$tmp"; then
    echo "[entrypoint] download failed: $url" >&2; rm -f "$tmp"; return 1
  fi
  rm -rf "$staging"; mkdir -p "$staging"
  if ! tar -xzf "$tmp" -C "$staging"; then
    echo "[entrypoint] archive extract failed" >&2; rm -rf "$tmp" "$staging"; return 1
  fi
  rm -f "$tmp"
  if [ ! -f "$staging/pyproject.toml" ] || [ ! -d "$staging/src" ]; then
    echo "[entrypoint] bundle missing src/ or pyproject.toml" >&2; rm -rf "$staging"; return 1
  fi

  concrete=$(grep -m1 '^version' "$staging/pyproject.toml" | sed -E 's/.*"([^"]+)".*/\1/')
  concrete="${concrete:-${ver#v}}"
  dest="$(slot_dir "$concrete")"
  rm -rf "$dest"; mkdir -p "$dest"; cp -a "$staging/." "$dest/"; rm -rf "$staging"

  if [ -f /app/.uv-lock-hash ] \
     && [ "$(sha256sum "$dest/uv.lock" | awk '{print $1}')" != "$(awk '{print $1}' /app/.uv-lock-hash)" ]; then
    echo "[entrypoint] WARNING: uv.lock changed — rebuild runtime image for faster starts" >&2
  fi
  echo "[entrypoint] uv sync (v$concrete, --extra $ROLE) ..." >&2
  if ! ( cd "$dest" && uv sync --frozen --extra "$ROLE" --quiet ); then
    echo "[entrypoint] uv sync failed for v$concrete" >&2; rm -rf "$dest"; return 1
  fi
  echo "$concrete"
}

# Ensure a complete slot exists for $1 (concrete or "latest"); echo the concrete version.
ensure_slot() {
  local ver="$1"
  if [ "$ver" != "latest" ] && [ -d "$(slot_dir "${ver#v}")/.venv" ]; then
    echo "${ver#v}"; return 0
  fi
  install_slot "$ver"
}

# Keep committed + intent + the 3 most-recent slots; drop the rest.
gc_slots() {
  local committed intent i=0 b
  committed=$(cat "$COMMITTED_FILE" 2>/dev/null || true)
  intent=$(cat "$INTENT_FILE" 2>/dev/null || true)
  for d in $(ls -1dt "$SLOTS_DIR"/*/ 2>/dev/null); do
    b=$(basename "$d"); i=$((i + 1))
    [ "$b" = "$committed" ] && continue
    [ "$b" = "$intent" ] && continue
    [ "$i" -le 3 ] && continue
    echo "[entrypoint] GC old slot v$b" >&2; rm -rf "$d"
  done
}

commit_slot() { write_atomic "$COMMITTED_FILE" "$1"; rm -f "$INTENT_FILE"; gc_slots; }

# ── Select which version to run ───────────────────────────────────────
# Sets RUN_VER (concrete slot to run) + CANDIDATE (1 = health-gate it). Returns 1
# only on a truly empty first boot whose download failed (caller retries).
# Precedence: one-shot UI/worker trigger (.pending-version) → in-progress intent
# (crash-safe resume) → committed (sticky steady state) → SATHOP_VERSION (first boot).
RUN_VER=""; CANDIDATE=0
select_version() {
  local committed target concrete
  committed=$(cat "$COMMITTED_FILE" 2>/dev/null || true)

  # Promote the inbound one-shot stamp into durable intent BEFORE deleting it, so
  # a crash between consuming the stamp and finishing install never loses the
  # upgrade (the old .pending-version crash window).
  if [ -f "$PENDING_STAMP" ]; then
    target=$(cat "$PENDING_STAMP"); write_atomic "$INTENT_FILE" "${target#v}"; rm -f "$PENDING_STAMP"
    echo "[entrypoint] upgrade requested → v${target#v}" >&2
  fi

  if [ -s "$INTENT_FILE" ]; then
    target=$(cat "$INTENT_FILE")
  elif [ -n "$committed" ] && [ -d "$(slot_dir "$committed")/.venv" ]; then
    RUN_VER="$committed"; CANDIDATE=0; return 0          # steady state
  else
    target="${SATHOP_VERSION:-latest}"; write_atomic "$INTENT_FILE" "${target#v}"   # first boot
  fi

  if ! concrete="$(ensure_slot "$target")"; then
    if [ -n "$committed" ] && [ -d "$(slot_dir "$committed")/.venv" ]; then
      echo "[entrypoint] install of v${target#v} failed → staying on committed v$committed" >&2
      rm -f "$INTENT_FILE"; RUN_VER="$committed"; CANDIDATE=0; return 0
    fi
    return 1                                             # first boot, nothing to fall back to
  fi
  write_atomic "$INTENT_FILE" "$concrete"                # resolve "latest"/vX → concrete number
  RUN_VER="$concrete"
  if [ "$ROLE" != "orchestrator" ] && [ -n "$committed" ] && [ "$concrete" != "$committed" ] \
     && [ -d "$(slot_dir "$committed")/.venv" ]; then
    CANDIDATE=1                                          # gated upgrade with a healthy fallback
  else
    CANDIDATE=0                                          # orch / first boot / same-as-committed
  fi
  return 0
}

# ── Supervisor loop ──────────────────────────────────────────────────
# Component exit codes: 0 = restart requested, 42 = removed (stop), else = crash.
# tini (PID 1) forwards SIGTERM here on `docker stop`; we re-forward it to the
# component so its graceful-drain handler fires, and set STOPPING so a
# TERM-initiated exit stops the container instead of looping into a restart.
BASE_PATH="$PATH"
STOPPING=
on_term() { STOPPING=1; [ -n "${CHILD:-}" ] && kill -TERM "$CHILD" 2>/dev/null || true; }
trap on_term TERM INT

BACKOFF=1
MAX_BACKOFF=60
STABLE_THRESHOLD=30

while true; do
  if ! select_version; then
    echo "[entrypoint] no usable bundle yet, retrying in ${BACKOFF}s ..." >&2
    sleep "$BACKOFF"; BACKOFF=$(( BACKOFF * 2 )); [ "$BACKOFF" -gt "$MAX_BACKOFF" ] && BACKOFF=$MAX_BACKOFF
    continue
  fi

  [ -n "$STOPPING" ] && exit 0
  SLOT="$(slot_dir "$RUN_VER")"
  echo "[entrypoint] Starting sathop.$ROLE (v$RUN_VER, candidate=$CANDIDATE) ..."
  # Run from REPO_DIR (not the slot): components resolve ./data relative to CWD,
  # so the data dir must stay fixed across versions. The slot supplies only the
  # venv (on PATH); its editable install resolves the right per-version src.
  cd "$REPO_DIR"
  export PATH="$SLOT/.venv/bin:$BASE_PATH"
  START_TS=$(date +%s)
  set +e
  python -m "sathop.$ROLE.main" &
  CHILD=$!
  [ -n "$STOPPING" ] && kill -TERM "$CHILD" 2>/dev/null || true   # TERM raced the start

  GATE=
  if [ "$CANDIDATE" = 1 ]; then
    # Health gate: promote to committed iff the candidate is still alive after the
    # window (catches boot-then-crash). A crash inside the window leaves committed
    # unchanged → the post-wait check rolls back to the last-good slot.
    ( sleep "$GATE_SEC"; kill -0 "$CHILD" 2>/dev/null && { commit_slot "$RUN_VER"; echo "[entrypoint] health gate passed → committed v$RUN_VER" >&2; } ) &
    GATE=$!
  else
    commit_slot "$RUN_VER"                                          # orch / first boot
  fi

  wait "$CHILD"; EXIT_CODE=$?
  while kill -0 "$CHILD" 2>/dev/null; do wait "$CHILD"; EXIT_CODE=$?; done
  CHILD=
  [ -n "$GATE" ] && kill "$GATE" 2>/dev/null
  set -e
  ELAPSED=$(( $(date +%s) - START_TS ))

  if [ -n "$STOPPING" ]; then
    echo "[entrypoint] SIGTERM received — container stopping after drain."
    exit 0
  fi

  if [ "$CANDIDATE" = 1 ] && [ "$(cat "$COMMITTED_FILE" 2>/dev/null || true)" != "$RUN_VER" ]; then
    echo "[entrypoint] v$RUN_VER failed health gate (exit $EXIT_CODE after ${ELAPSED}s) — rolling back to v$(cat "$COMMITTED_FILE" 2>/dev/null)" >&2
    rm -f "$INTENT_FILE"            # drop the bad target; do not retry it
    BACKOFF=1
    continue                        # next loop runs the committed (last-good) slot
  fi

  if [ "$EXIT_CODE" -eq 42 ]; then
    echo "[entrypoint] Process removed (exit 42) — stopping container."
    break
  elif [ "$EXIT_CODE" -eq 0 ]; then
    echo "[entrypoint] Restart requested ..."
    BACKOFF=1
  else
    [ "$ELAPSED" -ge "$STABLE_THRESHOLD" ] && BACKOFF=1
    echo "[entrypoint] Process crashed (exit $EXIT_CODE), retrying in ${BACKOFF}s ..."
    sleep "$BACKOFF"; BACKOFF=$(( BACKOFF * 2 )); [ "$BACKOFF" -gt "$MAX_BACKOFF" ] && BACKOFF=$MAX_BACKOFF
  fi
done
