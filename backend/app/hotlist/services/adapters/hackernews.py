"""Hacker News 首页热榜 adapter：官方 Algolia API（front_page 榜单）。

重写自旧 ai_trending services/sources/hn.py，改动：
  - 删除 hn_heat 时间衰减热度函数——统一走 ranking.py 的榜位权重；
  - 只保留 fetch（原 search 关键词检索属于旧「主题订阅」，由 Phase 3 频率词规则取代）；
  - rank 按 Algolia 返回的 frontpage 顺序 enumerate；points/num_comments
    进 metrics 仅展示。
"""
from __future__ import annotations

from app.common.utils.text import parse_datetime
from app.hotlist.services.adapters.base import (
    HotSourceAdapter,
    RawEntry,
    register,
)

API_URL = "https://hn.algolia.com/api/v1/search?tags=front_page"


class HackerNewsAdapter(HotSourceAdapter):
    adapter_key = "hackernews"

    def fetch(self, params: dict) -> list[RawEntry]:
        data = self._get_json(API_URL, timeout=20)
        entries: list[RawEntry] = []
        for idx, hit in enumerate(data.get("hits") or [], 1):
            title = (hit.get("title") or "").strip()
            if not title:
                continue
            object_id = hit.get("objectID") or ""
            url = (hit.get("url") or "").strip()
            if not url and object_id:
                url = f"https://news.ycombinator.com/item?id={object_id}"
            if not url:
                continue
            points = int(hit.get("points") or 0)
            num_comments = int(hit.get("num_comments") or 0)
            entries.append(
                RawEntry(
                    rank=idx,
                    title=title,
                    url=url,
                    summary=(hit.get("story_text") or "").strip(),
                    published_at=parse_datetime(hit.get("created_at")),
                    metrics={"points": points, "num_comments": num_comments},
                )
            )
        return entries


register(HackerNewsAdapter())
