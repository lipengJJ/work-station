"""GitHub Trending adapter：主通道 SSR HTML，失败降级 GitHub Search API。

重写自旧 ai_trending services/sources/github.py，改动：
  - 删除 github_heat；rank 按页面/接口原始顺序 enumerate（HTML 页面顺序本身就是 trending 排名）；
  - 只保留 fetch（search 检索能力由 Phase 3 频率词规则取代）。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from loguru import logger
from lxml import html as lxml_html

from app.common.utils.text import parse_datetime
from app.hotlist.services.adapters.base import (
    HotSourceAdapter,
    HotSourceAdapterError,
    RawEntry,
    register,
)

TRENDING_URL = "https://github.com/trending?since=daily"
SEARCH_API = "https://api.github.com/search/repositories"
_STARS_TODAY_RE = re.compile(r"([\d,]+)\s*stars?\s*today", re.IGNORECASE)


class GitHubAdapter(HotSourceAdapter):
    adapter_key = "github"

    def fetch(self, params: dict) -> list[RawEntry]:
        try:
            return self._fetch_html()
        except HotSourceAdapterError:
            logger.warning("github trending HTML 抓取失败，降级 GitHub Search API")
            return self._fetch_search_api()

    def _fetch_html(self) -> list[RawEntry]:
        html_text = self._request(TRENDING_URL, timeout=20).text
        root = lxml_html.fromstring(html_text)
        articles = root.xpath('//article[contains(@class, "Box-row")]')
        entries: list[RawEntry] = []
        for idx, article in enumerate(articles, 1):
            anchors = article.xpath(".//h2//a")
            if not anchors:
                continue
            repo_href = (anchors[0].get("href") or "").strip("/")
            if not repo_href or "/" not in repo_href:
                continue
            desc_nodes = article.xpath('.//p[contains(@class, "col-9")]')
            description = desc_nodes[0].text_content().strip() if desc_nodes else ""
            stars_today = 0
            m = _STARS_TODAY_RE.search(article.text_content())
            if m:
                stars_today = int(m.group(1).replace(",", ""))
            entries.append(
                RawEntry(
                    rank=idx,
                    title=repo_href,
                    url=f"https://github.com/{repo_href}",
                    summary=description,
                    published_at=datetime.now(timezone.utc),  # SSR 页没有发布时间，用抓取时间兜底
                    metrics={"stars_today": stars_today},
                )
            )
        if not entries:
            raise HotSourceAdapterError("github trending HTML 未解析出任何条目")
        return entries

    def _fetch_search_api(self) -> list[RawEntry]:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        url = f"{SEARCH_API}?q=created:>{since}&sort=stars&order=desc&per_page=30"
        data = self._get_json(url, timeout=20, headers={"Accept": "application/vnd.github+json"})
        entries: list[RawEntry] = []
        for idx, repo in enumerate(data.get("items") or [], 1):
            full_name = repo.get("full_name") or ""
            html_url = repo.get("html_url") or ""
            if not full_name or not html_url:
                continue
            stars = int(repo.get("stargazers_count") or 0)
            entries.append(
                RawEntry(
                    rank=idx,
                    title=full_name,
                    url=html_url,
                    summary=repo.get("description") or "",
                    published_at=parse_datetime(repo.get("created_at")),
                    metrics={"stars": stars, "stars_today": 0},
                )
            )
        return entries


register(GitHubAdapter())
