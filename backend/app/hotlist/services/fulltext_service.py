"""L2 全文抓取与缓存（Phase 6 §4.3）。

四条约束：
1. 先看 RSS 里有没有——crawl_service 抓取时已把 content:encoded 全文写入缓存，这里直接命中；
2. 尊重 robots.txt，禁止抓取的 status="skipped" 降级用摘要；
3. 付费墙识别：正文短于 200 字或含明显订阅提示词的标 skipped；
4. 超时 8 秒、失败不重试——15 条里失败两三条无所谓，不值得拖慢整个报告任务。
"""
from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Optional
from urllib.parse import urlsplit
import urllib.robotparser

from loguru import logger
import requests

from app.common.utils.text import strip_html
from app.core.database import SessionLocal
from app.hotlist.models import HotItem, HotItemContent

FULLTEXT_TIMEOUT = 8
MIN_BODY_CHARS = 200
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; WorkBench-Hotlist/1.0; +https://github.com)"
    ),
}
# 付费墙 / 订阅提示词：命中即降级（小写匹配）
PAYWALL_HINTS = (
    "subscribe to continue",
    "subscribe now",
    "please subscribe",
    "this content is for subscribers",
    "members only",
    "sign in to continue",
    "订阅后阅读",
    "付费解锁",
    "请订阅",
    "成为会员",
    "登录后阅读",
    "开通会员",
)

# 进程内 robots 缓存：host -> (can_fetch 判定结果缓存 | None)；None = 解析失败（放行）
_robots_cache: dict[str, Optional[bool]] = {}
_robots_lock = threading.Lock()


def _robots_allowed(url: str) -> bool:
    """robots.txt 检查（进程内缓存 host 级判定，每条 URL 只解析一次）。"""
    try:
        parts = urlsplit(url)
        host = parts.netloc.lower()
        if not host:
            return True
        with _robots_lock:
            if host in _robots_cache:
                return _robots_cache[host] is not False
        try:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{parts.scheme}://{host}/robots.txt")
            rp.read()
            allowed = (
                rp.can_fetch("WorkBench-Hotlist", url)
                or rp.can_fetch("*", url)
            )
        except Exception:  # noqa: BLE001  解析失败放行，不阻塞报告
            allowed = True
        with _robots_lock:
            _robots_cache[host] = allowed
        return allowed
    except Exception:  # noqa: BLE001
        return True


def _looks_paywalled(text: str) -> bool:
    """付费墙识别：明显订阅提示词命中即视为墙（不依赖长度判断）。"""
    low = (text or "").lower()[:2000]
    return any(hint in low for hint in PAYWALL_HINTS)


def _looks_empty(text: str) -> bool:
    """正文短于 MIN_BODY_CHARS 视为抓取失败/空页（可能被 JS 渲染或 404 页）。"""
    return len((text or "").strip()) < MIN_BODY_CHARS


def _fetch_page(url: str) -> str:
    """抓取页面正文：直接 strip_html 全文（报告场景要的是文字密度，不需要正文抽取器）。"""
    try:
        resp = requests.get(
            url, timeout=FULLTEXT_TIMEOUT, headers=DEFAULT_HEADERS
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError(f"抓取失败: {exc}") from exc
    return strip_html(resp.text)


def fetch_fulltext(item: HotItem) -> HotItemContent:
    """按需抓全文，结果写 hot_item_contents 缓存（同一条只抓一次）。

    自开自关 Session（供 topic_report_service 的 ThreadPoolExecutor 并发调用——
    SQLAlchemy Session 非线程安全，不能跨线程共享）。
    返回缓存行（可能 status=failed/skipped，调用方降级用摘要即可）。
    异常不外抛——调用方（主题报告的并发池）不能被单条失败打断。
    """
    db = SessionLocal()
    try:
        cached = db.get(HotItemContent, item.id)
        if cached is not None:
            return cached

        now = datetime.now(timezone.utc)
        row = HotItemContent(item_id=item.id, fetched_at=now)

        # 1. RSS 自带全文（crawl 时已写入）——但这里是兜底查，正常情况 crawl 已写入
        if not item.url:
            row.status = "skipped"
            row.error = "条目无 URL"
            db.add(row)
            db.commit()
            return row

        if not _robots_allowed(item.url):
            row.status = "skipped"
            row.error = "robots.txt 禁止抓取"
            db.add(row)
            db.commit()
            logger.info(f"全文抓取跳过（robots 禁止）: {item.url}")
            return row

        try:
            text = _fetch_page(item.url)
        except ValueError as exc:
            row.status = "failed"
            row.error = str(exc)
            row.char_count = 0
            db.add(row)
            db.commit()
            logger.info(f"全文抓取失败（{item.id}）: {exc}")
            return row

        if _looks_paywalled(text):
            row.status = "skipped"
            row.error = "疑似付费墙/订阅提示"
            db.add(row)
            db.commit()
            logger.info(f"全文抓取跳过（付费墙）: {item.url}")
            return row

        if _looks_empty(text):
            row.status = "failed"
            row.error = "正文过短（可能被 JS 渲染或已下线）"
            db.add(row)
            db.commit()
            logger.info(f"全文抓取跳过（正文过短）: {item.url}")
            return row

        row.content = text
        row.char_count = len(text)
        row.status = "success"
        db.add(row)
        db.commit()
        return row
    finally:
        db.close()
