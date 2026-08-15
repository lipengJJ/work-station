#!/bin/bash
# 一键更新部署：拉最新代码 → 重新打包两个镜像 → 重启容器 → 幂等建号。
# 用法：./update.sh [FRONTEND_PORT] [BACKEND_PORT]
# 默认端口：前端 8090 / 后端 8020（与本地 dev 5666/8010 错开，避免冲突）
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

FRONTEND_PORT="${1:-8090}"
BACKEND_PORT="${2:-8020}"

echo "==> 1/4 拉取最新代码"
git pull

echo "==> 2/4 重新打包镜像（backend + frontend）"
docker compose build backend
docker compose build frontend

echo "==> 3/4 重启容器（端口: 前端 ${FRONTEND_PORT} / 后端 ${BACKEND_PORT}）"
BACKEND_PORT="${BACKEND_PORT}" FRONTEND_PORT="${FRONTEND_PORT}" docker compose up -d

echo "==> 4/4 等待就绪 + 初始化管理员账号（幂等）"
for _ in $(seq 1 20); do
  if docker compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8010/api/health')" 2>/dev/null; then
    break
  fi
  sleep 1
done
docker compose exec -T backend python seed.py

echo ""
echo "✅ 更新完成：http://localhost:${FRONTEND_PORT}（账号 admin / admin123）"
