"""InfoQ 中国源：官方 RSS（https://www.infoq.cn/feed），AI 内容浓度高，默认不过滤。"""
from __future__ import annotations

import feedparser

from app.ai_trending.services.base import (
    RawItem,
    TrendingSource,
    TrendingSourceError,
    paper_heat,
    parse_struct_time,
    strip_html,
)


class InfoQSource(TrendingSource):
    """InfoQ 中文技术新闻，category=news（RSS 无热度指标，用时间衰减分）。"""

    source_id = "infoq"
    source_name = "InfoQ"
    category_type = "news"
    filter_keywords: list[str] | None = None  # P0 源、AI 内容浓度高，默认不过滤

    FEED_URL = "https://www.infoq.cn/feed"

    def fetch(self) -> list[RawItem]:
        content = self._http_get_bytes(self.FEED_URL)
        feed = feedparser.parse(content)
        if getattr(feed, "bozo", 0) and not feed.entries:
            raise TrendingSourceError("infoq feed 解析失败（bozo）")
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
