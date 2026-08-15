"""诊断：视口 resize 700->1440 后布局状态 + antd Empty 默认 margin。"""
import json
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5666"

MEASURE = r"""
() => {
  const box = el => { if(!el) return null; const r=el.getBoundingClientRect();
    return {left:Math.round(r.left*10)/10, width:Math.round(r.width*10)/10, right:Math.round(r.right*10)/10}; };
  const container = document.querySelector('div.flex.w-full.flex-col.gap-4');
  const empty = document.querySelector('div.ant-empty');
  const emptyCs = empty ? getComputedStyle(empty) : null;
  const aside = document.querySelector('aside');
  return {
    container: box(container),
    empty: box(empty),
    emptyMargin: emptyCs ? { left: emptyCs.marginLeft, right: emptyCs.marginRight, paddingLeft: emptyCs.paddingLeft } : null,
    aside: aside ? box(aside) : null,
  };
}
"""


def measure(page, tag):
    try:
        m = page.evaluate(MEASURE)
        print(tag, json.dumps(m))
    except Exception as e:
        print(tag, "ERR", e)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()

    # 登录
    page.goto(f"{BASE}/auth/login", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1200)
    try:
        page.fill('input[name="username"]', "admin")
        page.fill('input[name="password"]', "admin123")
    except Exception:
        inputs = page.locator("form input")
        inputs.nth(0).fill("admin")
        inputs.nth(1).fill("admin123")
    page.keyboard.press("Enter")
    page.wait_for_timeout(3000)
    page.wait_for_url(lambda u: "/auth/login" not in u, timeout=15000)
    print("logged in:", page.url)

    # 场景 1：直接 1440 加载
    page.goto(f"{BASE}/ai-trending", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2000)
    measure(page, "S1 直接1440加载: ")

    # 场景 2：resize 到 700，加载
    page.set_viewport_size({"width": 700, "height": 900})
    page.goto(f"{BASE}/ai-trending", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)
    measure(page, "S2 700加载: ")

    # 场景 3：resize 回 1440（不 reload）→ 看是否恢复 240
    page.set_viewport_size({"width": 1440, "height": 900})
    page.wait_for_timeout(1500)
    measure(page, "S3 700->1440 不reload: ")

    # 场景 4：resize 回 1440 并 reload → 看是否恢复 240
    page.goto(f"{BASE}/ai-trending", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)
    measure(page, "S4 700->1440 reload: ")

    # 场景 5：新 page（干净 1440 上下文）→ 骨架屏/空态/错误 Alert
    page2 = ctx.new_page()  # 继承 ctx 默认 1440
    page2.goto(f"{BASE}/ai-trending", wait_until="networkidle", timeout=30000)
    page2.wait_for_timeout(2000)
    measure(page2, "S5 新page(1440): ")

    browser.close()
