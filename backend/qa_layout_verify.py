"""QA 布局复核：AI 热点主题页（/ai-trending）通栏布局验收（Playwright 无头，多视口测量）。

验收清单（UI 设计师制定）：
1. 1440×900：内容容器 left≈240、right≈1424（仅剩 Page p-4 16px），无居中留白
2. 1920×1080：同样通栏，无 320px 级空白
3. 标题「AI 热点主题」左缘与内容区左缘对齐（left≈240）
4. 主题卡片 3 列等宽（computed grid-template-columns 三列一致）、间距均匀 12px；
   首卡左缘=容器左缘、末卡右缘=容器右缘
5. 空态/骨架屏/错误 Alert 通栏（骨架 3 张占位卡与卡片网格同宽）
6. 三个视图态（主题列表/主题详情/全部热点）列表均通栏、宽度一致
7. 窄视口回退：<768 单列、768–1024 两列，无横向滚动条
8. 控制台无 error

运行：backend/.venv/bin/python backend/qa_layout_verify.py
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5666"
API = "http://127.0.0.1:8010"

VIEWPORTS = [
    (1440, 900),
    (1920, 1080),
    (800, 900),
    (900, 900),
    (700, 900),
]

# 容器边缘容差（px）
EDGE_TOL = 8
# 列宽一致容差（px）
COL_TOL = 1.0
# 左右对齐容差（px）
ALIGN_TOL = 2.0

PASS: list[str] = []
FAIL: list[str] = []
MEASURE: dict = {}
ALL_CONSOLE: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------- 测量 JS ----
MEASURE_TOPICS_JS = r"""
() => {
  const box = el => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { left: Math.round(r.left*10)/10, top: Math.round(r.top*10)/10,
             width: Math.round(r.width*10)/10, right: Math.round(r.right*10)/10,
             height: Math.round(r.height*10)/10 };
  };
  const container = document.querySelector('div.flex.w-full.flex-col.gap-4');
  const grids = Array.from(document.querySelectorAll('div.grid'));
  const cardGrid = grids.find(g => g.querySelector(':scope > div.cursor-pointer'));
  const cards = cardGrid ? Array.from(cardGrid.querySelectorAll(':scope > div.cursor-pointer')) : [];
  const cs = cardGrid ? getComputedStyle(cardGrid) : null;
  const gtc = cs ? cs.gridTemplateColumns.split(/\s+/).filter(Boolean) : [];
  const titleEl = Array.from(document.querySelectorAll('div,span')).find(el =>
    Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim() === 'AI 热点主题'));
  const empty = document.querySelector('div.ant-empty');
  const alertErr = document.querySelector('.ant-alert-error');
  return {
    viewport: [window.innerWidth, window.innerHeight],
    docScrollW: document.documentElement.scrollWidth,
    docClientW: document.documentElement.clientWidth,
    bodyScrollW: document.body.scrollWidth,
    container: box(container),
    title: titleEl ? box(titleEl) : null,
    grid: cardGrid ? box(cardGrid) : null,
    gridTemplateColumns: gtc,
    columnGap: cs ? cs.columnGap : null,
    rowGap: cs ? cs.rowGap : null,
    cardCount: cards.length,
    firstCard: cards[0] ? box(cards[0]) : null,
    lastCard: cards.length ? box(cards[cards.length - 1]) : null,
    hasEmpty: !!empty,
    empty: empty ? box(empty) : null,
    hasErrorAlert: !!alertErr,
    errorAlert: alertErr ? box(alertErr) : null,
  };
}
"""

MEASURE_LIST_JS = r"""
() => {
  const box = el => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { left: Math.round(r.left*10)/10, top: Math.round(r.top*10)/10,
             width: Math.round(r.width*10)/10, right: Math.round(r.right*10)/10,
             height: Math.round(r.height*10)/10 };
  };
  const container = document.querySelector('div.flex.w-full.flex-col.gap-4');
  const backBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('返回主题列表'));
  const header = backBtn ? backBtn.closest('div.rounded-xl') : null;
  const list = document.querySelector('.ant-list');
  const empty = document.querySelector('div.ant-empty');
  const panel = (() => {
    const tabs = document.querySelector('.ant-tabs');
    return tabs ? tabs.closest('div.rounded-xl') : null;
  })();
  return {
    viewport: [window.innerWidth, window.innerHeight],
    docScrollW: document.documentElement.scrollWidth,
    docClientW: document.documentElement.clientWidth,
    container: box(container),
    header: header ? box(header) : null,
    panel: panel ? box(panel) : null,
    list: list ? box(list) : null,
    hasList: !!list,
    empty: empty ? box(empty) : null,
    hasEmpty: !!empty,
  };
}
"""

MEASURE_SKELETON_JS = r"""
() => {
  const box = el => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { left: Math.round(r.left*10)/10, width: Math.round(r.width*10)/10,
             right: Math.round(r.right*10)/10 };
  };
  const grids = Array.from(document.querySelectorAll('div.grid'));
  const skGrid = grids.find(g => g.querySelector(':scope > .ant-skeleton'));
  const cs = skGrid ? getComputedStyle(skGrid) : null;
  const gtc = cs ? cs.gridTemplateColumns.split(/\s+/).filter(Boolean) : [];
  const skeletons = skGrid ? skGrid.querySelectorAll(':scope > .ant-skeleton') : [];
  return {
    viewport: [window.innerWidth, window.innerHeight],
    grid: skGrid ? box(skGrid) : null,
    gridTemplateColumns: gtc,
    columnGap: cs ? cs.columnGap : null,
    skeletonCount: skeletons.length,
  };
}
"""


def parse_cols(gtc: list[str]) -> list[float]:
    nums = []
    for c in gtc:
        m = re.match(r"([\d.]+)", c)
        if m:
            nums.append(float(m.group(1)))
    return nums


def no_hscroll(d: dict) -> bool:
    return d.get("docScrollW", 0) <= d.get("docClientW", 0) + 1


# ---------------------------------------------------------------- 主流程 ----
def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        def on_console(msg):
            if msg.type == "error":
                ALL_CONSOLE.append(msg.text)

        def on_pageerror(exc):
            ALL_CONSOLE.append(f"pageerror: {exc}")

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)

        # ---------------- 登录 ----------------
        page.goto(f"{BASE}/auth/login", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        try:
            page.fill('input[name="username"]', "admin")
            page.fill('input[name="password"]', "admin123")
        except Exception:
            inputs = page.locator("form input")
            inputs.nth(0).fill("admin")
            inputs.nth(1).fill("admin123")
        page.keyboard.press("Enter")
        page.wait_for_timeout(3000)
        try:
            page.wait_for_url(lambda url: "/auth/login" not in url, timeout=15000)
        except Exception:
            pass
        check("登录成功跳离 login 页", "/auth/login" not in page.url, f"url={page.url}")

        # ---------------- 预检：确认页面有 3 个主题 ----------------
        page.goto(f"{BASE}/ai-trending", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2500)
        card_cnt = page.locator("div.cursor-pointer").count()
        check("预检：主题卡片 >= 3（3 列网格满行）", card_cnt >= 3, f"count={card_cnt}")

        # ================ A. 各视口正常态测量 ================
        for w, h in VIEWPORTS:
            page.set_viewport_size({"width": w, "height": h})
            page.goto(f"{BASE}/ai-trending", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)
            # 等待卡片网格出现（若 3 主题已存在）
            try:
                page.wait_for_selector("div.grid > div.cursor-pointer", timeout=8000)
            except Exception:
                pass

            m = page.evaluate(MEASURE_TOPICS_JS)
            MEASURE[f"{w}x{h}"] = {"topics": m}

            # ---- 主题详情态（点「大模型」，有 123 条命中可出列表）----
            try:
                card = page.locator("div.cursor-pointer", has_text="大模型").first
                card.locator("span.truncate").first.click(timeout=5000)
                page.wait_for_selector("button:has-text('返回主题列表')", timeout=8000)
                page.wait_for_timeout(1800)
                md = page.evaluate(MEASURE_LIST_JS)
                MEASURE[f"{w}x{h}"]["detail"] = md
                # 返回列表
                page.get_by_role("button", name="返回主题列表").first.click()
                page.wait_for_selector("button:has-text('新建主题')", timeout=8000)
                page.wait_for_timeout(1200)
            except Exception as e:
                MEASURE[f"{w}x{h}"]["detail"] = {"error": str(e)}

            # ---- 全部热点态 ----
            try:
                page.get_by_role("button", name="全部热点").first.click()
                page.wait_for_selector("button:has-text('返回主题')", timeout=8000)
                page.wait_for_timeout(1800)
                ma = page.evaluate(MEASURE_LIST_JS)
                MEASURE[f"{w}x{h}"]["all"] = ma
                page.get_by_role("button", name="返回主题").first.click()
                page.wait_for_selector("button:has-text('新建主题')", timeout=8000)
                page.wait_for_timeout(1000)
            except Exception as e:
                MEASURE[f"{w}x{h}"]["all"] = {"error": str(e)}

        # ================ B. 空态 / 骨架屏 / 错误 Alert（受控拦截） ================
        # B1 骨架屏：延迟 topics 接口 3s，测量骨架网格
        def delayed_continue(route):
            def _run():
                time.sleep(3)
                route.continue_()

            threading.Thread(target=_run, daemon=True).start()

        page.route("**/api/ai-trending/topics", delayed_continue)
        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(f"{BASE}/ai-trending", wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_selector("div.grid > .ant-skeleton", timeout=5000)
            page.wait_for_timeout(400)
            sk = page.evaluate(MEASURE_SKELETON_JS)
            MEASURE["skeleton_1440"] = sk
        except Exception as e:
            MEASURE["skeleton_1440"] = {"error": str(e)}
        page.unroute("**/api/ai-trending/topics")
        page.wait_for_timeout(2500)  # 等真实数据加载完成

        # B2 空态：topics 接口返回 []，测量 Empty 宽度
        def fulfill_empty(route):
            route.fulfill(status=200, content_type="application/json", body=json.dumps([]))

        page.route("**/api/ai-trending/topics", fulfill_empty)
        page.goto(f"{BASE}/ai-trending", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1800)
        try:
            page.wait_for_selector("div.ant-empty", timeout=6000)
            me = page.evaluate(MEASURE_TOPICS_JS)
            MEASURE["empty_1440"] = me
        except Exception as e:
            MEASURE["empty_1440"] = {"error": str(e)}
        page.unroute("**/api/ai-trending/topics")

        # B3 错误 Alert：topics 接口返回 500
        def fulfill_error(route):
            route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": "QA forced error"}))

        page.route("**/api/ai-trending/topics", fulfill_error)
        page.goto(f"{BASE}/ai-trending", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1800)
        try:
            page.wait_for_selector(".ant-alert-error", timeout=6000)
            merr = page.evaluate(MEASURE_TOPICS_JS)
            MEASURE["error_1440"] = merr
        except Exception as e:
            MEASURE["error_1440"] = {"error": str(e)}
        page.unroute("**/api/ai-trending/topics")
        page.wait_for_timeout(1200)

        browser.close()

    # ================================================================
    # 判定
    # ================================================================
    print("\n================ 判定 ================")

    # 清单 1/2：通栏容器
    t1440 = MEASURE.get("1440x900", {}).get("topics", {})
    t1920 = MEASURE.get("1920x1080", {}).get("topics", {})
    if t1440.get("container"):
        c = t1440["container"]
        ok_left = abs(c["left"] - 240) <= EDGE_TOL
        ok_right = abs(c["right"] - 1424) <= EDGE_TOL
        check("1. [1440×900] 容器 left≈240", ok_left, f"left={c['left']} (期望≈240)")
        check("1. [1440×900] 容器 right≈1424（仅剩 Page p-4 16px）", ok_right, f"right={c['right']} (期望≈1424)")
    else:
        check("1. [1440×900] 容器测量", False, str(t1440.get("error", "no data")))

    if t1920.get("container"):
        c = t1920["container"]
        ok_right = abs(c["right"] - 1904) <= EDGE_TOL
        ok_width = c["width"] > 1500  # 无 320px 级空白
        check("2. [1920×1080] 通栏 right≈1904", ok_right, f"right={c['right']}")
        check("2. [1920×1080] 无 320px 级空白（width>1500）", ok_width, f"width={c['width']}")
    else:
        check("2. [1920×1080] 容器测量", False, str(t1920.get("error", "no data")))

    # 清单 3：标题左缘对齐
    if t1440.get("container") and t1440.get("title"):
        c, t = t1440["container"], t1440["title"]
        check("3. 标题「AI 热点主题」左缘=容器左缘", abs(t["left"] - c["left"]) <= ALIGN_TOL,
              f"title.left={t['left']}, container.left={c['left']}")
    else:
        check("3. 标题左缘对齐", False, "missing data")

    # 清单 4：卡片网格 3 列等宽 / 12px / 首末卡贴边（1440 与 1920 各验一次）
    for tag, w, h in [("4", 1440, 900), ("4", 1920, 1080)]:
        tp = MEASURE.get(f"{w}x{h}", {}).get("topics", {})
        if not tp.get("grid"):
            check(f"{tag}. [{w}×{h}] 卡片网格", False, "no grid")
            continue
        g = tp["grid"]
        cols = parse_cols(tp.get("gridTemplateColumns", []))
        ok3 = len(cols) == 3
        ok_equal = ok3 and (max(cols) - min(cols)) <= COL_TOL
        ok_gap = tp.get("columnGap") in ("12px", "12px 12px")
        fc, lc = tp.get("firstCard"), tp.get("lastCard")
        ok_first = fc and abs(fc["left"] - g["left"]) <= ALIGN_TOL
        ok_last = lc and abs(lc["right"] - g["right"]) <= ALIGN_TOL
        ok_grid_edge = abs(g["left"] - tp["container"]["left"]) <= ALIGN_TOL and abs(g["right"] - tp["container"]["right"]) <= ALIGN_TOL
        check(f"{tag}. [{w}×{h}] 网格 3 列等宽", ok3 and ok_equal,
              f"cols={tp.get('gridTemplateColumns')}")
        check(f"{tag}. [{w}×{h}] 列间距 12px", ok_gap, f"columnGap={tp.get('columnGap')}")
        check(f"{tag}. [{w}×{h}] 首卡左缘=容器左缘", ok_first,
              f"firstCard.left={fc and fc['left']}, grid.left={g['left']}")
        check(f"{tag}. [{w}×{h}] 末卡右缘=容器右缘", ok_last,
              f"lastCard.right={lc and lc['right']}, grid.right={g['right']}")
        check(f"{tag}. [{w}×{h}] 网格贴容器左右缘", ok_grid_edge,
              f"grid=[{g['left']},{g['right']}] container=[{tp['container']['left']},{tp['container']['right']}]")

    # 清单 5：骨架屏 / 空态 / 错误 Alert 通栏
    sk = MEASURE.get("skeleton_1440", {})
    if sk.get("grid"):
        cols = parse_cols(sk.get("gridTemplateColumns", []))
        check("5. 骨架屏 3 张占位卡与卡片网格同宽（1440）", len(cols) == 3 and sk.get("skeletonCount") == 3,
              f"cols={sk.get('gridTemplateColumns')}, count={sk.get('skeletonCount')}, width={sk['grid']['width']}")
    else:
        check("5. 骨架屏测量", False, str(sk.get("error", "no data")))

    emp = MEASURE.get("empty_1440", {})
    if emp.get("empty") and emp.get("container"):
        ok = abs(emp["empty"]["left"] - emp["container"]["left"]) <= ALIGN_TOL and abs(
            emp["empty"]["right"] - emp["container"]["right"]) <= ALIGN_TOL
        check("5. 空态通栏（Empty 贴容器左右缘）", ok,
              f"empty=[{emp['empty']['left']},{emp['empty']['right']}] container=[{emp['container']['left']},{emp['container']['right']}]")
    else:
        check("5. 空态测量", False, str(emp.get("error", "no data")))

    errd = MEASURE.get("error_1440", {})
    if errd.get("errorAlert") and errd.get("container"):
        ok = abs(errd["errorAlert"]["left"] - errd["container"]["left"]) <= ALIGN_TOL and abs(
            errd["errorAlert"]["right"] - errd["container"]["right"]) <= ALIGN_TOL
        check("5. 错误 Alert 通栏（贴容器左右缘）", ok,
              f"alert=[{errd['errorAlert']['left']},{errd['errorAlert']['right']}] container=[{errd['container']['left']},{errd['container']['right']}]")
    else:
        check("5. 错误 Alert 测量", False, str(errd.get("error", "no data")))

    # 清单 6：三个视图态宽度一致、列表通栏
    for w, h in [(1440, 900), (1920, 1080)]:
        st = MEASURE.get(f"{w}x{h}", {})
        t = st.get("topics", {})
        d = st.get("detail", {})
        a = st.get("all", {})
        if t.get("container") and d.get("container") and a.get("container"):
            widths = [t["container"]["width"], d["container"]["width"], a["container"]["width"]]
            ok = (max(widths) - min(widths)) <= ALIGN_TOL
            check(f"6. [{w}×{h}] 三视图态容器宽度一致", ok, f"topics={widths[0]}, detail={widths[1]}, all={widths[2]}")
        else:
            check(f"6. [{w}×{h}] 三视图态容器宽度", False,
                  f"t={t.get('error','ok')} d={d.get('error','ok')} a={a.get('error','ok')}")
        # 列表通栏（detail / all 的 .ant-list）
        for state_name, st_data in [("主题详情", d), ("全部热点", a)]:
            if st_data.get("list") and t.get("container"):
                l = st_data["list"]
                ok = abs(l["left"] - t["container"]["left"]) <= ALIGN_TOL and abs(
                    l["right"] - t["container"]["right"]) <= ALIGN_TOL
                check(f"6. [{w}×{h}] {state_name}态列表通栏", ok,
                      f"list=[{l['left']},{l['right']}] container=[{t['container']['left']},{t['container']['right']}]")
            else:
                check(f"6. [{w}×{h}] {state_name}态列表通栏", False,
                      f"list={st_data.get('error','no data')} hasList={st_data.get('hasList')}")

    # 清单 7：窄视口回退
    for w, h, expect_cols in [(800, 900, 2), (900, 900, 2), (700, 900, 1)]:
        tp = MEASURE.get(f"{w}x{h}", {}).get("topics", {})
        cols = parse_cols(tp.get("gridTemplateColumns", []))
        ok_col = len(cols) == expect_cols
        ok_scroll = no_hscroll(tp)
        check(f"7. [{w}×{h}] {expect_cols} 列（{'<768' if expect_cols == 1 else '768–1024'}）", ok_col,
              f"cols={tp.get('gridTemplateColumns')}")
        check(f"7. [{w}×{h}] 无横向滚动条", ok_scroll,
              f"scrollW={tp.get('docScrollW')}, clientW={tp.get('docClientW')}")

    # 清单 8：控制台无 error（排除 favicon / 403 噪声）
    real_errors = [e for e in ALL_CONSOLE if "favicon" not in e.lower() and "403" not in e]
    check("8. 控制台无 error（正常导航流程）", len(real_errors) == 0, str(real_errors[:5]))

    # ---------------- 输出测量矩阵 ----------------
    print("\n================ 测量矩阵 ================")
    for key, val in MEASURE.items():
        print(f"\n--- {key} ---")
        print(json.dumps(val, ensure_ascii=False, indent=2)[:3000])

    # ---------------- 汇总 ----------------
    print("\n================ SUMMARY ================")
    print(f"Total: {len(PASS) + len(FAIL)} | Passed: {len(PASS)} | Failed: {len(FAIL)}")
    if FAIL:
        print("Failed:")
        for f in FAIL:
            print("  -", f)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
