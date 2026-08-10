"""
夸克网盘资源链接的搜索 Provider 策略层。

夸克没有官方开放的网盘资源搜索 API，因此用"搜索引擎/第三方 API"组合来发现
pan.quark.cn/s/{share_id} 分享链接，统一解析成 QuarkLink 后再标准化。

搜索渠道可扩展：新增 Provider 只需实现 SearchProvider 接口并在 QUARK_PROVIDERS 注册。
"""
from __future__ import annotations

import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from typing import Optional

import requests
from lxml import etree
from loguru import logger
from pydantic import BaseModel

from app.core.config import get_settings

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# pan.quark.cn/s/ 分享短链（share_id 通常 26 位左右大小写字母数字）
_SHARE_RE = re.compile(r"https?://(?:www\.)?pan\.quark\.cn/s/([A-Za-z0-9]{12,40})")
# 分享提取码：常见格式 "提取码:xxxx" / "密码 1234" / "pwd=abcd"
_PWD_RE = re.compile(
    r"(?:提取码|访问码|密码|pwd|password|passwd|code|key)\s*[=:：]?\s*([0-9a-zA-Z]{4,6})",
    re.IGNORECASE,
)


class QuarkLink(BaseModel):
    """一条候选夸克分享链接。"""

    title: str
    url: str
    share_id: str
    snippet: str = ""
    pwd: str = ""


def parse_share_id(url: str) -> Optional[str]:
    m = _SHARE_RE.search(url)
    return m.group(1) if m else None


def normalize_link(text: str) -> Optional[str]:
    """从任意文本里抠出第一个 pan.quark.cn/s/ 完整链接。"""
    m = _SHARE_RE.search(text)
    return m.group(0) if m else None


def extract_pwd(text: str) -> str:
    """从标题/摘要文本里尝试提取分享提取码。"""
    m = _PWD_RE.search(text or "")
    return m.group(1) if m else ""


def _dedupe(links: list[QuarkLink]) -> list[QuarkLink]:
    seen: set[str] = set()
    out: list[QuarkLink] = []
    for link in links:
        if link.share_id in seen:
            continue
        seen.add(link.share_id)
        out.append(link)
    return out


class SearchProvider(ABC):
    provider_id: str = ""
    provider_name: str = ""

    @abstractmethod
    def search(self, query: str, page: int, page_size: int) -> list[QuarkLink]:
        """返回 query 命中的夸克分享链接，按相关度排序。"""


class BingRssProvider(SearchProvider):
    """Bing 搜索 RSS 接口：国内可直连、无需 JS 渲染，结果稳定。"""

    provider_id = "bing"
    provider_name = "Bing 搜索"

    def search(self, query: str, page: int, page_size: int) -> list[QuarkLink]:
        offset = (page - 1) * page_size
        resp = requests.get(
            "https://www.bing.com/search",
            params={"format": "rss", "q": query, "count": page_size, "first": offset},
            headers={"User-Agent": UA},
            timeout=12,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        m_ns = "{http://schemas.microsoft.com/LiveSearch/2008/04/XML/web}"
        items = root.findall(f".//{m_ns}item") or root.findall(".//item")

        links: list[QuarkLink] = []
        for item in items:
            title = (item.findtext(f"{m_ns}title") or item.findtext("title") or "").strip()
            real_url = (item.findtext(f"{m_ns}url") or "").strip()
            link_tag = (item.findtext("link") or "").strip()
            description = html.unescape(item.findtext(f"{m_ns}description") or item.findtext("description") or "")
            snippet = re.sub(r"<[^>]+>", " ", description)
            snippet = html.unescape(snippet)[:200]

            url = real_url or link_tag
            share_url = normalize_link(url) or normalize_link(title)
            if not share_url:
                continue
            share_id = parse_share_id(share_url)
            if not share_id:
                continue
            links.append(
                QuarkLink(
                    title=title or share_url,
                    url=share_url,
                    share_id=share_id,
                    snippet=snippet,
                    pwd=extract_pwd(f"{title} {snippet}"),
                )
            )
        return _dedupe(links)


class DuckDuckGoHtmlProvider(SearchProvider):
    """DuckDuckGo HTML 接口（备选渠道，海外网络更稳）。"""

    provider_id = "duckduckgo"
    provider_name = "DuckDuckGo 搜索"

    def search(self, query: str, page: int, page_size: int) -> list[QuarkLink]:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "s": (page - 1) * page_size},
            headers={"User-Agent": UA},
            timeout=12,
        )
        resp.raise_for_status()
        root = etree.HTML(resp.text)
        if root is None:
            return []

        links: list[QuarkLink] = []
        for node in root.xpath("//a[contains(@class,'result__a')]"):
            raw_href = node.get("href") or ""
            title = html.unescape("".join(node.itertext())).strip()
            # DDG 的跳转链接：//duckduckgo.com/l/?uddg=<urlencoded>&rut=...
            parsed = urllib.parse.urlparse(raw_href)
            uddg = urllib.parse.parse_qs(parsed.query).get("uddg", [None])[0]
            target = uddg or raw_href
            share_url = normalize_link(target) or normalize_link(title)
            if not share_url:
                continue
            share_id = parse_share_id(share_url)
            if not share_id:
                continue
            snippet_node = node.getparent()
            snippet = ""
            if snippet_node is not None:
                sn = snippet_node.xpath(".//a[contains(@class,'result__snippet')]")
                if sn:
                    snippet = html.unescape("".join(sn[0].itertext()))[:200]
            links.append(
                QuarkLink(
                    title=title or share_url,
                    url=share_url,
                    share_id=share_id,
                    snippet=snippet,
                    pwd=extract_pwd(f"{title} {snippet}"),
                )
            )
        return _dedupe(links)


class CustomApiProvider(SearchProvider):
    """
    自定义搜索 API（可选）：在环境变量 WORKBENCH_QUARK_SEARCH_API 配置一个第三方
    夸克资源搜索接口，GET {url}?keyword=&page=&page_size=，响应支持多种常见 JSON 结构：
      {"data"/"items"/"list"/"results": [{"title"/"name": ..., "url"/"link"/"share_url": ...,
       "pwd"/"password": ...}]}
    配置了才启用，否则自动跳过。
    """

    provider_id = "custom_api"
    provider_name = "自定义搜索 API"

    @property
    def base_url(self) -> str:
        return (get_settings().quark_search_api or "").strip()

    def search(self, query: str, page: int, page_size: int) -> list[QuarkLink]:
        base = self.base_url
        if not base:
            return []
        resp = requests.get(
            base,
            params={"keyword": query, "page": page, "page_size": page_size},
            headers={"User-Agent": UA},
            timeout=12,
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("data") or payload.get("items") or payload.get("list") or payload.get("results") or []
        if not isinstance(rows, list):
            return []

        links: list[QuarkLink] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or row.get("name") or "")
            url = str(row.get("url") or row.get("link") or row.get("share_url") or "")
            pwd = str(row.get("pwd") or row.get("password") or row.get("提取码") or "")
            desc = str(row.get("desc") or row.get("snippet") or "")
            share_url = normalize_link(url) or normalize_link(title)
            if not share_url:
                continue
            share_id = parse_share_id(share_url)
            if not share_id:
                continue
            links.append(
                QuarkLink(
                    title=title or share_url,
                    url=share_url,
                    share_id=share_id,
                    snippet=desc[:200],
                    pwd=pwd or extract_pwd(f"{title} {desc}"),
                )
            )
        return _dedupe(links)


# 默认启用顺序：自定义 API（若配置）→ Bing → DDG
def build_providers() -> list[SearchProvider]:
    bing, ddg, custom = BingRssProvider(), DuckDuckGoHtmlProvider(), CustomApiProvider()
    ordered: list[SearchProvider] = [custom] if custom.base_url else []
    ordered += [bing, ddg]
    return ordered


def search_with_providers(query: str, page: int, page_size: int) -> tuple[list[QuarkLink], str]:
    """按序尝试各 Provider，返回 (结果, 实际命中的 provider_id)。"""
    errors: list[str] = []
    for provider in build_providers():
        try:
            links = provider.search(query, page, page_size)
            if links:
                return links, provider.provider_id
            logger.info(f"resource.search provider={provider.provider_id} 无夸克链接命中")
        except Exception as exc:  # noqa: BLE001 单个渠道失败不阻断整体搜索
            errors.append(f"{provider.provider_name}: {exc}")
            logger.warning(f"resource.search provider={provider.provider_id} 失败: {exc}")
    if errors:
        raise RuntimeError("；".join(errors))
    return [], ""
