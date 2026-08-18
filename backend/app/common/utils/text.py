"""文本 / 时间解析通用工具。

原先住在 app/ai_trending/services/base.py，ai_trending 下线时提到这里。
"""
from __future__ import annotations

import html as html_lib
import re
from calendar import timegm
from datetime import datetime, timezone
from time import struct_time

_ISO_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def parse_datetime(value: str | None) -> datetime | None:
    """把 API / feed 的 ISO 8601 字符串解析成 aware UTC datetime；解析不了返回 None。"""
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    for fmt in _ISO_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def parse_struct_time(st: struct_time | None) -> datetime | None:
    """feedparser 的 published_parsed / updated_parsed → aware UTC datetime。"""
    if not st:
        return None
    try:
        return datetime.fromtimestamp(timegm(st), tz=timezone.utc)
    except (OverflowError, OSError, ValueError, TypeError):
        return None


def strip_html(text: str) -> str:
    """去掉 HTML 标签 + 反转义实体，折叠空白，返回纯文本。"""
    if not text:
        return ""
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = html_lib.unescape(plain)
    return " ".join(plain.split())


def truncate(text: str, limit: int, suffix: str = "…") -> str:
    """按字符数截断（超出才加后缀）。落库前控制 summary 长度用。"""
    text = text or ""
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + suffix


def hours_since(dt: datetime | None, now: datetime | None = None) -> float:
    """距 dt 的小时数；dt 缺失返回 0，负值钳到 0。naive 时间按 UTC 处理。"""
    if dt is None:
        return 0.0
    now = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 3600.0)
