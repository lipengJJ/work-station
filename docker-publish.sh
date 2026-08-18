#!/bin/bash
# =============================================================================
# docker-publish.sh — 构建镜像并推送到 Docker Hub（云端部署用）
#
# 用法:
#   ./docker-publish.sh                 # 多架构构建(amd64+arm64) + 推送 Docker Hub ← 云端部署推荐
#   ./docker-publish.sh --local         # 仅构建本机架构镜像(本地运行调试, 不推送)
#   ./docker-publish.sh --local --push  # 仅构建本机架构 + 推送
#   ./docker-publish.sh --help
#
# 环境变量:
#   DOCKERHUB_USER   仓库用户名（默认取 .env 的 DOCKERHUB_USER，缺省 lipengj）
#   IMAGE_TAG        镜像标签（默认 latest）
#
# 说明:
#   - 多架构模式用 docker buildx 构建 linux/amd64 + linux/arm64 双平台并直接 --push，
#     解决云端(x86 服务器)拉不到 arm64-only 镜像的问题
#   - 需先 docker login（或 Docker Desktop 已登录）
#   - 推送完成后可在服务器上: docker compose -f docker-compose.domain.yml pull && up -d
# =============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# ---------------------------- 参数解析 ----------------------------
LOCAL_ONLY=false
DO_PUSH=false
HELP=false
for arg in "$@"; do
  case "$arg" in
    --local) LOCAL_ONLY=true ;;
    --push) DO_PUSH=true ;;
    --help|-h) HELP=true ;;
    *) echo "未知参数: $arg（--help 查看用法）" >&2; exit 1 ;;
  esac
done

if $HELP; then
  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

# ---------------------------- 配置 ----------------------------
DOCKERHUB_USER="${DOCKERHUB_USER:-$(grep -E '^DOCKERHUB_USER=' .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d ' \r' || true)}"
DOCKERHUB_USER="${DOCKERHUB_USER:-lipengj}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
BACKEND_IMAGE="${DOCKERHUB_USER}/workbench-backend:${IMAGE_TAG}"
FRONTEND_IMAGE="${DOCKERHUB_USER}/workbench-frontend:${IMAGE_TAG}"

# 默认多架构模式 = 构建 + 推送；--local 不推（除非再加 --push）
if ! $LOCAL_ONLY; then
  DO_PUSH=true
fi

echo "=============================================================="
echo " 仓库用户   : ${DOCKERHUB_USER}"
echo " 镜像标签   : ${IMAGE_TAG}"
echo " 模式       : $($LOCAL_ONLY && echo '本机架构(本地调试)' || echo '多架构 amd64+arm64(云端部署)')"
echo " 推送       : $($DO_PUSH && echo '是' || echo '否')"
echo "=============================================================="

# ---------------------------- 前置检查 ----------------------------
command -v docker >/dev/null 2>&1 || { echo "✗ 未找到 docker" >&2; exit 1; }
if ! docker info >/dev/null 2>&1; then
  echo "✗ Docker 未运行，请先启动 Docker Desktop/daemon" >&2
  exit 1
fi
if $DO_PUSH; then
  if ! docker system info 2>/dev/null | grep -qi username && [ ! -s "$HOME/.docker/config.json" ]; then
    echo "✗ 未检测到 Docker Hub 登录，请先执行: docker login" >&2
    exit 1
  fi
fi

# ---------------------------- 构建 + 推送 ----------------------------
build_and_push() {
  local name="$1" context="$2" platforms="$3"
  echo ""
  echo ">>> 构建 ${name}（${platforms}）"
  if $DO_PUSH; then
    docker buildx build --platform "${platforms}" --push -t "${name}" "${context}"
  else
    docker build -t "${name}" "${context}"
  fi
  echo "✓ ${name} 完成"
}

if $LOCAL_ONLY; then
  # 本机架构（本地调试用）
  build_and_push "${BACKEND_IMAGE}" "./backend" "local"
  build_and_push "${FRONTEND_IMAGE}" "./frontend" "local"
else
  # 多架构（云端部署用）—— 顺序构建避免小磁盘机器并行把空间挤爆
  if ! docker buildx ls >/dev/null 2>&1; then
    echo "✗ 需要 buildx（Docker Desktop 自带），请确认 docker buildx 可用" >&2
    exit 1
  fi
  build_and_push "${BACKEND_IMAGE}" "./backend" "linux/amd64,linux/arm64"
  build_and_push "${FRONTEND_IMAGE}" "./frontend" "linux/amd64,linux/arm64"
fi

# ---------------------------- 结果 ----------------------------
echo ""
echo "=============================================================="
if $DO_PUSH; then
  echo " ✓ 已推送: ${BACKEND_IMAGE}"
  echo "           ${FRONTEND_IMAGE}"
  echo ""
  echo " 云端部署:"
  echo "   docker compose -f docker-compose.domain.yml pull"
  echo "   docker compose -f docker-compose.domain.yml up -d"
  echo "   docker compose -f docker-compose.domain.yml exec backend python seed.py"
else
  echo " ✓ 本地镜像: ${BACKEND_IMAGE}"
  echo "            ${FRONTEND_IMAGE}"
  echo " 可运行本地部署: BACKEND_PORT=8020 FRONTEND_PORT=8090 docker compose up -d"
fi
echo "=============================================================="
