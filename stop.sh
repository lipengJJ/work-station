#!/bin/bash
# =============================================================
# workbench 一键停止（本地开发环境）
#   用法: ./stop.sh          停止前后端
#   说明: 优先按 pid 文件停止，再用端口兜底，避免遗留子进程
# =============================================================
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${YELLOW}[stop]${NC} $*"; }
ok()    { echo -e "${GREEN}[stop]${NC} $*"; }
die()   { echo -e "${RED}[stop]${NC} $*" >&2; exit 1; }

BACKEND_PORT="${BACKEND_PORT:-8010}"
FRONTEND_PORT="${FRONTEND_PORT:-5666}"

stop_pid_file() {
  local name="$1" file="$2"
  if [ -f "$file" ]; then
    local pid
    pid="$(cat "$file" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      info "已发送停止信号: ${name} (pid ${pid})"
    fi
    rm -f "$file"
  fi
}

stop_by_port() {
  local name="$1" port="$2"
  local pids
  pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    # 先 SIGTERM，等 3 秒，再 SIGKILL 兜底
    echo "$pids" | xargs kill >/dev/null 2>&1 || true
    sleep 3
    pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
    if [ -n "$pids" ]; then
      echo "$pids" | xargs kill -9 >/dev/null 2>&1 || true
    fi
    ok "${name} (端口 ${port}) 已停止"
  else
    info "${name} (端口 ${port}) 未在运行"
  fi
}

stop_pid_file "后端" "logs/backend.pid"
stop_pid_file "前端" "logs/frontend.pid"
stop_by_port "后端" "$BACKEND_PORT"
stop_by_port "前端" "$FRONTEND_PORT"

echo ""
ok "Workbench 已停止"
