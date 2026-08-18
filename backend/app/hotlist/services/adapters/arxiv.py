"""arXiv adapter：官方 Atom feed（cs.AI OR cs.LG 按提交时间倒序）。

重写自旧 ai_trending services/sources/arxiv.py，改动：
  - 删除 paper_heat；rank 按 feed 返回顺序（已按提交时间倒序）enumerate；
  - 只保留 fetch（search 检索能力由 Phase 3 频率词规则取代）。
"""
from __future__ import annotations

import feedparser

from app.common.utils.text import parse_struct_time
from app.hotlist.services.adapters.base import (
    HotSourceAdapter,
    HotSourceAdapterError,
    RawEntry,
    register,
)

API_URL = (
    "https://export.arxiv.org/api/query?"
    "search_query=cat:cs.AI+OR+cat:cs.LG"
    "&sortBy=submittedDate&sortOrder=descending&max_results=50"
)


class ArxivAdapter(HotSourceAdapter):
    adapter_key = "arxiv"

    def fetch(self, params: dict) -> list[RawEntry]:
        content = self._request(API_URL, timeout=20).content
        feed = feedparser.parse(content)
        if getattr(feed, "bozo", 0) and not feed.entries:
            raise HotSourceAdapterError("arxiv feed 解析失败（bozo）")
        entries: list[RawEntry] = []
        for idx, entry in enumerate(feed.entries or [], 1):
            title = " ".join((entry.get("title") or "").split())
            # entry.id 形如 http://arxiv.org/abs/2401.12345v2（normalize_url 会去掉版本号）
            link = (entry.get("id") or entry.get("link") or "").strip()
            if not title or not link:
                continue
            summary = " ".join((entry.get("summary") or "").split())
            published_at = parse_struct_time(
                entry.get("published_parsed") or entry.get("updated_parsed")
            )
            entries.append(
                RawEntry(
                    rank=idx,
                    title=title,
                    url=link,
                    summary=summary,
                    published_at=published_at,
                )
            )
        return entries


register(ArxivAdapter())
