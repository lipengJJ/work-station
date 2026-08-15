"""arXiv 源：官方 Atom feed（cs.AI OR cs.LG，按提交时间倒序取 50 条）。"""
from __future__ import annotations

import feedparser

from app.ai_trending.services.base import (
    RawItem,
    TrendingSource,
    TrendingSourceError,
    paper_heat,
    parse_struct_time,
)


class ArxivSource(TrendingSource):
    """arXiv 人工智能/机器学习最新论文，category=paper（无热度指标，用时间衰减分）。"""

    source_id = "arxiv"
    source_name = "arXiv"
    category_type = "paper"
    filter_keywords: list[str] | None = None

    API_URL = (
        "https://export.arxiv.org/api/query?"
        "search_query=cat:cs.AI+OR+cat:cs.LG"
        "&sortBy=submittedDate&sortOrder=descending&max_results=50"
    )

    def fetch(self) -> list[RawItem]:
        content = self._http_get_bytes(self.API_URL)
        feed = feedparser.parse(content)
        if getattr(feed, "bozo", 0) and not feed.entries:
            raise TrendingSourceError("arxiv feed 解析失败（bozo）")
        items: list[RawItem] = []
        for entry in feed.entries:
            title = " ".join((entry.get("title") or "").split())
            # entry.id 形如 http://arxiv.org/abs/2401.12345v2（url_hash 会去掉版本号）
            link = (entry.get("id") or entry.get("link") or "").strip()
            if not title or not link:
                continue
            summary = " ".join((entry.get("summary") or "").split())
            published_at = parse_struct_time(
                entry.get("published_parsed") or entry.get("updated_parsed")
            )
            tags = [
                t.get("term", "")
                for t in entry.get("tags") or []
                if t.get("term")
            ]
            arxiv_id = link.rstrip("/").rsplit("/", 1)[-1]
            heat = paper_heat(published_at)
            items.append(
                RawItem(
                    source=self.source_id,
                    title=title,
                    url=link,
                    summary=summary,
                    category=self.category_type,
                    tags=tags,
                    published_at=published_at,
                    heat_score=heat,
                    heat_meta={"arxiv_id": arxiv_id},
                )
            )
        return items
