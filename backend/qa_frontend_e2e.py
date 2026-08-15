"""QA 前端 E2E 回归：AI 热点 → 主题跟踪模式（Playwright 无头）。

覆盖：
B1. 登录 + /ai-trending 主题列表态（新建主题按钮 / 全部热点入口 / 全局推送卡片已移除）
B2. 有主题：点主题 → 详情态（返回按钮 + 热点列表）；推送配置弹窗（channel 4 选项/频率/时间/开关/保存）
B3. 全部热点视图（来源 Tab/列表）正常
B4. 新建主题流程（弹窗填名称+关键词 → 提交 → 列表出现新主题）
B5. 控制台无 error
"""
from __future__ import annotations

import re
import sys
import time

import requests
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5666"
API = "http://127.0.0.1:8010"

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        console_errors: list[str] = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))

        # ---- 登录 ----
        page.goto(f"{BASE}/auth/login", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)
        try:
            page.fill('input[name="username"]', "admin")
            page.fill('input[name="password"]', "admin123")
        except Exception:
            # 兜底：按表单内输入框顺序填
            inputs = page.locator("form input")
            inputs.nth(0).fill("admin")
            inputs.nth(1).fill("admin123")
        page.keyboard.press("Enter")
        page.wait_for_timeout(3000)
        # 等待登录完成（URL 离开 login 或出现主布局）
        try:
            page.wait_for_url(lambda url: "/auth/login" not in url, timeout=15000)
        except Exception:
            pass
        cur = page.url
        check("B1 登录成功跳离 login 页", "/auth/login" not in cur, f"url={cur}")

        # 读取 token 备用（Vben 存于 localStorage 的 <app>-core-access key，不含 "token" 字样）
        token = None
        try:
            token = page.evaluate(
                "() => { const k = Object.keys(localStorage).find(x => /access/i.test(x) || /token/i.test(x)); "
                "return k ? localStorage.getItem(k) : null; }"
            )
        except Exception:
            pass
        check("B1 localStorage 存在 token", bool(token), f"token-prefix={str(token)[:20] if token else None}")

        # ---- 进入 /ai-trending ----
        page.goto(f"{BASE}/ai-trending", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2500)

        # B1: 列表态关键元素（实现文案为「AI 热点主题」）
        check("B1 页面含「AI 热点主题」标题", page.get_by_text("AI 热点主题").count() > 0)
        check("B1 有「新建主题」按钮", page.get_by_role("button", name="新建主题").count() > 0)
        check("B1 有「全部热点」入口", page.get_by_role("button", name="全部热点").count() > 0)
        # 全局推送卡片已移除：页面不应出现「定时推送」相关文案
        body_text = page.inner_text("body")
        check("B1 全局推送卡片已移除（无「定时推送」文案）", "定时推送" not in body_text and "企业微信 Webhook" not in body_text, body_text[:100])
        check("B1 无「推送配置卡片」残留", "每日推送" not in body_text)

        # 若列表无主题 → 先通过 API 创建（用 localStorage token）
        topic_cards = page.locator("text=立即抓取").count()
        if topic_cards == 0:
            print("    ... 页面无主题，先通过 API 创建主题 ...")
            token = token or ""
            headers = {"Authorization": f"Bearer {token}"}
            if not token:
                r = requests.post(f"{API}/api/auth/login", data={"username": "admin", "password": "admin123"})
                token = r.json()["access_token"]
                headers = {"Authorization": f"Bearer {token}"}
            r = requests.post(
                f"{API}/api/ai-trending/topics",
                json={"name": f"E2E主题-{int(time.time())}", "keywords": ["大模型", "AI Agent"], "interval_minutes": 60, "enabled": True},
                headers=headers, timeout=10,
            )
            check("B-API 预创建主题 200", r.status_code == 200, r.text[:120])
            tid = r.json().get("id") if r.status_code == 200 else None
            # 触发一次 run-now 让详情有数据
            if tid:
                requests.post(f"{API}/api/ai-trending/topics/{tid}/run-now", headers=headers, timeout=10)
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(2500)

        # B1: 主题卡片出现
        card_cnt = page.locator("text=立即抓取").count()
        check("B1 主题卡片出现（有立即抓取按钮）", card_cnt > 0, f"count={card_cnt}")

        # 点击主题卡片进入详情态（点击卡片第一个标题文本）
        first_topic_title = page.locator("div.cursor-pointer span.truncate").first
        check("B2 存在主题卡片标题", first_topic_title.count() > 0)
        if first_topic_title.count() > 0:
            first_topic_title.click()
            page.wait_for_timeout(2500)
            check("B2 详情态有「返回主题列表」按钮", page.get_by_role("button", name="返回主题列表").count() > 0)
            check("B2 详情态有「推送配置」按钮", page.get_by_role("button", name="推送配置").count() > 0)
            check("B2 详情态有「立即抓取」按钮", page.get_by_role("button", name="立即抓取").count() > 0)

            # 推送配置弹窗
            page.get_by_role("button", name="推送配置").first.click()
            page.wait_for_timeout(2000)
            modal = page.locator(".ant-modal-content")
            check("B2 推送配置弹窗出现", modal.count() > 0)
            if modal.count() > 0:
                # 注意：antd 两字按钮自动插空格「保 存」「取 消」→ 全部用正则匹配；Escape 会关闭 Modal 不能用来关下拉
                body2 = modal.first.inner_text()
                check("B2 弹窗含「开启主题推送」开关", "开启主题推送" in body2)
                save_btn = page.get_by_role("button", name=re.compile(r"保\s*存"))
                check("B2 弹窗有保存按钮", save_btn.count() > 0)
                # channel 下拉 4 选项
                channel_sel = modal.locator(".ant-select").first
                channel_sel.click()
                page.wait_for_timeout(800)
                opts = page.locator(".ant-select-item-option").all_inner_texts()
                check("B2 channel 下拉 4 选项", any("企业微信" in o for o in opts) and any("钉钉" in o for o in opts) and any("飞书" in o for o in opts) and any("邮件" in o for o in opts), str(opts))
                # 点击弹窗标题区关闭下拉（不用 Escape，避免关掉 Modal）
                page.mouse.click(700, 200)
                page.wait_for_timeout(500)
                body2b = modal.first.inner_text()
                check("B2 弹窗含推送频率/时间/仅保存提示", "推送频率" in body2b and "推送时间" in body2b and "仅保存配置" in body2b)
                # 关闭弹窗
                page.get_by_role("button", name=re.compile(r"取\s*消")).first.click()
                page.wait_for_timeout(1000)

            # 返回列表
            page.get_by_role("button", name="返回主题列表").click()
            page.wait_for_timeout(1500)
            check("B2 返回后回到列表态（新建主题按钮可见）", page.get_by_role("button", name="新建主题").count() > 0)

        # B3: 全部热点视图
        page.get_by_role("button", name="全部热点").first.click()
        page.wait_for_timeout(2500)
        check("B3 全部热点视图标题", page.get_by_text("全部热点").count() > 0)
        check("B3 来源 Tab 存在（HN/GitHub/arXiv/HF）", page.get_by_text("HN", exact=True).count() > 0 and page.get_by_text("GitHub", exact=True).count() > 0 and page.get_by_text("arXiv", exact=True).count() > 0 and page.get_by_text("HF", exact=True).count() > 0)
        check("B3 热点列表有数据", page.locator(".ant-list-item").count() > 0, f"items={page.locator('.ant-list-item').count()}")
        # 返回
        page.get_by_role("button", name="返回主题").click()
        page.wait_for_timeout(1500)

        # B4: 新建主题流程
        page.get_by_role("button", name="新建主题").first.click()
        page.wait_for_timeout(1200)
        modal = page.locator(".ant-modal-content").last
        check("B4 新建主题弹窗出现", modal.count() > 0)
        if modal.count() > 0:
            topic_name = f"E2E新主题-{int(time.time())}"
            modal.locator("input").first.fill(topic_name)
            # 关键词 tags Select：输入后回车
            kw_input = modal.locator(".ant-select-selection-search-input").first
            kw_input.fill("多模态")
            kw_input.press("Enter")
            page.wait_for_timeout(600)
            kw_input.fill("RAG")
            kw_input.press("Enter")
            page.wait_for_timeout(600)
            modal.get_by_role("button", name=re.compile(r"保\s*存")).click()
            page.wait_for_timeout(2500)
            # 成功后回到列表态并出现新主题
            body3 = page.inner_text("body")
            check("B4 新建主题提交成功出现新卡片", topic_name in body3, f"found={topic_name in body3}")

        # B5: 控制台错误
        real_errors = [e for e in console_errors if "favicon" not in e.lower() and "403" not in e]
        check("B5 控制台无 error", len(real_errors) == 0, str(real_errors[:5]))

        browser.close()

    print("\n================ SUMMARY ================")
    print(f"Total: {len(PASS) + len(FAIL)} | Passed: {len(PASS)} | Failed: {len(FAIL)}")
    if FAIL:
        print("Failed:")
        for f in FAIL:
            print("  -", f)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
