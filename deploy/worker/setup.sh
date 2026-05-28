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
# ─────────────────────────────────────────────────────────────────────

IMAGE="ghcr.io/imutum/sathop/runtime:latest"
CONTAINER="sathop-worker"
DATA_DIR="/var/lib/sathop/worker"

# ── 检查 Docker ──────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo "ERROR: docker not found. Install Docker first." >&2
  exit 1
fi

# ── 交互获取参数（未通过环境变量传入时）───────────────────────────────
if [ -z "${SATHOP_ORCH_URL:-}" ]; then
  read -rp "Orchestrator URL (如 https://sathop.mutum.top:16181): " SATHOP_ORCH_URL
fi
if [ -z "${SATHOP_TOKEN:-}" ]; then
  read -rp "API Token: " SATHOP_TOKEN
fi

# ── 自动检测公网 IP ──────────────────────────────────────────────────
PUBLIC_IP=$(curl -fsSL --max-time 5 https://ifconfig.me 2>/dev/null \
         || curl -fsSL --max-time 5 https://api.ipify.org 2>/dev/null \
         || echo "")
if [ -z "$PUBLIC_IP" ]; then
  echo "ERROR: cannot detect public IP" >&2
  exit 1
fi
echo "[setup] Public IP: $PUBLIC_IP"

# ── 生成随机 Worker ID ───────────────────────────────────────────────
WORKER_ID="worker-$(head -c 4 /dev/urandom | xxd -p)"
echo "[setup] Worker ID: $WORKER_ID"

# ── 构建 sathop:// URL ──────────────────────────────────────────────
SCHEME=$(echo "$SATHOP_ORCH_URL" | grep -q '^https' && echo "sathops" || echo "sathop")
HOST_PORT=$(echo "$SATHOP_ORCH_URL" | sed 's|^https\?://||; s|/$||')
SATHOP_URL="${SCHEME}://${SATHOP_TOKEN}@${HOST_PORT}"

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
  -e SATHOP_PUBLIC_URL="https://$PUBLIC_IP" \
  -e SATHOP_URL="$SATHOP_URL" \
  -p 443:9000 \
  -v "$DATA_DIR":/app/data \
  -v sathop-repo:/app/repo \
  "$IMAGE"

echo ""
echo "=========================================="
echo "  Worker started!"
echo "  ID:     $WORKER_ID"
echo "  IP:     $PUBLIC_IP"
echo "  Data:   $DATA_DIR"
echo "  Logs:   docker logs -f $CONTAINER"
echo "=========================================="
