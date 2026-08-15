"""
夸克网盘资源链接的搜索 Provider 策略层。

夸克没有官方开放的网盘资源搜索 API，因此用"搜索引擎/第三方 API"组合来发现
pan.quark.cn/s/{share_id} 分享链接，统一解析成 QuarkLink 后再标准化。

渠道实测结论（2025-02，国内网络）：
- bilibili：B站视频搜索 API，国内直连稳定，视频简介常带夸克分享链接，命中率最高
- toutiao：头条搜索，国内直连稳定，网盘帖命中率中等（唯一需要 HTML 渲染解析）
- bing / duckduckgo：国内网络不可达或 0 命中，保留为海外/代理环境备选
- 神马 m.sm.cn：首次命中后立即触发验证码 punish，剔除
- 360 www.so.com / m.so.com：连续请求触发风控（访问异常页），剔除
- 搜狗 www.sogou.com：反爬 JS 页，剔除

搜索渠道可扩展：新增 Provider 只需实现 SearchProvider 接口并在 build_providers 注册。
"""
from __future__ import annotations

import concurrent.futures
import html
import json
import re
import time
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

# B站 -412 风控退避窗口：记录最近一次触发时间，窗口内不再傻等重试，
# 快速返回空结果让头条等其他渠道接管（用户连续搜索多个词时避免每轮都等 2s）。
_BILI_RATELIMIT_WINDOW = 30.0
_bili_last_412_at: float = 0.0


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
    """按 share_id 去重（保留先出现的条目及其提取码/摘要）。"""
    seen: set[str] = set()
    out: list[QuarkLink] = []
    for link in links:
        if link.share_id in seen:
            continue
        seen.add(link.share_id)
        out.append(link)
    return out


def _clean_html(text: str) -> str:
    """去除 HTML 标签并反转义实体，B站/头条返回的标题摘要常带 <em> 等标签。"""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return html.unescape(text).strip()


class SearchProvider(ABC):
    provider_id: str = ""
    provider_name: str = ""

    @abstractmethod
    def search(self, query: str, page: int, page_size: int) -> list[QuarkLink]:
        """返回 query 命中的夸克分享链接，按相关度排序。"""


class BiliBiliProvider(SearchProvider):
    """
    B站视频搜索 API：国内直连稳定、无需登录。

    很多 UP 主会在视频标题/简介里直接放夸克网盘分享链接（"我用夸克网盘给你分享了…"），
    因此从搜索结果中解析 pan.quark.cn/s/ 命中率很高，是当前召回主力渠道。
    """

    provider_id = "bilibili"
    provider_name = "B站视频搜索"

    def search(self, query: str, page: int, page_size: int) -> list[QuarkLink]:
        global _bili_last_412_at

        # 风控退避：最近触发过 -412 的窗口内直接跳过（返回空），避免连续压测时
        # 每个搜索词都等 2s 重试、拖慢整体；窗口过后自动恢复
        if time.time() - _bili_last_412_at < _BILI_RATELIMIT_WINDOW:
            logger.info("resource.search provider=bilibili 风控退避中，跳过本轮")
            return []

        # B站 API 偶发返回非 JSON（风控/限流），重试 2 次；整体失败抛异常由上层合并兜底
        last_err: Optional[Exception] = None
        payload: Optional[dict] = None
        for attempt in range(3):
            try:
                resp = requests.get(
                    "https://api.bilibili.com/x/web-interface/search/type",
                    params={
                        "search_type": "video",
                        "keyword": query,
                        "page": page,
                        "page_size": page_size,
                    },
                    headers={
                        "User-Agent": UA,
                        "Referer": "https://search.bilibili.com/",
                        "Accept": "application/json, text/plain, */*",
                    },
                    timeout=10,
                )
                payload = resp.json()
                break
            except (requests.RequestException, ValueError) as exc:
                last_err = exc
                time.sleep(1)
        if payload is None:
            raise RuntimeError(f"B站搜索接口连续失败：{last_err}")
        if payload.get("code") == -412:
            # -412 是短时风控：等待 2s 重试一次，重试仍失败才进入退避窗口，
            # 避免单次偶发风控后浪费后续请求
            logger.warning("resource.search provider=bilibili 触发 -412 风控，等待 2s 重试")
            time.sleep(2)
            try:
                resp = requests.get(
                    "https://api.bilibili.com/x/web-interface/search/type",
                    params={
                        "search_type": "video",
                        "keyword": query,
                        "page": page,
                        "page_size": page_size,
                    },
                    headers={
                        "User-Agent": UA,
                        "Referer": "https://search.bilibili.com/",
                        "Accept": "application/json, text/plain, */*",
                    },
                    timeout=10,
                )
                payload = resp.json()
            except (requests.RequestException, ValueError) as exc:
                _bili_last_412_at = time.time()
                logger.warning(f"resource.search provider=bilibili -412 重试失败: {exc}")
                return []
            if payload.get("code") != 0:
                _bili_last_412_at = time.time()
                return []
        elif payload.get("code") != 0:
            logger.warning(f"resource.search provider=bilibili 返回 code={payload.get('code')}")
            return []

        rows = (payload.get("data") or {}).get("result") or []
        links: list[QuarkLink] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = _clean_html(row.get("title"))
            description = _clean_html(row.get("description"))
            # 一条视频的简介里可能放多个分享链接，全部提取
            for m in _SHARE_RE.finditer(f"{title} {description}"):
                share_url = m.group(0)
                share_id = m.group(1)
                if not share_id:
                    continue
                snippet = description[:200]
                links.append(
                    QuarkLink(
                        title=title or share_url,
                        url=share_url,
                        share_id=share_id,
                        snippet=snippet,
                        pwd=extract_pwd(f"{title} {description}"),
                    )
                )
        return _dedupe(links)


class BingRssProvider(SearchProvider):
    """Bing 搜索 RSS 接口：国内可达但夸克链接命中率低，保留为海外/代理环境备选。"""

    provider_id = "bing"
    provider_name = "Bing 搜索"

    def search(self, query: str, page: int, page_size: int) -> list[QuarkLink]:
        offset = (page - 1) * page_size
        resp = requests.get(
            "https://cn.bing.com/search",
            params={"format": "rss", "q": query, "count": page_size, "first": offset},
            headers={"User-Agent": UA},
            timeout=8,
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
    """DuckDuckGo HTML 接口（海外网络更稳，国内基本不可达，保留为备选渠道）。"""

    provider_id = "duckduckgo"
    provider_name = "DuckDuckGo 搜索"

    def search(self, query: str, page: int, page_size: int) -> list[QuarkLink]:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "s": (page - 1) * page_size},
            headers={"User-Agent": UA},
            timeout=8,
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


class ToutiaoProvider(SearchProvider):
    """
    头条搜索（so.toutiao.com）：国内可直连、结果里大量包含网盘分享帖。
    解析页面内嵌的 ala-data 结构化数据（title/summary_text），从中提取夸克分享链接。

    备注：页面结构可能随头条改版变化；若一段时间失效，优先检查
    `script[data-for="ala-data"]` 与 `"title"/"summary_text"` 字段是否还在。
    """

    provider_id = "toutiao"
    provider_name = "头条搜索"

    # 分类词后缀会触发头条的商业广告页（整页夸克 app 推广、无资源帖），
    # 首次 0 条命中时去掉这些词再搜一次（如 "流浪地球 电影 夸克网盘" → "流浪地球 夸克网盘"）。
    _FALLBACK_WORDS = {"电影", "剧集", "电子书", "动漫", "音乐", "软件"}

    # 分享链接也可能写成 //pan.quark.cn/s/xxx 或带参数
    _SHARE_RE = re.compile(r"https?://(?:www\.)?pan\.quark\.cn/s/([A-Za-z0-9]{12,40})")
    _TITLE_RE = re.compile(r'"title"\s*:\s*"(.*?)"', re.S)
    _SUM_RE = re.compile(r'"(?:summary_text|summary)"\s*:\s*"(.*?)"', re.S)

    @staticmethod
    def _decode_json_str(s: str) -> str:
        """头条 JSON 里的字符串带 \\u003c 等转义，用 json.loads 安全还原（避免中文乱码）。"""
        try:
            return json.loads(f'"{s}"')
        except Exception:  # noqa: BLE001 转义不完整时退回原样
            return s

    def search(self, query: str, page: int, page_size: int) -> list[QuarkLink]:
        links = self._search_once(query, page, page_size)
        if links:
            return links
        # 0 条命中 → 去掉分类词重试（头条对"X 电影/电子书… 夸克网盘"常整页广告）。
        # 实测头条对无间隔的连续请求会返回空响应，回退前必须等 1.5s 左右。
        reduced = [w for w in query.split() if w not in self._FALLBACK_WORDS]
        new_query = " ".join(reduced).strip()
        if new_query and new_query != query:
            logger.info(f"resource.search provider=toutiao 分类词回退: {query!r} -> {new_query!r}")
            time.sleep(1.5)
            links = self._search_once(new_query, page, page_size)
        return links

    def _search_once(self, query: str, page: int, page_size: int) -> list[QuarkLink]:
        # 注意：只能带 dv/keyword 两个参数。实测加 offset/format 会让头条返回
        # 另一种结构（无 ala-data 块、无夸克链接），翻页暂不做。
        resp = requests.get(
            "https://so.toutiao.com/search",
            params={"dv": "0", "keyword": query},
            headers={
                "User-Agent": UA,
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://so.toutiao.com/",
            },
            timeout=10,
        )
        resp.raise_for_status()
        root = etree.HTML(resp.text)
        if root is None:
            return []

        links: list[QuarkLink] = []
        for node in root.xpath('//script[@data-for="ala-data"]'):
            content = node.text or ""
            share_match = self._SHARE_RE.search(content)
            if not share_match:
                continue
            title_m = self._TITLE_RE.search(content)
            sum_m = self._SUM_RE.search(content)
            title = ""
            if title_m:
                title = re.sub(r"<[^>]+>", "", self._decode_json_str(title_m.group(1))).strip()
            snippet = ""
            if sum_m:
                snippet = re.sub(r"<[^>]+>", "", self._decode_json_str(sum_m.group(1))).strip()[:200]
            share_url = share_match.group(0)
            share_id = share_match.group(1)
            # 结果块里的 title 是页面标题（如"夸克网盘"）时用摘要补充描述
            if title and title != "夸克网盘":
                display_title = title
            else:
                display_title = snippet or share_url
            links.append(
                QuarkLink(
                    title=display_title[:120],
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


# 默认启用顺序：自定义 API（若配置）→ B站 → 头条 → Bing → DDG。
# 实测国内网络 B站 API 命中率最高且稳定，排在头条前面；
# Bing/DDG 保留为海外/代理环境备选，并发执行不阻塞整体。
def build_providers() -> list[SearchProvider]:
    custom, bili, toutiao, bing, ddg = (
        CustomApiProvider(),
        BiliBiliProvider(),
        ToutiaoProvider(),
        BingRssProvider(),
        DuckDuckGoHtmlProvider(),
    )
    ordered: list[SearchProvider] = [custom] if custom.base_url else []
    ordered += [bili, toutiao, bing, ddg]
    return ordered


def search_with_providers(query: str, page: int, page_size: int) -> tuple[list[QuarkLink], str]:
    """并发执行所有 Provider，合并各渠道结果（按 share_id 去重），显著提升召回率。

    合并策略：
      1. 并发提交所有渠道，单渠道超时 8~12s（B站/头条 10s，Bing/DDG 8s，自定义 API 12s）；
      2. 收集所有成功返回的结果，按 share_id 去重、保留首个条目的提取码/摘要；
      3. 命中渠道名用顿号拼接（如 "B站视频搜索、头条搜索"）供前端展示；
      4. 全部渠道失败时抛出汇总错误，由上层转为 502。
    """
    providers = build_providers()
    errors: list[str] = []
    hit_providers: list[str] = []
    merged: list[QuarkLink] = []
    # 是否至少有一个渠道"成功执行"（返回了列表，无论空/非空）：
    # 有渠道成功执行就说明搜索链路本身可用，其他渠道的网络失败不应导致 502，
    # 而应返回 0 结果提示（由上层降级换词）；只有全部渠道都抛异常才视为渠道全挂。
    any_ok = False

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(providers)) as pool:
        futures: dict[concurrent.futures.Future, SearchProvider] = {}
        for provider in providers:
            fut = pool.submit(provider.search, query, page, page_size)
            futures[fut] = provider
        for fut in concurrent.futures.as_completed(futures):
            provider = futures[fut]
            try:
                links = fut.result()
            except Exception as exc:  # noqa: BLE001 单个渠道失败不阻断整体搜索
                errors.append(f"{provider.provider_name}: {exc}")
                logger.warning(f"resource.search provider={provider.provider_id} 失败: {exc}")
                continue
            any_ok = True
            if links:
                hit_providers.append(provider.provider_name)
                merged.extend(links)
                logger.info(f"resource.search provider={provider.provider_id} 命中 {len(links)} 条")

    deduped = _dedupe(merged)
    if deduped:
        logger.info(f"resource.search 合并结果 {len(deduped)} 条（渠道: {'、'.join(hit_providers)}）")
        return deduped, "、".join(hit_providers)
    # 有渠道成功执行但都 0 命中：不是渠道故障，返回空列表让上层降级换词
    if any_ok:
        return [], ""
    if errors:
        raise RuntimeError("；".join(errors))
    return [], ""
