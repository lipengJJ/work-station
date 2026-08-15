"""
小红书页面级爬取（Playwright）：评论获取从"Web API 直连"重构为"浏览器渲染 DOM 爬取"。

背景：小红书 PC 评论接口（/api/sns/web/v2/comment/page 等）风控极敏感，频繁请求
容易触发滑块/限流。改用无头 Chromium 打开笔记页、滚动加载评论区、解析 .comment-item
DOM 的方式（参考 wangjushi/XHS-Crawler 的 scrape_comments_by_url），请求形态与真人
浏览一致，风控面显著更小。

设计约定：
- 进程级懒启动：全局共享一个 browser，第一个调用才 launch；每次 crawl 用独立
  context（cookie 隔离），抓完即关。退出通过 atexit 钩子清理浏览器进程。
- playwright 在方法内懒 import：即使环境没装 playwright，本模块仍可被正常 import
  （spider 模块的依赖链不会因此断裂），真正调用爬取时才报出明确错误。
- 输出结构：与 spider._flatten_comments / handle_comment_info 兼容的原始 dict 列表
  （含可选 sub_comments 嵌套，父评论 id 已打好）。DOM 拿不到的字段给空串/空列表兜底。
- 异常复用 xhs_errors 体系：页面打不开/超时 → XhsNetworkError；跳转登录页/登录引导
  → XhsAuthError；笔记不存在/已删除 → XhsNotFoundError。

注意：本模块依赖 Playwright + chromium（backend/requirements.txt 已加入 playwright，
部署时需执行 `playwright install chromium`，Dockerfile 需相应补充系统依赖）。
"""

from __future__ import annotations

import atexit
import hashlib
import random
import re
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from loguru import logger

from ..xhs_errors import XhsAuthError, XhsNetworkError, XhsNotFoundError

# ------------------------------------------------------------ 滚动/节流参数 ----

# 每轮滚动后的等待（秒），加随机抖动让滚动节奏更像真人，避免被风控识别成脚本
SCROLL_PAUSE = 1.2
# 提取一次评论后触发 on_batch 流式回调的最小累计条数（一级+二级）
BATCH_SIZE = 30
# 连续多少轮没有新增评论即认为已滚到底（评论区有"加载中"占位时可能出现空轮）
IDLE_STOP_ROUNDS = 4

# 点击"展开更多回复"类按钮的选择器集合（不同版本页面 class 略有差异，逐个尝试）
_EXPAND_SELECTORS = (
    ".unfold-comment",
    ".sub-comment-more",
    ".expand-comment",
    ".more-comments",
    ".comment-more",
)

# 登录失效的强特征：跳转到这些 URL 说明登录态已失效
_AUTH_URL_MARKERS = ("login", "passport")
# 页面出现这些文案/选择器说明需要登录（且没有评论区容器时判定登录失效）
_AUTH_BODY_MARKERS = ("登录后查看", "扫码登录", "手机号登录")
_AUTH_SELECTORS = (".login-container", ".login-modal", ".xhs-login-dialog", ".xhs-login")
# 笔记不存在/已删除文案
_NOT_FOUND_MARKERS = ("笔记不存在", "内容已删除", "该笔记已删除", "页面不存在")

# 兜底 UA：新版 Playwright headless 已能通过绝大多数 UA 检测，这里再显式给一个桌面 UA
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ------------------------------------------------------------ 进程级浏览器 ----

_browser_lock = threading.Lock()
_playwright = None
_browser = None


def _import_playwright():
    """懒导入 playwright，返回 sync_playwright 启动后的对象。未安装时给出可操作提示。"""
    global _playwright
    if _playwright is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RuntimeError(
                "缺少 playwright 依赖：请先执行 `pip install playwright && "
                "python -m playwright install chromium`（评论页面级爬取需要）"
            ) from e
        _playwright = sync_playwright().start()
    return _playwright


def _ensure_browser():
    """进程级懒启动 headless chromium（单例）。线程安全，可被多个 crawl 串行复用。"""
    global _browser
    with _browser_lock:
        if _browser is not None and _browser.is_connected():
            return _browser
        pw = _import_playwright()
        try:
            _browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
        except Exception as e:
            raise RuntimeError(
                f"启动 Chromium 失败（{e}）。请确认已执行 `python -m playwright install chromium`"
            ) from e
        return _browser


def shutdown_crawler() -> None:
    """关闭全局浏览器与 playwright 进程（进程退出时由 atexit 兜底调用）。"""
    global _playwright, _browser
    with _browser_lock:
        if _browser is not None:
            try:
                _browser.close()
            except Exception:
                pass
        if _playwright is not None:
            try:
                _playwright.stop()
            except Exception:
                pass
        _browser = None
        _playwright = None


@atexit.register
def _atexit_shutdown() -> None:
    shutdown_crawler()


# ------------------------------------------------------------ 时间/字段解析 ----

# 绝对时间解析格式（DOM 里 title 属性常见）
_TIME_PATTERNS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日")


def parse_comment_time_to_ms(text: str) -> int:
    """
    把评论时间文本转成毫秒时间戳（handle_comment_info 需要毫秒级 create_time）。
    支持"刚刚/x分钟前/x小时前/昨天/x天前/x个月前/x年前"以及绝对时间串；
    解析失败兜底返回当前时间戳——宁可比真实时间略晚，也不能因时间字段非法把
    整条评论丢进 _flatten_comments 的异常跳过分支。
    """
    text = (text or "").strip()
    now = time.time()
    if not text or "刚刚" in text:
        return int(now * 1000)
    m = re.search(r"(\d+)\s*分钟前", text)
    if m:
        return int((now - int(m.group(1)) * 60) * 1000)
    m = re.search(r"(\d+)\s*小时前", text)
    if m:
        return int((now - int(m.group(1)) * 3600) * 1000)
    if "昨天" in text:
        return int((now - 86400) * 1000)
    m = re.search(r"(\d+)\s*天前", text)
    if m:
        return int((now - int(m.group(1)) * 86400) * 1000)
    m = re.search(r"(\d+)\s*个月前", text)
    if m:
        return int((now - int(m.group(1)) * 30 * 86400) * 1000)
    m = re.search(r"(\d+)\s*年前", text)
    if m:
        return int((now - int(m.group(1)) * 365 * 86400) * 1000)
    for fmt in _TIME_PATTERNS:
        try:
            dt = datetime.strptime(text, fmt)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    logger.debug(f"评论时间无法解析，兜底为当前时间: {text!r}")
    return int(now * 1000)


def _fallback_comment_id(comment: dict) -> str:
    """DOM 拿不到评论 id 时的稳定兜底：user_id+content+昵称 的 md5（同一条评论每次 hash 一致，可去重）。"""
    user_id = (comment.get("user_info") or {}).get("user_id") or ""
    raw = f"{user_id}|{comment.get('content', '')}"
    return "dom_" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:20]


def _extract_note_id(note_url: str) -> str:
    path = note_url.split("?", 1)[0].rstrip("/")
    return path.rsplit("/", 1)[-1] if "/" in path else path


def _to_playwright_proxy(proxies: Optional[dict]) -> Optional[dict]:
    """把 requests 风格代理（{"http": ..., "https": ...}）转成 Playwright context proxy。"""
    if not proxies:
        return None
    server = proxies.get("https") or proxies.get("http")
    if not server:
        return None
    return {"server": server}


def _parse_cookies_str(cookies_str: str) -> list:
    """把 "k1=v1; k2=v2" cookie 字符串解析成 Playwright 可注入的 cookie 列表。"""
    cookies = []
    for part in (cookies_str or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or not value:
            continue
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": ".xiaohongshu.com",
                "path": "/",
            }
        )
    return cookies


# ------------------------------------------------------------ DOM 提取（JS） ----

# 一次性在页面里提取全部一级评论（含其子回复）。返回字段与 handle_comment_info 兼容
# （id / user_info.user_id / user_info.nickname / user_info.image / content /
#  show_tags / like_count / create_time / ip_location / pictures / sub_comments）。
_EXTRACT_COMMENTS_JS = r"""
() => {
  const clean = (s) => (s == null ? '' : String(s)).replace(/\s+/g, ' ').trim();
  const pickAttr = (el, names) => {
    for (const n of names) {
      const v = el.getAttribute(n);
      if (v && v.trim()) return v.trim();
    }
    return '';
  };
  const parseCount = (text) => {
    const s = clean(text).replace(/,/g, '');
    const m = s.match(/([\d.]+)\s*[万亿]/);
    if (m) {
      const n = parseFloat(m[1]);
      return s.includes('万') ? Math.round(n * 10000) : Math.round(n * 100000000);
    }
    const d = s.match(/(\d+)/);
    return d ? parseInt(d[1], 10) : 0;
  };
  const pickTimeText = (el) => {
    const titled = el.querySelector('.date span[title]');
    if (titled) {
      const t = (titled.getAttribute('title') || '').trim();
      if (t) return t;
    }
    const nodes = el.querySelectorAll('.date span');
    for (const n of nodes) {
      if (n.classList && n.classList.contains('location')) continue;
      const t = clean(n.textContent);
      if (t) return t;
    }
    return '';
  };
  const pickLocation = (el) => {
    const n = el.querySelector('.date .location, .location');
    return n ? clean(n.textContent).replace(/^来自/, '') : '';
  };
  const parseOne = (el) => {
    const link = el.querySelector('a.name, .name a');
    let user_id = '', nickname = '';
    if (link) {
      nickname = clean(link.textContent);
      const href = link.getAttribute('href') || '';
      const m = href.match(/user\/profile\/([^?/#]+)/);
      if (m) user_id = m[1];
    }
    const avatarEl = el.querySelector('.avatar img');
    const avatar = avatarEl
      ? (avatarEl.getAttribute('src') || avatarEl.getAttribute('data-src') || '')
      : '';
    const contentEl = el.querySelector('.content');
    const content = contentEl ? clean(contentEl.textContent) : '';
    const likeEl = el.querySelector('.like-wrapper .count, .like .count');
    const likeCount = likeEl ? parseCount(likeEl.textContent) : 0;
    const comment_id = pickAttr(el, ['data-comment-id', 'data-id', 'comment-id']);
    const tags = [];
    el.querySelectorAll('.tag').forEach((t) => {
      const x = clean(t.textContent);
      if (x) tags.push(x);
    });
    const pictures = [];
    el.querySelectorAll('.comment-images img, .images img, .img-box img').forEach((im) => {
      const s = im.getAttribute('src') || im.getAttribute('data-src') || '';
      if (s && s.startsWith('http')) pictures.push(s);
    });
    return {
      id: comment_id,
      user_info: { user_id: user_id, nickname: nickname, image: avatar },
      content: content,
      show_tags: tags,
      like_count: likeCount,
      create_time: pickTimeText(el),
      ip_location: pickLocation(el),
      pictures: pictures,
      sub_comments: [],
    };
  };
  const result = [];
  const allItems = document.querySelectorAll('.comment-item');
  for (const el of allItems) {
    // 只处理顶层一级评论（其内部嵌套的是子回复）
    let isTop = true;
    let p = el.parentElement;
    while (p) {
      if (p.classList && p.classList.contains('comment-item')) { isTop = false; break; }
      p = p.parentElement;
    }
    if (!isTop) continue;
    const item = parseOne(el);
    // 子回复：一级评论内部嵌套的 .comment-item / .sub-comment-item（最近祖先就是 el）。
    // 注意 closest() 会匹配元素自身，需从父元素起跳，否则子回复会匹配到自己。
    for (const subEl of allItems) {
      if (subEl === el) continue;
      if (subEl.parentElement.closest('.comment-item') === el) {
        item.sub_comments.push(parseOne(subEl));
      }
    }
    result.push(item);
  }
  return result;
}
"""


# ------------------------------------------------------------ 爬取器 ----

class XhsPageCrawler:
    """小红书页面级爬取器（Playwright headless Chromium）。"""

    def __init__(self) -> None:
        # 进程级共享浏览器，crawl 各自建独立 context（cookie 隔离）
        self._browser = None

    def close(self) -> None:
        """关闭全局浏览器/playwright（进程退出时 atexit 也会兜底调用）。"""
        shutdown_crawler()

    # ------------------------------------------------------------ 基础设施 ----

    @staticmethod
    def _apply_anti_detection(page) -> None:
        """注入反自动化检测脚本（webdriver 特征抹除 + 浏览器指纹伪造）。"""
        page.add_init_script(
            r"""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.navigator.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'] });
            Object.defineProperty(navigator, 'plugins', {
              get: () => [1, 2, 3, 4, 5],
            });
            Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
            const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
            if (originalQuery) {
              window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications'
                  ? Promise.resolve({ state: Notification.permission })
                  : originalQuery(parameters)
              );
            }
            """
        )

    @staticmethod
    def _inject_cookies(context, cookies_str: str) -> None:
        cookies = _parse_cookies_str(cookies_str)
        if not cookies:
            logger.warning("cookie 字符串为空或无法解析，页面可能处于未登录态")
            return
        try:
            context.add_cookies(cookies)
        except Exception:
            # 个别 cookie 值含非法字符时整批失败，退化为只注入基础域 cookie（去点重试）
            try:
                fixed = [
                    {**c, "domain": "www.xiaohongshu.com"}
                    for c in cookies
                ]
                context.add_cookies(fixed)
            except Exception as e:
                logger.warning(f"注入 cookie 失败（{e}），继续以无 cookie 方式打开页面")

    @staticmethod
    def _check_auth_state(page) -> None:
        """检测登录态失效：跳转登录页 / 整页登录引导且无评论区 → XhsAuthError。"""
        try:
            url = page.url or ""
        except Exception:
            url = ""
        if any(m in url.lower() for m in _AUTH_URL_MARKERS):
            raise XhsAuthError("检测到跳转登录页，登录态可能已失效")
        try:
            has_scroller = page.locator(".note-scroller").count() > 0
        except Exception:
            has_scroller = False
        if has_scroller:
            return
        try:
            has_auth_ui = any(page.locator(sel).count() > 0 for sel in _AUTH_SELECTORS)
        except Exception:
            has_auth_ui = False
        if has_auth_ui:
            raise XhsAuthError("页面出现登录引导，登录态可能已失效")
        try:
            body_text = page.locator("body").inner_text(timeout=2000) or ""
        except Exception:
            body_text = ""
        if any(m in body_text for m in _AUTH_BODY_MARKERS):
            raise XhsAuthError("页面需要登录后查看评论，登录态可能已失效")

    @staticmethod
    def _check_not_found(page) -> None:
        """笔记不存在/已删除 → XhsNotFoundError。"""
        try:
            body_text = page.locator("body").inner_text(timeout=2000) or ""
        except Exception:
            body_text = ""
        if any(m in body_text for m in _NOT_FOUND_MARKERS):
            raise XhsNotFoundError("笔记不存在或已删除")

    @staticmethod
    def _is_end_of_comments(page) -> bool:
        try:
            if page.locator(".end-container").count() or page.locator(".no-comments").count():
                return True
        except Exception:
            return False
        return False

    @staticmethod
    def _click_expand_buttons(page) -> int:
        """点击所有"展开更多回复"按钮（新加载出的子回复），返回点击次数。"""
        clicked = 0
        for sel in _EXPAND_SELECTORS:
            try:
                loc = page.locator(sel)
                count = loc.count()
            except Exception:
                continue
            for i in range(min(count, 5)):
                try:
                    loc.nth(i).click(timeout=1000)
                    clicked += 1
                except Exception:
                    pass
        if clicked:
            time.sleep(0.8 + random.uniform(0, 0.5))
        return clicked

    def _extract_comments(self, page) -> list:
        """执行 JS 提取全部评论原始结构，并把 create_time 转成毫秒时间戳。"""
        try:
            raw = page.evaluate(_EXTRACT_COMMENTS_JS)
        except Exception as e:
            logger.warning(f"页面评论 DOM 提取失败: {e}")
            return []
        if not isinstance(raw, list):
            return []
        for item in raw:
            if not isinstance(item, dict):
                continue
            item["create_time"] = parse_comment_time_to_ms(item.get("create_time"))
            for sub in item.get("sub_comments") or []:
                if isinstance(sub, dict):
                    sub["create_time"] = parse_comment_time_to_ms(sub.get("create_time"))
        return raw

    @staticmethod
    def _merge_comments(raw: list, seen_ids: set, comment_map: dict) -> tuple:
        """
        与已抓评论合并去重。

        返回 (new_items, fresh_subs)：
        - new_items: 本批新增的顶层评论（含其本轮新增的子回复）
        - fresh_subs: 已见过的一级评论本轮新加载出的子回复（独立返回给调用方进入
          流式回调，避免"后到子评论"漏发 on_batch 导致 comment_store 落库缺失）

        - 一级评论 id 用 DOM id，取不到用 fallback hash；
        - 一级评论已见过时，其子回复仍逐条去重，新增子回复合并进已有 item 的
          sub_comments（同一父评论的评论树保持完整）；
        - 子回复打上 parent_comment_id，spider 层 _flatten_comments 会原样保留。
        """
        new_items: list = []
        fresh_subs_total: list = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            cid = item.get("id") or _fallback_comment_id(item)
            item["id"] = cid
            is_new_top = cid not in seen_ids
            item_fresh_subs = []
            for sub in item.get("sub_comments") or []:
                if not isinstance(sub, dict):
                    continue
                sid = sub.get("id") or _fallback_comment_id(sub)
                sub["id"] = sid
                sub["parent_comment_id"] = cid
                if sid in seen_ids:
                    continue
                seen_ids.add(sid)
                item_fresh_subs.append(sub)
            if is_new_top:
                seen_ids.add(cid)
                item["sub_comments"] = item_fresh_subs
                comment_map[cid] = item
                new_items.append(item)
            elif item_fresh_subs:
                existing = comment_map.get(cid)
                if existing is not None:
                    existing.setdefault("sub_comments", []).extend(item_fresh_subs)
                else:
                    new_items.extend(item_fresh_subs)
                fresh_subs_total.extend(item_fresh_subs)
        return new_items, fresh_subs_total

    @staticmethod
    def _emit_batch(on_batch: Optional[Callable], note_id: str, batch: list) -> None:
        """流式回调（与 API 路线 on_page 语义一致：回调失败只告警，不影响主流程）。"""
        if on_batch is None or not batch:
            return
        try:
            on_batch(note_id, batch)
        except Exception as e:
            logger.warning(f"评论流式回调失败（note={note_id}），跳过该批: {e}")

    # ------------------------------------------------------------ 主入口 ----

    def crawl_note_comments(
        self,
        note_url: str,
        cookies_str: str,
        on_batch: Optional[Callable[[str, list], None]] = None,
        max_scroll_rounds: int = 60,
        max_comments: Optional[int] = None,
        proxies: Optional[dict] = None,
        scroll_pause: Optional[float] = None,
    ) -> list:
        """
        打开笔记页滚动加载全部评论并解析 DOM，返回与 handle_comment_info 兼容的原始 dict 列表。

        :param note_url: 笔记 URL（建议带 xsec_token）
        :param cookies_str: 已登录态 cookie 字符串（token_store.get_cookies_str 直接喂进来）
        :param on_batch: 可选回调 on_batch(note_id, 本批原始评论 dict 列表)，边滚动边触发（流式落库）
        :param max_scroll_rounds: 滚动轮次上限，达到后强制结束返回已抓到的（不抛错）
        :param max_comments: 最多保留的一级评论数量，达到后停止滚动（None 不限制）
        :param proxies: requests 风格代理 dict，可空
        :param scroll_pause: 每轮滚动后的最小等待秒数（额外叠加随机抖动），用于限速，
                             None 时用默认 SCROLL_PAUSE
        :return: 原始结构评论列表（每个 dict 含 id/user_info/content/show_tags/like_count/
                 create_time(毫秒)/ip_location/pictures/sub_comments[可选]/parent_comment_id[子回复]）
        :raises XhsNetworkError: 页面打不开/超时/评论区容器未加载
        :raises XhsAuthError: 登录态失效（跳转登录页/整页登录引导）
        :raises XhsNotFoundError: 笔记不存在/已删除
        """
        note_id = _extract_note_id(note_url)
        logger.info(f"页面爬取评论开始 note={note_id} url={note_url[:120]}")
        pause = SCROLL_PAUSE if scroll_pause is None else float(scroll_pause)

        browser = _ensure_browser()
        context = None
        page = None
        try:
            proxy = _to_playwright_proxy(proxies)
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=_DEFAULT_USER_AGENT,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                proxy=proxy,
            )
            page = context.new_page()
            self._apply_anti_detection(page)
            self._inject_cookies(context, cookies_str)

            # 打开笔记页
            try:
                page.goto(note_url, wait_until="domcontentloaded", timeout=20000)
            except Exception as e:
                # 打开失败先排除"跳登录页"和"笔记不存在"，再归类为网络错误
                try:
                    self._check_auth_state(page)
                except XhsAuthError:
                    raise
                try:
                    self._check_not_found(page)
                except XhsNotFoundError:
                    raise
                raise XhsNetworkError(f"页面打开失败/超时: {e}") from e

            self._check_auth_state(page)
            self._check_not_found(page)

            # 等评论区滚动容器出现
            try:
                page.wait_for_selector(".note-scroller", timeout=15000)
            except Exception as e:
                self._check_auth_state(page)
                self._check_not_found(page)
                raise XhsNetworkError(f"评论区容器未加载（页面结构可能已变化）: {e}") from e

            comments: list = []
            seen_ids: set = set()
            comment_map: dict = {}
            batch_buffer: list = []
            idle_rounds = 0

            for _round in range(max_scroll_rounds):
                # 展开子回复（每轮可能加载出新的"展开更多回复"按钮）
                self._click_expand_buttons(page)
                self._check_auth_state(page)

                # 先提取当前已渲染的评论再判断结束条件——评论区若已全部加载完
                # （.end-container 已在首屏），也要先把已渲染的评论提取走
                raw = self._extract_comments(page)
                new_items, fresh_subs = self._merge_comments(raw, seen_ids, comment_map)
                # 有新增内容（新一级评论或后到子评论）都算"有进展"，不累计 idle；
                # 新增子评论也要进流式缓冲，保证 on_batch 不遗漏（comment_store 落库完整）
                if not new_items and not fresh_subs:
                    idle_rounds += 1
                    if idle_rounds >= IDLE_STOP_ROUNDS:
                        logger.info(f"note={note_id} 连续 {idle_rounds} 轮无新评论，判定已滚动到底")
                        break
                else:
                    idle_rounds = 0
                    if new_items:
                        comments.extend(new_items)
                    batch_buffer.extend(new_items + fresh_subs)
                    logger.debug(
                        f"note={note_id} 第 {_round + 1} 轮新增一级 {len(new_items)} 条、子回复 {len(fresh_subs)} 条，"
                        f"累计 {len(comments)} 条一级"
                    )

                # 流式落库：攒够一批就触发
                if len(batch_buffer) >= BATCH_SIZE:
                    self._emit_batch(on_batch, note_id, batch_buffer)
                    batch_buffer = []

                # 一级评论数量达到上限即停（与 API 路线的 max_comments 语义一致，达到后截断）
                if max_comments is not None and len(comments) >= max_comments:
                    comments = comments[:max_comments]
                    logger.info(f"note={note_id} 一级评论达到上限 {max_comments}，提前结束")
                    break

                if self._is_end_of_comments(page):
                    break

                # 滚动到底部触发懒加载
                try:
                    page.evaluate(
                        "document.querySelector('.note-scroller')"
                        ".scrollTo(0, document.querySelector('.note-scroller').scrollHeight)"
                    )
                except Exception:
                    pass
                time.sleep(pause + random.uniform(0, 1.5))
            else:
                logger.warning(
                    f"note={note_id} 滚动超过 {max_scroll_rounds} 轮强制结束，已抓取 {len(comments)} 条"
                )

            if batch_buffer:
                self._emit_batch(on_batch, note_id, batch_buffer)
            logger.info(f"页面爬取评论结束 note={note_id} 共 {len(comments)} 条")
            return comments
        finally:
            # context 每次 crawl 独立创建，抓完即关；browser 进程级复用由 shutdown_crawler 统一清理
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
