"""AI 开发热点抓取服务层：抽象基类 + 热度归一化 + URL 归一化 + 注册表。

所有无 IO 的纯函数（热度计算 / URL 归一化 / 关键词过滤）都集中在这里，可单测；
各数据源只负责「请求 + 解析 + 调用热度函数」，不碰数据库。
"""
from __future__ import annotations

import hashlib
import html as html_lib
import re
from abc import ABC, abstractmethod
from calendar import timegm
from datetime import datetime, timezone
from math import log10 as _log10
from math import log2 as _log2
from time import struct_time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from pydantic import BaseModel, Field

# ------------------------------------------------------------------ 常量 ----
# 各源原始热度指标的参考上限（用于跨源归一化到 0-100）
MAX_REF = {
    "hn": 10_000,  # HN points 参考上限（log2 基准）
    "github": 5_000,  # GitHub stars_today 参考上限
    "hf_models": 1_000_000,  # HF trendingScore 参考上限（log10 基准）
}
PAPER_RSS_BASE = 10.0  # arXiv / HF papers / RSS 时间衰减默认分上限
DECAY_HALF_LIFE_HOURS = 24.0  # 统一时间衰减半衰期（小时）

# URL 归一化时丢弃的跟踪参数
DROP_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "ref",
    "source",
    "from",
    "mc_cid",
    "mc_eid",
}

# 已知仅支持 https 的站点：http/https 统一为 https（跨源去重需要，如 arXiv Atom 的 entry.id 是 http）
HTTPS_ONLY_HOSTS = {
    "arxiv.org",
    "www.arxiv.org",
    "huggingface.co",
    "www.huggingface.co",
    "hf.co",
    "github.com",
    "www.github.com",
    "news.ycombinator.com",
    "infoq.cn",
    "www.infoq.cn",
    "36kr.com",
    "www.36kr.com",
}

# AI 关键词过滤（标题 + 摘要命中任一即保留；36氪默认启用，InfoQ 提供开关）
AI_KEYWORDS = [
    "人工智能",
    "AI",
    "大模型",
    "OpenAI",
    "LLM",
    "机器学习",
    "深度学习",
    "智能体",
    "AGI",
    "AIGC",
    "生成式",
    "GPT",
    "Claude",
    "Gemini",
    "开源",
    "程序员",
    "编程",
    "开发者",
    "技术",
]

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; WorkBench-AITrending/1.0; +https://github.com)",
}


# ------------------------------------------------------------ 基础数学 ----
def log2(x: float) -> float:
    """安全 log2（0/负数钳到 1e-9 避免 ValueError）。"""
    return _log2(max(float(x), 1e-9))


def log10(x: float) -> float:
    """安全 log10（0/负数钳到 1e-9 避免 ValueError）。"""
    return _log10(max(float(x), 1e-9))


def hours_since(dt: datetime | None, now: datetime | None = None) -> float:
    """距发布时间的小时数；dt 缺失时返回 0（抓取时间兜底），负值钳到 0。"""
    if dt is None:
        return 0.0
    now = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 3600.0)


def time_decay_factor(published_at: datetime | None, now: datetime | None = None) -> float:
    """0.5 ** (距发布小时数 / 24)，输出 (0, 1]。"""
    return 0.5 ** (hours_since(published_at, now) / DECAY_HALF_LIFE_HOURS)


def normalize_heat(raw: float, max_ref: float) -> float:
    """clamp(raw / max_ref * 100, 0, 100)。"""
    if max_ref <= 0:
        return 0.0
    return max(0.0, min(100.0, float(raw) / max_ref * 100.0))


def final_heat(
    base_score: float, published_at: datetime | None, now: datetime | None = None
) -> float:
    """round(base_score * time_decay_factor(...), 2)，统一收尾。"""
    return round(float(base_score) * time_decay_factor(published_at, now), 2)


# ------------------------------------------------------------ 各源热度 ----
def hn_heat(points: int, published_at: datetime | None, now: datetime | None = None) -> float:
    """HN：base = normalize_heat(log2(points + 1), log2(10_001))，再乘时间衰减。"""
    base = normalize_heat(log2(points + 1), log2(MAX_REF["hn"] + 1))
    return final_heat(base, published_at, now)


def github_heat(
    stars_today: int, published_at: datetime | None, now: datetime | None = None
) -> float:
    """GitHub：base = normalize_heat(log2(stars_today + 1), log2(5_001))，再乘时间衰减。"""
    base = normalize_heat(log2(stars_today + 1), log2(MAX_REF["github"] + 1))
    return final_heat(base, published_at, now)


def paper_heat(published_at: datetime | None, now: datetime | None = None) -> float:
    """arXiv / HF papers / RSS 共用：base = normalize_heat(max(0, 10 - hours/6), 10)，再乘时间衰减。"""
    hours = hours_since(published_at, now)
    base = normalize_heat(max(0.0, PAPER_RSS_BASE - hours / 6.0), PAPER_RSS_BASE)
    return final_heat(base, published_at, now)


def hf_models_heat(
    trending_score: float, published_at: datetime | None, now: datetime | None = None
) -> float:
    """HF 模型：base = normalize_heat(log10(trending_score + 1), log10(1_000_001))，再乘时间衰减。"""
    base = normalize_heat(log10(trending_score + 1), log10(MAX_REF["hf_models"] + 1))
    return final_heat(base, published_at, now)


# ---------------------------------------------------------- URL 归一化 ----
_ARXIV_ID_RE = re.compile(r"^(\d{4}\.\d{4,5})(?:v\d+)?$")


def normalize_url(url: str) -> str:
    """URL 归一化规则：
    1. strip 空白
    2. scheme + host 转小写
    3. 去掉末尾 '/'（根路径除外）
    4. 丢弃 DROP_QUERY_PARAMS 及所有 utm_* 前缀查询参数
    5. arXiv 特例：arxiv.org/abs/XXXX.XXXXXvN → 去版本号 → arxiv.org/abs/XXXX.XXXXX
    6. HF 特例：huggingface.co 链接统一为 https://huggingface.co/{model_id}（去 /blob/、/tree/ 等后缀）
    """
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path or ""
    fragment = parts.fragment

    # 已知仅支持 https 的站点：http/https 统一为 https，避免跨源同内容因 scheme 不同无法去重
    # （如 arXiv Atom feed 的 entry.id 是 http://，而 HF daily_papers 拼的是 https://）
    host_raw = netloc.split(":")[0]
    if scheme == "http" and host_raw in HTTPS_ONLY_HOSTS:
        scheme = "https"

    # 丢弃跟踪参数
    query = ""
    if parts.query:
        kept: list[tuple[str, str]] = []
        for k, v in parse_qsl(parts.query, keep_blank_values=True):
            kl = k.lower()
            if kl.startswith("utm_") or kl in DROP_QUERY_PARAMS:
                continue
            kept.append((k, v))
        query = urlencode(kept)

    # 去掉末尾斜杠（根路径除外）
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    host = netloc.split(":")[0]

    # arXiv 去版本号
    if host in ("arxiv.org", "www.arxiv.org"):
        m = re.search(r"/(abs|pdf)/([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?)", path)
        if m:
            base_id = re.sub(r"v\d+$", "", m.group(2))
            path = f"/abs/{base_id}"
            return urlunsplit((scheme, netloc, path, query, fragment))

    # HF 归一化：huggingface.co/{model_id}
    if host in ("huggingface.co", "www.huggingface.co", "hf.co"):
        segs = [s for s in path.split("/") if s]
        if segs and segs[0] == "models":
            segs = segs[1:]
        for cut in ("blob", "tree", "resolve", "raw", "commit"):
            if cut in segs:
                segs = segs[: segs.index(cut)]
        path = "/" + "/".join(segs) if segs else ""
        return urlunsplit((scheme, netloc, path, "", fragment))

    return urlunsplit((scheme, netloc, path, query, fragment))


def url_hash(url: str) -> str:
    """归一化 URL 的 MD5，作为跨源去重键。"""
    return hashlib.md5(normalize_url(url).encode("utf-8")).hexdigest()


# ---------------------------------------------------------- 关键词过滤 ----
def filter_ai_keywords(
    title: str, summary: str = "", keywords: list[str] | None = None
) -> bool:
    """大小写不敏感子串匹配（标题 + 摘要），命中任一关键词返回 True。"""
    kws = keywords or AI_KEYWORDS
    if not kws:
        return True
    haystack = f"{title or ''} {summary or ''}".lower()
    return any(str(k).lower() in haystack for k in kws)


# ---------------------------------------------------------- 时间解析 ----
def parse_datetime(value: str | None) -> datetime | None:
    """把 API / feed 的 ISO 8601 字符串解析成 aware UTC datetime；解析不了返回 None。"""
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def parse_struct_time(st: struct_time | None) -> datetime | None:
    """feedparser 的 published_parsed / updated_parsed（time.struct_time）→ aware UTC datetime。"""
    if not st:
        return None
    try:
        return datetime.fromtimestamp(timegm(st), tz=timezone.utc)
    except (OverflowError, OSError, ValueError, TypeError):
        return None


def strip_html(text: str) -> str:
    """去掉 HTML 标签 + 反转义实体，折叠空白，返回纯文本。"""
    if not text:
        return ""
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = html_lib.unescape(plain)
    return " ".join(plain.split())


# ------------------------------------------------------------ RawItem ----
class RawItem(BaseModel):
    """抓取器产出的标准化条目（不落库，Collector 负责入库）。"""

    source: str = ""
    title: str = ""
    url: str = ""
    summary: str = ""
    category: str = "news"  # news / project / paper / model
    tags: list[str] = Field(default_factory=list)
    published_at: datetime | None = None
    heat_score: float = 0.0
    heat_meta: dict = Field(default_factory=dict)


# ------------------------------------------------------- 抽象基类 + 注册表 ----
class TrendingSourceError(Exception):
    """热点源业务错误（请求失败 / 解析失败等），message 可直接展示/记录。"""


class TrendingSource(ABC):
    """热点源抽象基类。

    新增数据源三步：
      1. 实现 TrendingSource 子类（source_id / source_name / category_type + fetch()）
      2. services/sources/__init__.py 注册一行
      3. services/scheduler_jobs.py 加 cron job 配置一行
    前端来源 Tab 与 /sources 接口自动出现，无需改 controller。
    """

    source_id: str = ""
    source_name: str = ""
    category_type: str = "news"
    filter_keywords: list[str] | None = None  # None = 不过滤

    @abstractmethod
    def fetch(self) -> list[RawItem]:
        """抓取并解析该源，返回标准化 RawItem 列表；失败抛 TrendingSourceError。"""

    # -------------------------------------------------- 子类公共工具 ----
    def _keep(self, item: RawItem) -> bool:
        """按 filter_keywords 决定是否保留该条目（标题 + 摘要命中即保留）。"""
        if not self.filter_keywords:
            return True
        return filter_ai_keywords(item.title, item.summary, self.filter_keywords)

    def _request(self, url: str, timeout: int = 20, headers: dict | None = None) -> requests.Response:
        """统一 GET 请求：超时 + 抛错语义收敛为 TrendingSourceError。"""
        try:
            resp = requests.get(
                url, timeout=timeout, headers=headers or DEFAULT_HEADERS
            )
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            raise TrendingSourceError(f"{self.source_id} 请求失败: {exc}") from exc

    def _http_get(self, url: str, timeout: int = 20, headers: dict | None = None) -> str:
        return self._request(url, timeout=timeout, headers=headers).text

    def _http_get_bytes(self, url: str, timeout: int = 20, headers: dict | None = None) -> bytes:
        return self._request(url, timeout=timeout, headers=headers).content

    def _http_get_json(self, url: str, timeout: int = 20, headers: dict | None = None) -> Any:
        resp = self._request(url, timeout=timeout, headers=headers)
        try:
            return resp.json()
        except ValueError as exc:
            raise TrendingSourceError(f"{self.source_id} 响应不是合法 JSON") from exc


class TrendingSourceRegistry:
    """热点源注册表：controller / collector / scheduler 通过 source_id 查找源。"""

    def __init__(self) -> None:
        self._sources: dict[str, TrendingSource] = {}

    def register(self, source: TrendingSource) -> None:
        if not source.source_id:
            raise TrendingSourceError("热点源缺少 source_id")
        self._sources[source.source_id] = source

    def get(self, source_id: str) -> TrendingSource:
        source = self._sources.get(source_id)
        if not source:
            raise TrendingSourceError(f"未知热点源: {source_id}")
        return source

    def list(self) -> list[TrendingSource]:
        return list(self._sources.values())


registry = TrendingSourceRegistry()
