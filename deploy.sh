#!/bin/bash
# 一键构建 + 部署：第一次跑会自动生成 .env（随机密钥）、build 镜像、起容器、建管理员账号。
# 之后再跑就是普通的更新部署（拉最新代码后重新执行即可）。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -f .env ]; then
  echo "==> 未找到 .env，基于 .env.example 生成，并随机写入密钥"
  cp .env.example .env
  for KEY in WORKBENCH_SECRET_KEY; do
    SECRET="$(openssl rand -hex 32)"
    if [[ "$OSTYPE" == "darwin"* ]]; then
      sed -i '' "s#^${KEY}=.*#${KEY}=${SECRET}#" .env
    else
      sed -i "s#^${KEY}=.*#${KEY}=${SECRET}#" .env
    fi
  done
fi

echo "==> docker compose build（顺序构建，避免小磁盘 VM 上并行构建把空间挤爆）"
docker compose build backend
docker compose build frontend

echo "==> docker compose up"
docker compose up -d backend frontend

echo "==> 等待 backend 就绪"
for _ in $(seq 1 20); do
  if docker compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8010/api/health')" 2>/dev/null; then
    break
  fi
  sleep 1
done

echo "==> 初始化管理员账号（已存在则跳过，seed.py 本身是幂等的）"
docker compose exec -T backend python seed.py

FRONTEND_PORT="$(grep -E '^FRONTEND_PORT=' .env | cut -d= -f2 || true)"
FRONTEND_PORT="${FRONTEND_PORT:-80}"

echo ""
echo "部署完成：http://<本机或服务器IP>:${FRONTEND_PORT}"
echo "默认账号 admin / admin123 —— 首次登录后请立刻修改密码"
