"""Round 2 失败恢复验证：注入扫描失败 → status=failed 落库 → 恢复后 run-now 可再次触发 → status=idle。

思路（不改服务端代码）：
- 在本进程内 import 同一模块实例，monkeypatch topic_service._upsert_item 抛异常
  （_upsert_item 在 per-source try 之外 → 异常逃逸到外层 except → 走 failed 分支），
  用真实 SessionLocal 写入共享 DB（status=failed + last_run_message 落库）；
- 再通过 :8010 API 验证：GET 显示 failed；run-now 可再次触发（非 429 死锁）→ 扫描完成 status=idle。
"""
from __future__ import annotations

import sys
import time

import requests

sys.path.insert(0, "/Users/lipeng01/vscode/workbench/backend")

from app.ai_trending.services import topic_service  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402

BASE = "http://127.0.0.1:8010"
PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> None:
    # 登录
    r = requests.post(f"{BASE}/api/auth/login", data={"username": "admin", "password": "admin123"},
                      headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=10)
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # 建主题
    name = f"QA失败恢复-{int(time.time())}"
    r = requests.post(f"{BASE}/api/ai-trending/topics",
                      json={"name": name, "keywords": ["大模型"], "interval_minutes": 60, "enabled": True},
                      headers=h, timeout=10)
    check("F1 创建主题 200", r.status_code == 200, r.text[:120])
    tid = r.json().get("id")
    check("F1 拿到 id", tid is not None, f"id={tid}")
    if not tid:
        return

    # 注入失败：monkeypatch _upsert_item 抛异常 → run_topic_scan 走 failed 分支
    def _boom(db, raw):
        raise RuntimeError("QA注入的扫描失败")

    orig = topic_service._upsert_item
    topic_service._upsert_item = _boom
    try:
        topic_service.run_topic_scan(tid)
    finally:
        topic_service._upsert_item = orig

    # 验证 DB 状态 failed + last_run_message 落库
    r = requests.get(f"{BASE}/api/ai-trending/topics/{tid}", headers=h, timeout=10)
    t = r.json()
    check("F2 注入失败后 status=failed", t.get("status") == "failed", f"status={t.get('status')}")
    check("F2 last_run_message 落库", "注入的扫描失败" in (t.get("last_run_message") or ""), str(t.get("last_run_message")))
    check("F2 last_run_at 已更新", t.get("last_run_at") is not None, str(t.get("last_run_at")))

    # 恢复后 run-now 可再次触发（非 429「正在扫描中」死锁）
    r = requests.post(f"{BASE}/api/ai-trending/topics/{tid}/run-now", headers=h, timeout=10)
    check("F3 failed 后 run-now 可再次触发（200 非 429）", r.status_code == 200, f"got {r.status_code} {r.text[:120]}")
    if r.status_code == 200:
        # 等待扫描完成（真实扫描，最长 120s）
        deadline = time.time() + 120
        last = None
        while time.time() < deadline:
            rr = requests.get(f"{BASE}/api/ai-trending/topics/{tid}", headers=h, timeout=10)
            if rr.status_code == 200:
                last = rr.json()
                if last.get("status") != "running":
                    break
            time.sleep(3)
        check("F4 恢复后扫描完成 status=idle", (last or {}).get("status") == "idle", f"status={(last or {}).get('status')} msg={(last or {}).get('last_run_message')}")
        check("F4 恢复后 last_run_message 为成功信息", "扫描完成" in ((last or {}).get("last_run_message") or ""), str((last or {}).get("last_run_message")))

    # 清理
    r = requests.delete(f"{BASE}/api/ai-trending/topics/{tid}", headers=h, timeout=10)
    check("F5 DELETE 清理 200", r.status_code == 200, r.text[:120])

    print("\n===== SUMMARY =====")
    print(f"Total: {len(PASS)+len(FAIL)} | Passed: {len(PASS)} | Failed: {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print("  -", f)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
