#!/bin/bash
# =============================================================
# workbench 一键启动（本地开发环境）
#   用法: ./start.sh         启动前后端
#   说明: 幂等 —— 重复执行会复用已启动的服务，不会重复拉起
#   日志: logs/backend.log / logs/frontend.log
# =============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[start]${NC} $*"; }
ok()    { echo -e "${GREEN}[start]${NC} $*"; }
warn()  { echo -e "${YELLOW}[start]${NC} $*"; }
die()   { echo -e "${RED}[start]${NC} $*" >&2; exit 1; }

# workbench-notify 分支使用独立端口（避开主工作区 8010/5666、mobile 5676、docker 8090/8020）
BACKEND_PORT="${BACKEND_PORT:-8012}"
FRONTEND_PORT="${FRONTEND_PORT:-5668}"
mkdir -p logs

port_in_use() { lsof -ti tcp:"$1" >/dev/null 2>&1; }

# ---------- 1. 依赖检查 ----------
if [ ! -d backend/.venv ]; then
  warn "backend/.venv 不存在，正在创建虚拟环境并安装依赖 ..."
  if command -v uv >/dev/null 2>&1; then
    (cd backend && uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt)
  else
    (cd backend && python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -r requirements.txt)
  fi
  ok "后端依赖安装完成"
fi

if [ ! -d frontend/node_modules ]; then
  warn "frontend/node_modules 不存在，正在 pnpm install（较慢，请耐心等待）..."
  (cd frontend && pnpm install)
  ok "前端依赖安装完成"
fi

# ---------- 2. 初始化数据库与种子数据（幂等） ----------
info "初始化数据库 / 种子数据（admin/admin123）..."
(cd backend && .venv/bin/python seed.py)
ok "初始化完成"

# ---------- 3. 启动后端 ----------
if port_in_use "$BACKEND_PORT"; then
  warn "端口 ${BACKEND_PORT} 已被占用，跳过后端启动（若为旧进程请先 ./stop.sh）"
else
  info "启动后端 http://localhost:${BACKEND_PORT} ..."
  (cd backend && nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" >> "${ROOT}/logs/backend.log" 2>&1 & echo $! > "${ROOT}/logs/backend.pid")
  ok "后端已拉起 (pid $(cat logs/backend.pid))"
fi

# ---------- 4. 启动前端 ----------
if port_in_use "$FRONTEND_PORT"; then
  warn "端口 ${FRONTEND_PORT} 已被占用，跳过前端启动（若为旧进程请先 ./stop.sh）"
else
  info "启动前端 http://localhost:${FRONTEND_PORT} ..."
  (cd frontend && nohup pnpm --filter @vben/web-antd run dev >> "${ROOT}/logs/frontend.log" 2>&1 & echo $! > "${ROOT}/logs/frontend.pid")
  ok "前端已拉起 (pid $(cat logs/frontend.pid))"
fi

# ---------- 5. 健康检查 ----------
echo ""
info "等待服务就绪 ..."
backend_ok=0; frontend_ok=0
for _ in $(seq 1 60); do
  [ "$backend_ok" = 0 ] && curl -sf "http://localhost:${BACKEND_PORT}/api/health" >/dev/null 2>&1 && backend_ok=1
  [ "$frontend_ok" = 0 ] && curl -sf "http://localhost:${FRONTEND_PORT}/" >/dev/null 2>&1 && frontend_ok=1
  [ "$backend_ok" = 1 ] && [ "$frontend_ok" = 1 ] && break
  sleep 1
done

[ "$backend_ok" = 1 ] && ok "后端就绪  http://localhost:${BACKEND_PORT}  (API 文档 /docs)" || warn "后端未在 60s 内就绪，请查看 logs/backend.log"
[ "$frontend_ok" = 1 ] && ok "前端就绪  http://localhost:${FRONTEND_PORT}" || warn "前端未在 60s 内就绪，请查看 logs/frontend.log"

echo ""
echo -e "${GREEN}==============================================${NC}"
echo -e "${GREEN}  Workbench 已启动${NC}"
echo -e "  前端:  ${CYAN}http://localhost:${FRONTEND_PORT}${NC}"
echo -e "  后端:  ${CYAN}http://localhost:${BACKEND_PORT}${NC}"
echo -e "  账号:  admin / admin123"
echo -e "  停止:  ${YELLOW}./stop.sh${NC}"
echo -e "${GREEN}==============================================${NC}"
