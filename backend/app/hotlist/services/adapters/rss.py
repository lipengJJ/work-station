"""通用 RSS/Atom adapter：一个类驱动任意 feed 源（原 InfoQ + 36氪 各一个类，合并配置化）。

重写自旧 ai_trending services/sources/infoq.py + kr36.py，改动：
  - 删除两源各自的 AI 关键词过滤（kr36 的 filter_ai_keywords）——由 Phase 3 频率词规则取代，
    能力严格更强（正则 / 必须词 / 排除词 / 限量），adapter 只管「请求 + 解析 + 排位」；
  - feed 地址不再写死在类里，从 adapter_params['url'] 读，新增一个 RSS 源前端点一下就行；
  - rank 按 feed 条目原始顺序（多数 feed 已按发布时间倒序）enumerate。
"""
from __future__ import annotations

import feedparser

from app.common.utils.text import parse_struct_time, strip_html
from app.hotlist.services.adapters.base import (
    HotSourceAdapter,
    HotSourceAdapterError,
    RawEntry,
    register,
)


class RssAdapter(HotSourceAdapter):
    adapter_key = "rss"

    def fetch(self, params: dict) -> list[RawEntry]:
        url = params.get("url", "")
        if not url:
            raise HotSourceAdapterError("rss adapter 缺少 url 参数")
        content = self._request(url, timeout=20).content
        feed = feedparser.parse(content)
        if getattr(feed, "bozo", 0) and not feed.entries:
            raise HotSourceAdapterError(f"rss feed 解析失败（bozo）: {url}")
        entries: list[RawEntry] = []
        for idx, entry in enumerate(feed.entries or [], 1):
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            summary = strip_html(entry.get("description") or "")
            published_at = parse_struct_time(
                entry.get("published_parsed") or entry.get("updated_parsed")
            )
            entries.append(
                RawEntry(rank=idx, title=title, url=link, summary=summary, published_at=published_at)
            )
        return entries


register(RssAdapter())
