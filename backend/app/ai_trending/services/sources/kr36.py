"""36氪源：官方 RSS（https://36kr.com/feed）为全站 feed，默认启用 AI 关键词过滤降噪。"""
from __future__ import annotations

import feedparser

from app.ai_trending.services.base import (
    AI_KEYWORDS,
    RawItem,
    TrendingSource,
    TrendingSourceError,
    paper_heat,
    parse_struct_time,
    strip_html,
)


class Kr36Source(TrendingSource):
    """36氪全站快讯，category=news，默认启用 AI 关键词过滤（噪声大）。"""

    source_id = "kr36"
    source_name = "36氪"
    category_type = "news"
    filter_keywords: list[str] = AI_KEYWORDS

    FEED_URL = "https://www.36kr.com/feed"  # 裸域 36kr.com 会命中反爬验证页，www 子域直接返回 RSS

    def fetch(self) -> list[RawItem]:
        content = self._http_get_bytes(self.FEED_URL)
        feed = feedparser.parse(content)
        if getattr(feed, "bozo", 0) and not feed.entries:
            raise TrendingSourceError("kr36 feed 解析失败（bozo）")
        items: list[RawItem] = []
        for entry in feed.entries:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            summary = strip_html(entry.get("description") or "")
            published_at = parse_struct_time(
                entry.get("published_parsed") or entry.get("updated_parsed")
            )
            heat = paper_heat(published_at)
            item = RawItem(
                source=self.source_id,
                title=title,
                url=link,
                summary=summary,
                category=self.category_type,
                tags=[],
                published_at=published_at,
                heat_score=heat,
                heat_meta={},
            )
            if self._keep(item):
                items.append(item)
        return items
