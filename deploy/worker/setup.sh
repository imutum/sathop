#!/usr/bin/env bash
set -euo pipefail

# ── SatHop Worker 一键部署 ────────────────────────────────────────────
# 用法:  curl -fsSL <url> | bash
#   或:  bash setup.sh
#
# 在全新云服务器上运行即可启动 worker。自动检测公网 IP，生成随机 ID，
# 使用自签证书。只需预装 Docker。
#
# 环境变量（可在运行前 export，或脚本会交互询问）:
#   SATHOP_ORCH_URL   orchestrator 地址，如 https://orch.example.com:8000
#   SATHOP_TOKEN       API token
#   SATHOP_PORT        宿主端口（默认 443，被占则自动尝试 8443/9443）
#   SATHOP_PUBLIC_IP   公网 IP，留空则自动探测（优先 IPv4）
# ─────────────────────────────────────────────────────────────────────

IMAGE="ghcr.io/imutum/sathop/runtime:latest"
CONTAINER="sathop-worker"
DATA_DIR="/var/lib/sathop/worker"
PORT_CANDIDATES=(443 8443 9443)

# ── 检查 Docker ──────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo "ERROR: docker not found. Install Docker first." >&2
  exit 1
fi

# ── 交互获取参数（未通过环境变量传入时）───────────────────────────────
if [ -z "${SATHOP_ORCH_URL:-}" ]; then
  read -rp "Orchestrator URL: " SATHOP_ORCH_URL
fi
if [ -z "${SATHOP_TOKEN:-}" ]; then
  read -rp "API Token: " SATHOP_TOKEN
fi

# ── 公网 IP：手动指定优先，否则自动探测（优先 IPv4，回退 IPv6）─────────
# 双栈机器上 curl 默认走 IPv6，echo 服务会回 IPv6 地址 → 故 -4 强制 IPv4，
# 与现有机群一致；纯 IPv6 机器才回退 -6（URL 构建处会自动加方括号）。
PUBLIC_IP="${SATHOP_PUBLIC_IP:-}"
if [ -z "$PUBLIC_IP" ]; then
  PUBLIC_IP=$(curl -4 -fsSL --max-time 5 https://ifconfig.me 2>/dev/null \
           || curl -4 -fsSL --max-time 5 https://api.ipify.org 2>/dev/null \
           || curl -6 -fsSL --max-time 5 https://api6.ipify.org 2>/dev/null \
           || echo "")
fi
if [ -z "$PUBLIC_IP" ]; then
  echo "ERROR: cannot detect public IP" >&2
  exit 1
fi
echo "[setup] Public IP: $PUBLIC_IP"

# ── 选择可用端口 ────────────────────────────────────────────────────
pick_port() {
  if [ -n "${SATHOP_PORT:-}" ]; then
    echo "$SATHOP_PORT"
    return
  fi
  for p in "${PORT_CANDIDATES[@]}"; do
    if ! ss -tlnp 2>/dev/null | grep -q ":$p " && \
       ! docker ps --format '{{.Ports}}' 2>/dev/null | grep -q "0.0.0.0:$p->"; then
      echo "$p"
      return
    fi
  done
  echo "ERROR: ports ${PORT_CANDIDATES[*]} all occupied" >&2
  exit 1
}

HOST_PORT=$(pick_port)
echo "[setup] Port: $HOST_PORT"

# ── 生成随机 Worker ID ───────────────────────────────────────────────
WORKER_ID="worker-$(od -An -tx1 -N4 /dev/urandom | tr -d ' ')"
echo "[setup] Worker ID: $WORKER_ID"

# ── 构建 sathop:// URL ──────────────────────────────────────────────
SCHEME=$(echo "$SATHOP_ORCH_URL" | grep -qi '^https' && echo "sathops" || echo "sathop")
ORCH_HOST=$(echo "$SATHOP_ORCH_URL" | sed 's|^[Hh][Tt][Tt][Pp][Ss]\?://||; s|/$||')
ENCODED_TOKEN=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$SATHOP_TOKEN', safe=''))" 2>/dev/null \
             || echo "$SATHOP_TOKEN")
SATHOP_URL="${SCHEME}://${ENCODED_TOKEN}@${ORCH_HOST}"

# ── PUBLIC_URL（443 省略端口，非 443 带端口；IPv6 字面量加方括号）──────
case "$PUBLIC_IP" in
  *:*) PUBLIC_HOST="[$PUBLIC_IP]" ;;   # IPv6 literal must be bracketed in URLs
  *)   PUBLIC_HOST="$PUBLIC_IP" ;;
esac
if [ "$HOST_PORT" = "443" ]; then
  PUBLIC_URL="https://$PUBLIC_HOST"
else
  PUBLIC_URL="https://$PUBLIC_HOST:$HOST_PORT"
fi

# ── 准备数据目录 ────────────────────────────────────────────────────
mkdir -p "$DATA_DIR"

# ── 停掉旧容器（如有）───────────────────────────────────────────────
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
  echo "[setup] Removing existing container ..."
  docker stop "$CONTAINER" 2>/dev/null || true
  docker rm "$CONTAINER" 2>/dev/null || true
fi

# ── 拉取镜像 ────────────────────────────────────────────────────────
echo "[setup] Pulling image ..."
docker pull "$IMAGE"

# ── 启动 ────────────────────────────────────────────────────────────
echo "[setup] Starting worker ..."
docker run -d \
  --name "$CONTAINER" \
  --restart unless-stopped \
  -e SATHOP_ROLE="worker" \
  -e SATHOP_WORKER_ID="$WORKER_ID" \
  -e SATHOP_PUBLIC_URL="$PUBLIC_URL" \
  -e SATHOP_URL="$SATHOP_URL" \
  -p "$HOST_PORT":9000 \
  -v "$DATA_DIR":/app/data \
  -v sathop-repo:/app/repo \
  "$IMAGE"

echo ""
echo "=========================================="
echo "  Worker started!"
echo "  ID:     $WORKER_ID"
echo "  URL:    $PUBLIC_URL"
echo "  Data:   $DATA_DIR"
echo "  Logs:   docker logs -f $CONTAINER"
echo "=========================================="
