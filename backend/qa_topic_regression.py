"""QA 回归测试：AI 热点 → 主题跟踪模式（feature/ai-trending 重构，T01-T05 独立验证）。

覆盖：
A1. 后端新代码在跑（GET /api/ai-trending/topics 不 404）
A2. 主题 CRUD 全链路（创建/列表/run-now/items/限频/去重/更新/推送配置/删除/404）
A3. 既有功能回归（/items /sources /refresh /push/* deprecated + OpenAPI）
A4. 数据一致性（SQLite 直查）
A5. 未登录 401
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime, timezone

import requests

BASE = "http://127.0.0.1:8010"
DB_PATH = "/Users/lipeng01/vscode/workbench/backend/workbench.db"

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def login() -> str:
    r = requests.post(
        f"{BASE}/api/auth/login",
        data={"username": "admin", "password": "admin123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


def auth_h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def wait_scan_done(token: str, topic_id: int, timeout: int = 120) -> dict:
    """轮询 GET /topics/{id} 直到 status != running（idle/failed）。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = requests.get(f"{BASE}/api/ai-trending/topics/{topic_id}", headers=auth_h(token), timeout=10)
        if r.status_code != 200:
            time.sleep(3)
            continue
        last = r.json()
        if last.get("status") != "running":
            return last
        time.sleep(3)
    return last or {}


def main() -> None:
    token = login()
    h = auth_h(token)
    print("== A1: 后端新代码在跑 ==")
    r = requests.get(f"{BASE}/api/ai-trending/topics", headers=h, timeout=10)
    check("A1 topics 端点不 404", r.status_code != 404, f"status={r.status_code}")

    print("\n== A5: 未登录访问 ==")
    anon_checks = [
        ("GET", "/api/ai-trending/topics"),
        ("GET", "/api/ai-trending/topics/1"),
        ("POST", "/api/ai-trending/topics/1/run-now"),
        ("GET", "/api/ai-trending/topics/1/items"),
        ("GET", "/api/ai-trending/topics/1/push-config"),
    ]
    for method, path in anon_checks:
        rr = requests.request(method, f"{BASE}{path}", timeout=10)
        check(f"A5 未登录 {method} {path} -> 401", rr.status_code == 401, f"got {rr.status_code}")

    print("\n== A3: 既有功能回归 ==")
    r = requests.get(f"{BASE}/api/ai-trending/items", headers=h, timeout=10)
    items_total = r.json().get("total", 0) if r.status_code == 200 else -1
    check("A3 GET /items 200", r.status_code == 200, f"total={items_total}")
    check("A3 /items total >= 351", items_total >= 351, f"total={items_total}")

    r = requests.get(f"{BASE}/api/ai-trending/sources", headers=h, timeout=10)
    srcs = r.json() if r.status_code == 200 else []
    check("A3 GET /sources 200 + 7 源", r.status_code == 200 and len(srcs) == 7, f"count={len(srcs)} sources={[s.get('source_id') for s in srcs]}")
    check("A3 /sources 含 7 个约定源", {s.get("source_id") for s in srcs} == {"hn", "github", "arxiv", "hf_models", "hf_papers", "infoq", "kr36"}, str([s.get("source_id") for s in srcs]))

    r = requests.post(f"{BASE}/api/ai-trending/refresh", headers=h, timeout=10)
    # 200 = 正常触发；429 = 10 分钟限频（前一次测试触发过）→ 端点本身可用
    check("A3 POST /refresh 可用（200 或 429 限频）", r.status_code in (200, 429), f"got {r.status_code} {r.text[:120]}")

    for path in ["/api/ai-trending/push/config", "/api/ai-trending/push/latest"]:
        rr = requests.get(f"{BASE}{path}", headers=h, timeout=10)
        check(f"A3 {path} 仍可用", rr.status_code == 200, f"got {rr.status_code}")

    # OpenAPI deprecated 标记（按 operation 检查：config GET/PUT + latest + test = 4 个 operation）
    r = requests.get(f"{BASE}/openapi.json", timeout=10)
    spec = r.json()
    push_ops = []
    for p, methods in spec["paths"].items():
        if "/push/" in p:
            for m, v in methods.items():
                if m in ("get", "post", "put", "delete"):
                    push_ops.append((p, m, bool(v.get("deprecated"))))
    check("A3 OpenAPI 含 4 个 push operation", len(push_ops) == 4, str([(p, m) for p, m, _ in push_ops]))
    check("A3 push 端点全部 deprecated=true", all(d for _, _, d in push_ops), str(push_ops))

    print("\n== A2: 主题 CRUD 全链路 ==")
    # ---- 创建 ----
    topic_name = f"QA回归主题-{int(time.time())}"
    body = {"name": topic_name, "keywords": ["大模型", "LLM"], "interval_minutes": 60, "enabled": True}
    r = requests.post(f"{BASE}/api/ai-trending/topics", json=body, headers=h, timeout=10)
    check("A2 POST /topics 创建 200", r.status_code == 200, r.text[:200])
    created = r.json()
    tid = created.get("id")
    check("A2 创建返回 id", tid is not None, f"id={tid}")
    check("A2 创建返回 hit_count 字段", "hit_count" in created, f"hit_count={created.get('hit_count')}")
    check("A2 创建返回 push 内嵌配置", isinstance(created.get("push"), dict) and created["push"].get("channel") == "wecom", str(created.get("push")))

    r = requests.get(f"{BASE}/api/ai-trending/topics", headers=h, timeout=10)
    lst = r.json()
    check("A2 GET /topics 列表含新主题", any(t.get("id") == tid for t in lst), f"count={len(lst)}")
    check("A2 列表条目含 hit_count", all("hit_count" in t for t in lst))

    # ---- 参数校验：非法 interval / 空 keywords ----
    for bad_body, label in [
        ({"name": "bad", "keywords": ["x"], "interval_minutes": 0}, "interval=0"),
        ({"name": "bad", "keywords": ["x"], "interval_minutes": -5}, "interval=-5"),
        ({"name": "bad", "keywords": ["x"], "interval_minutes": 45}, "interval=45(不在集合)"),
        ({"name": "bad", "keywords": [], "interval_minutes": 60}, "空 keywords"),
        ({"name": "bad", "keywords": ["  "], "interval_minutes": 60}, "全空白 keywords"),
        ({"name": "", "keywords": ["x"], "interval_minutes": 60}, "空 name"),
    ]:
        rr = requests.post(f"{BASE}/api/ai-trending/topics", json=bad_body, headers=h, timeout=10)
        check(f"A2 非法创建 {label} -> 400", rr.status_code == 400, f"got {rr.status_code} {rr.text[:120]}")

    # ---- 不存在的主题 GET/PUT/DELETE -> 404 ----
    rr = requests.get(f"{BASE}/api/ai-trending/topics/999999", headers=h, timeout=10)
    check("A2 不存在 GET -> 404", rr.status_code == 404, f"got {rr.status_code}")
    rr = requests.put(f"{BASE}/api/ai-trending/topics/999999", json={"name": "x"}, headers=h, timeout=10)
    check("A2 不存在 PUT -> 404", rr.status_code == 404, f"got {rr.status_code}")
    rr = requests.delete(f"{BASE}/api/ai-trending/topics/999999", headers=h, timeout=10)
    check("A2 不存在 DELETE -> 404", rr.status_code == 404, f"got {rr.status_code}")
    rr = requests.post(f"{BASE}/api/ai-trending/topics/999999/run-now", headers=h, timeout=10)
    check("A2 不存在 run-now -> 404", rr.status_code == 404, f"got {rr.status_code}")
    rr = requests.get(f"{BASE}/api/ai-trending/topics/999999/items", headers=h, timeout=10)
    check("A2 不存在 items -> 404", rr.status_code == 404, f"got {rr.status_code}")

    # ---- run-now ----
    r = requests.post(f"{BASE}/api/ai-trending/topics/{tid}/run-now", headers=h, timeout=10)
    check("A2 POST run-now 200", r.status_code == 200, r.text[:200])
    first_run_ts = time.time()

    # ---- 60s 内再次 run-now -> 429 ----
    r = requests.post(f"{BASE}/api/ai-trending/topics/{tid}/run-now", headers=h, timeout=10)
    check("A2 60s 内再次 run-now -> 429", r.status_code == 429, f"got {r.status_code} {r.text[:120]}")

    # ---- 轮询等待扫描完成 ----
    print("    ... 等待主题扫描完成（最长 120s）...")
    topic = wait_scan_done(token, tid)
    check("A2 扫描后 status=idle", topic.get("status") == "idle", f"status={topic.get('status')} msg={topic.get('last_run_message')}")
    check("A2 last_run_at 已更新", topic.get("last_run_at") is not None, str(topic.get("last_run_at")))
    check("A2 last_item_count>0", (topic.get("last_item_count") or 0) > 0, f"count={topic.get('last_item_count')} msg={topic.get('last_run_message')}")
    first_hit_count = topic.get("hit_count") or 0
    check("A2 hit_count>0", first_hit_count > 0, f"hit_count={first_hit_count}")

    # ---- items 详情 ----
    r = requests.get(f"{BASE}/api/ai-trending/topics/{tid}/items?sort=heat&page=1&page_size=20", headers=h, timeout=10)
    check("A2 GET items 200", r.status_code == 200, r.text[:200])
    page = r.json()
    items = page.get("items") or []
    check("A2 items 有数据", len(items) > 0, f"len={len(items)} total={page.get('total')}")
    required_fields = ["source", "title", "url", "summary", "heat_score", "category", "published_at"]
    field_ok = all(all(f in it for f in required_fields) for it in items)
    check("A2 items 字段完整", field_ok, str(list(items[0].keys()) if items else "no items"))
    url_ok = all(str(it.get("url") or "").startswith(("http://", "https://")) for it in items)
    check("A2 items url 合法", url_ok)
    # 分页 & sort=time
    r2 = requests.get(f"{BASE}/api/ai-trending/topics/{tid}/items?sort=time&page=1&page_size=5", headers=h, timeout=10)
    check("A2 items sort=time 200", r2.status_code == 200, r2.text[:120])
    r3 = requests.get(f"{BASE}/api/ai-trending/topics/{tid}/items?sort=bogus", headers=h, timeout=10)
    check("A2 items 非法 sort -> 400", r3.status_code == 400, f"got {r3.status_code}")

    # ---- 去重：等 60s 冷却后再 run-now，hit_count 不增长 ----
    print("    ... 等待 run-now 冷却 60s 后再触发一次（验证去重）...")
    time.sleep(max(0, 62 - (time.time() - first_run_ts)))
    r = requests.post(f"{BASE}/api/ai-trending/topics/{tid}/run-now", headers=h, timeout=10)
    check("A2 冷却后再次 run-now 200", r.status_code == 200, f"got {r.status_code} {r.text[:120]}")
    topic2 = wait_scan_done(token, tid)
    second_hit_count = topic2.get("hit_count") or 0
    check("A2 重复扫描 hit_count 不增长（去重）", second_hit_count == first_hit_count, f"first={first_hit_count} second={second_hit_count}")
    # DB 直查无重复 (topic_id, item_id)
    conn = sqlite3.connect(DB_PATH)
    dup = conn.execute(
        "SELECT COUNT(*) FROM (SELECT topic_id,item_id FROM ai_trending_topic_hit WHERE topic_id=? GROUP BY topic_id,item_id HAVING COUNT(*)>1)",
        (tid,),
    ).fetchone()[0]
    conn.close()
    check("A2 DB 无重复 (topic_id,item_id)", dup == 0, f"dup={dup}")

    # ---- PUT 更新 ----
    new_name = f"QA更新主题-{int(time.time())}"
    r = requests.put(
        f"{BASE}/api/ai-trending/topics/{tid}",
        json={"name": new_name, "keywords": ["AI Agent", "智能体"], "interval_minutes": 30},
        headers=h, timeout=10,
    )
    check("A2 PUT /topics 200", r.status_code == 200, r.text[:200])
    upd = r.json()
    check("A2 PUT 回读 name 一致", upd.get("name") == new_name, f"{upd.get('name')}")
    check("A2 PUT 回读 keywords 一致", upd.get("keywords") == ["AI Agent", "智能体"], str(upd.get("keywords")))
    check("A2 PUT 回读 interval 一致", upd.get("interval_minutes") == 30, str(upd.get("interval_minutes")))
    r = requests.get(f"{BASE}/api/ai-trending/topics/{tid}", headers=h, timeout=10)
    check("A2 GET 回读与 PUT 一致", r.json().get("name") == new_name and r.json().get("interval_minutes") == 30)

    # PUT 非法 interval / 空 keywords -> 400
    for bad_body, label in [
        ({"interval_minutes": 0}, "interval=0"),
        ({"interval_minutes": -1}, "interval=-1"),
        ({"interval_minutes": 100}, "interval=100"),
        ({"keywords": []}, "空 keywords"),
        ({"keywords": ["  "]}, "全空白 keywords"),
    ]:
        rr = requests.put(f"{BASE}/api/ai-trending/topics/{tid}", json=bad_body, headers=h, timeout=10)
        check(f"A2 PUT 非法 {label} -> 400", rr.status_code == 400, f"got {rr.status_code} {rr.text[:120]}")

    # ---- push-config ----
    for channel in ["wecom", "dingtalk", "feishu", "email"]:
        rr = requests.put(
            f"{BASE}/api/ai-trending/topics/{tid}/push-config",
            json={"enabled": True, "channel": channel, "frequency": "daily", "time": "09:30"},
            headers=h, timeout=10,
        )
        cfg = rr.json() if rr.status_code == 200 else {}
        check(f"A2 push-config channel={channel} 200 回读一致", rr.status_code == 200 and cfg.get("channel") == channel and cfg.get("time") == "09:30" and cfg.get("enabled") is True, f"got {rr.status_code} {rr.text[:120]}")
    r = requests.get(f"{BASE}/api/ai-trending/topics/{tid}/push-config", headers=h, timeout=10)
    check("A2 GET push-config 200 回读", r.status_code == 200 and r.json().get("channel") == "email", r.text[:120])
    # 非法 channel/time -> 400
    for bad_cfg, label in [
        ({"channel": "slack"}, "channel=slack"),
        ({"channel": "wecom", "time": "25:00"}, "time=25:00"),
        ({"channel": "wecom", "time": "09:99"}, "time=09:99"),
        ({"channel": "wecom", "time": "9:00"}, "time=9:00"),
        ({"channel": "wecom", "frequency": "hourly"}, "frequency=hourly"),
    ]:
        rr = requests.put(f"{BASE}/api/ai-trending/topics/{tid}/push-config", json=bad_cfg, headers=h, timeout=10)
        check(f"A2 push-config 非法 {label} -> 400", rr.status_code == 400, f"got {rr.status_code} {rr.text[:120]}")

    # ---- 推送配置后列表徽标（push 内嵌回读） ----
    r = requests.get(f"{BASE}/api/ai-trending/topics", headers=h, timeout=10)
    t = next((x for x in r.json() if x.get("id") == tid), {})
    check("A2 列表 push 内嵌回读 email+enabled", t.get("push", {}).get("channel") == "email" and t.get("push", {}).get("enabled") is True, str(t.get("push")))

    # ---- DELETE ----
    r = requests.delete(f"{BASE}/api/ai-trending/topics/{tid}", headers=h, timeout=10)
    check("A2 DELETE 200", r.status_code == 200 and r.json().get("success") is True, f"got {r.status_code} {r.text[:120]}")
    conn = sqlite3.connect(DB_PATH)
    topic_left = conn.execute("SELECT COUNT(*) FROM ai_trending_topic WHERE id=?", (tid,)).fetchone()[0]
    hit_left = conn.execute("SELECT COUNT(*) FROM ai_trending_topic_hit WHERE topic_id=?", (tid,)).fetchone()[0]
    conn.close()
    check("A2 DB topic 无残留", topic_left == 0, f"topic_left={topic_left}")
    check("A2 DB topic_hit 无残留", hit_left == 0, f"hit_left={hit_left}")

    print("\n== A4: 数据一致性（直查 SQLite）==")
    conn = sqlite3.connect(DB_PATH)
    # topic 表结构
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ai_trending_topic)")}
    expect_cols = {"id", "name", "keywords", "interval_minutes", "enabled", "status", "last_run_at", "last_run_message", "last_item_count", "push_enabled", "push_channel", "push_frequency", "push_time", "created_at", "updated_at"}
    check("A4 topic 表结构齐全", expect_cols <= cols, f"missing={expect_cols - cols}")
    # hit Unique 约束存在
    idx = conn.execute("PRAGMA index_list(ai_trending_topic_hit)").fetchall()
    uniq = any(i[2] == 1 for i in idx)
    check("A4 topic_hit 有唯一约束", uniq)
    # push_log topic_id 列
    pl_cols = {r[1] for r in conn.execute("PRAGMA table_info(ai_trending_push_log)")}
    check("A4 push_log 有 topic_id 列", "topic_id" in pl_cols)
    # items url_hash 无重复
    dup_hash = conn.execute("SELECT COUNT(*) FROM (SELECT url_hash FROM ai_trending_items GROUP BY url_hash HAVING COUNT(*)>1)").fetchone()[0]
    check("A4 items url_hash 无重复", dup_hash == 0, f"dup={dup_hash}")
    conn.close()

    print("\n================ SUMMARY ================")
    print(f"Total: {len(PASS) + len(FAIL)} | Passed: {len(PASS)} | Failed: {len(FAIL)}")
    if FAIL:
        print("Failed:")
        for f in FAIL:
            print("  -", f)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
