"""Hacker News 源：官方 Algolia API（front_page 榜单）。"""
from __future__ import annotations

from app.ai_trending.services.base import RawItem, TrendingSource, hn_heat, parse_datetime


class HackerNewsSource(TrendingSource):
    """Hacker News 首页热榜（https://hn.algolia.com/api/v1/search?tags=front_page）。

    原始热度指标：points（HN 评分）+ num_comments（评论数），映射 category=news。
    """

    source_id = "hn"
    source_name = "Hacker News"
    category_type = "news"
    filter_keywords: list[str] | None = None  # HN 内容浓度高，不过滤

    API_URL = "https://hn.algolia.com/api/v1/search?tags=front_page"

    def fetch(self) -> list[RawItem]:
        data = self._http_get_json(self.API_URL)
        items: list[RawItem] = []
        for hit in data.get("hits") or []:
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
            published_at = parse_datetime(hit.get("created_at"))
            story_text = (hit.get("story_text") or "").strip()
            summary = story_text or f"HN {points} 分 · {num_comments} 条评论"
            heat = hn_heat(points, published_at)
            items.append(
                RawItem(
                    source=self.source_id,
                    title=title,
                    url=url,
                    summary=summary,
                    category=self.category_type,
                    tags=[],
                    published_at=published_at,
                    heat_score=heat,
                    heat_meta={"points": points, "num_comments": num_comments},
                )
            )
        return items
