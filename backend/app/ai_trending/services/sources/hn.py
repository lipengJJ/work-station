"""Hacker News 源：官方 Algolia API（front_page 榜单 + 关键词检索）。"""
from __future__ import annotations

from urllib.parse import quote_plus

from loguru import logger

from app.ai_trending.services.base import (
    RawItem,
    TrendingSource,
    TrendingSourceError,
    hn_heat,
    parse_datetime,
)


class HackerNewsSource(TrendingSource):
    """Hacker News 首页热榜（https://hn.algolia.com/api/v1/search?tags=front_page）。

    原始热度指标：points（HN 评分）+ num_comments（评论数），映射 category=news。
    search() 覆写为 Algolia /search?query= 真检索（逐关键词请求，合并去重由 upsert 兜底）。
    """

    source_id = "hn"
    source_name = "Hacker News"
    category_type = "news"
    filter_keywords: list[str] | None = None  # HN 内容浓度高，不过滤

    API_URL = "https://hn.algolia.com/api/v1/search?tags=front_page"
    SEARCH_API = "https://hn.algolia.com/api/v1/search"

    def fetch(self) -> list[RawItem]:
        data = self._http_get_json(self.API_URL)
        return self._parse_hits(data.get("hits") or [])

    def search(self, keywords: list[str], page_size: int = 30) -> list[RawItem]:
        """Algolia 关键词检索：每关键词一次请求，tags=story 排除 job/comment。"""
        items: list[RawItem] = []
        for kw in keywords or []:
            kw = str(kw).strip()
            if not kw:
                continue
            url = (
                f"{self.SEARCH_API}?query={quote_plus(kw)}"
                f"&tags=story&hitsPerPage={page_size}"
            )
            try:
                data = self._http_get_json(url)
            except TrendingSourceError as exc:
                logger.warning(f"hn search 关键词「{kw}」请求失败: {exc}")
                continue
            items.extend(self._parse_hits(data.get("hits") or []))
        return items

    # ------------------------------------------------------------ 解析 ----
    def _parse_hits(self, hits: list[dict]) -> list[RawItem]:
        """Algolia hit 列表 → RawItem 列表（fetch / search 共用）。"""
        items: list[RawItem] = []
        for hit in hits or []:
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
