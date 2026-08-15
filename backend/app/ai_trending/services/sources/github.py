"""GitHub Trending 源：主通道 SSR HTML，失败降级 GitHub Search API。

- 主通道：https://github.com/trending?since=daily（SSR 渲染，仓库名/描述/今日 star 直接内嵌），
  用 lxml 解析（yfinance 已引入 lxml，不新增 beautifulsoup4）。
- 兜底：https://api.github.com/search/repositories?q=created:>日期&sort=stars&order=desc
  （匿名限额 10 次/分，仅降级用，够用）。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from lxml import html as lxml_html
from loguru import logger

from app.ai_trending.services.base import (
    RawItem,
    TrendingSource,
    TrendingSourceError,
    github_heat,
    parse_datetime,
)

_STARS_TODAY_RE = re.compile(r"([\d,]+)\s*stars?\s*today", re.IGNORECASE)


class GitHubSource(TrendingSource):
    """GitHub Trending 每日热门仓库，category=project。"""

    source_id = "github"
    source_name = "GitHub Trending"
    category_type = "project"
    filter_keywords: list[str] | None = None

    TRENDING_URL = "https://github.com/trending?since=daily"
    SEARCH_API = "https://api.github.com/search/repositories"

    def fetch(self) -> list[RawItem]:
        try:
            return self._fetch_html()
        except TrendingSourceError:
            logger.warning("github trending HTML 抓取失败，降级 GitHub Search API")
            return self._fetch_search_api()

    # ------------------------------------------------------------ 主通道 ----
    def _fetch_html(self) -> list[RawItem]:
        html_text = self._http_get(self.TRENDING_URL)
        root = lxml_html.fromstring(html_text)
        articles = root.xpath('//article[contains(@class, "Box-row")]')
        items: list[RawItem] = []
        for article in articles:
            anchors = article.xpath('.//h2//a')
            if not anchors:
                continue
            repo_href = (anchors[0].get("href") or "").strip("/")
            if not repo_href or "/" not in repo_href:
                continue
            full_name = repo_href
            desc_nodes = article.xpath('.//p[contains(@class, "col-9")]')
            description = desc_nodes[0].text_content().strip() if desc_nodes else ""
            stars_today = 0
            m = _STARS_TODAY_RE.search(article.text_content())
            if m:
                stars_today = int(m.group(1).replace(",", ""))
            # SSR 页没有发布时间，用抓取时间兜底（热度衰减最小）
            published_at = datetime.now(timezone.utc)
            heat = github_heat(stars_today, published_at)
            items.append(
                RawItem(
                    source=self.source_id,
                    title=full_name,
                    url=f"https://github.com/{full_name}",
                    summary=description,
                    category=self.category_type,
                    tags=[],
                    published_at=published_at,
                    heat_score=heat,
                    heat_meta={"stars_today": stars_today},
                )
            )
        return items

    # ------------------------------------------------------------ 兜底 ----
    def _fetch_search_api(self) -> list[RawItem]:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        url = (
            f"{self.SEARCH_API}?q=created:>{since}&sort=stars&order=desc&per_page=30"
        )
        data = self._http_get_json(
            url, headers={"Accept": "application/vnd.github+json"}
        )
        items: list[RawItem] = []
        for repo in data.get("items") or []:
            full_name = repo.get("full_name") or ""
            html_url = repo.get("html_url") or ""
            if not full_name or not html_url:
                continue
            stars = int(repo.get("stargazers_count") or 0)
            published_at = parse_datetime(repo.get("created_at"))
            heat = github_heat(stars, published_at)
            language = repo.get("language") or ""
            tags = [language] if language else []
            items.append(
                RawItem(
                    source=self.source_id,
                    title=full_name,
                    url=html_url,
                    summary=repo.get("description") or "",
                    category=self.category_type,
                    tags=tags,
                    published_at=published_at,
                    heat_score=heat,
                    heat_meta={"stars": stars, "stars_today": 0},
                )
            )
        return items
