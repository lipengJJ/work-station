"""热点源抓取器抽象基类 + RawEntry + 注册表。

与旧 ai_trending 的 TrendingSource / RawItem 的关键差别：RawEntry 有 rank（榜位），
没有 heat_score——打分统一由 services/ranking.py 按榜位算，adapter 不参与打分。
这样新增一个源只需要「请求 + 解析 + 按返回顺序排位」，不用再拍一个 MAX_REF 参考上限。
"""
from __future__ import annotations

import logging
import os
import socket
import threading

from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, Field
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# 真实浏览器 UA。自报家门的 bot UA（原来的 WorkBench-Hotlist/1.0）会被 Cloudflare
# 前置的站点直接 403，而 RSS 抓取本来就是公开内容，没必要为此丢一半的源。
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "application/rss+xml, application/atom+xml, application/xml;q=0.9, "
        "text/xml;q=0.9, */*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 连接超时 / 读取超时分离。原来 timeout=20 两者共用：一个连不上的 host 要白等 20 秒，
# 而 80 个源串行跑就是 20 多分钟。连接 5 秒够判断可达性，读取放宽到调用方给的值。
DEFAULT_CONNECT_TIMEOUT = 5.0

# 连接层重试（DNS / 连接 / 5xx）。一次本机 DNS 抖动就把整批源判失败，是这套抓取
# 最脆的地方；HTTP 4xx 不重试——那是对端的真实答复。
_RETRY = Retry(
    total=2,
    connect=2,
    read=1,
    status=2,
    backoff_factor=0.8,
    status_forcelist=(502, 503, 504),
    allowed_methods=frozenset({"GET", "HEAD"}),
    raise_on_status=False,
)

_session: requests.Session | None = None
_session_lock = threading.Lock()


def _get_session() -> requests.Session:
    """模块级共享 Session：连接池复用 + 统一挂重试策略。
    原来每个源各起一次裸 requests.get()，80 个源就是 80 次全新握手。"""
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                sess = requests.Session()
                adapter = HTTPAdapter(
                    max_retries=_RETRY, pool_connections=10, pool_maxsize=20
                )
                sess.mount("http://", adapter)
                sess.mount("https://", adapter)
                _session = sess
    return _session


def _proxies() -> dict | None:
    """代理配置。WORKBENCH_HOTLIST_PROXY（形如 http://127.0.0.1:7890）同时用于
    http/https；没配返回 None —— requests 自己会读 HTTP_PROXY / HTTPS_PROXY。"""
    proxy = (os.getenv("WORKBENCH_HOTLIST_PROXY") or "").strip()
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


# ------------------------------------------------------------ 错误分类 ----
# 瞬时类：本机网络或上游抖动，不该判定源失效（见 hot_source.last_error_kind）
TRANSIENT_KINDS = frozenset({
    "dns_error", "connect_timeout", "read_timeout",
    "connection_error", "upstream_5xx", "upstream_down",
})
# 触发上游 host 熔断的错误类型：只有「整个 host 不可达」才算，
# 403/404/parse_error 是单个源的问题，不能拖累同 host 的其他源。
HOST_TRIP_KINDS = frozenset({
    "dns_error", "connect_timeout", "connection_error", "upstream_5xx",
})

_HTTP_KIND_MAP = {
    403: "http_403", 404: "http_404", 410: "http_410", 429: "http_429",
}

_KIND_LABELS = {
    "dns_error": "域名解析失败（本机 DNS 查不到该域名，可能是 DNS 抖动或需要代理）",
    "connect_timeout": "连接超时（端口不通，可能被墙或站点下线）",
    "read_timeout": "读取超时",
    "connection_error": "连接失败",
    "upstream_5xx": "上游服务异常",
    "upstream_down": "上游整体不可用，本轮已跳过",
    "http_403": "被拒绝访问 403（可能需要代理）",
    "http_404": "地址失效 404",
    "http_410": "地址失效 410",
    "http_429": "被限流 429（该降低抓取频率）",
    "parse_error": "返回内容不是合法 RSS/Atom",
    "empty_feed": "feed 里没有任何条目",
    "domain_unsafe": "域名安全校验未通过",
    "proxy_error": "代理不可用",
    "ssl_error": "SSL 握手失败",
}


def kind_label(kind: str) -> str:
    """错误类型 → 人话。前端「状态」列直接用得上。"""
    return _KIND_LABELS.get(kind, kind or "未知错误")


def _is_dns_error(exc: BaseException) -> bool:
    """urllib3 的 NameResolutionError 被包在 requests.ConnectionError 里，
    异常链上找 socket.gaierror，找不到再退回字符串匹配。"""
    cur: BaseException | None = exc
    seen = 0
    while cur is not None and seen < 10:
        if isinstance(cur, socket.gaierror):
            return True
        cur = cur.__cause__ or cur.__context__
        seen += 1
    text = str(exc)
    return "NameResolutionError" in text or "Failed to resolve" in text


def classify(exc: Exception) -> str:
    """requests 异常 → last_error_kind。"""
    if isinstance(exc, requests.exceptions.HTTPError):
        code = exc.response.status_code if exc.response is not None else 0
        if code in _HTTP_KIND_MAP:
            return _HTTP_KIND_MAP[code]
        return "upstream_5xx" if 500 <= code < 600 else "connection_error"
    if isinstance(exc, requests.exceptions.ProxyError):
        return "proxy_error"
    if isinstance(exc, requests.exceptions.SSLError):
        return "ssl_error"
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "connect_timeout"
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return "read_timeout"
    if isinstance(exc, requests.exceptions.Timeout):
        return "read_timeout"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "dns_error" if _is_dns_error(exc) else "connection_error"
    return "connection_error"


class RawEntry(BaseModel):
    """adapter 产出的标准化条目。不落库，crawl_service 负责入库。"""

    rank: int = 0  # 1 起；adapter 按返回顺序 enumerate 填
    title: str = ""
    url: str = ""
    mobile_url: str = ""
    summary: str = ""
    published_at: datetime | None = None
    metrics: dict = Field(default_factory=dict)  # points / stars_today… 仅展示
    full_content: str = ""
    """feed 自带的正文纯文本（如 RSS content:encoded）。非空时 crawl_service 会顺带
    写入 hot_item_contents 缓存——L2 全文放大阶段「先看 RSS 里有没有」就不用再发请求。"""


class HotSourceAdapterError(Exception):
    """抓取/解析失败，message 可直接展示给用户。

    kind = 失败类型（见 HotSource.last_error_kind）。crawl_service 据此决定
    这次失败算瞬时还是永久，以及要不要熔断整个上游 host。
    """

    def __init__(self, message: str, kind: str = ""):
        super().__init__(message)
        self.kind = kind


class HotSourceAdapter(ABC):
    """抓取器抽象。一个 adapter 可服务多行 HotSource（靠 params 区分）。

    新增一个源的三种情况：
      1. 已有 adapter 能覆盖（如再加一个 RSS 源）→ 前端加一行，零代码
      2. 新协议 → 写一个 adapter 子类 + 注册一行 + seed 一行源
      3. NewsNow 已支持的平台 → seed 一行源即可
    """

    adapter_key: str = ""

    @abstractmethod
    def fetch(self, params: dict) -> list[RawEntry]:
        """返回有序列表（rank 已填）。失败抛 HotSourceAdapterError。"""

    def _request(
        self, url: str, timeout: int = 20, headers: dict | None = None
    ) -> requests.Response:
        """统一 GET：分离超时 + 连接层重试 + 异常收敛为带 kind 的 HotSourceAdapterError。"""
        try:
            resp = _get_session().get(
                url,
                timeout=(DEFAULT_CONNECT_TIMEOUT, float(timeout)),
                headers=headers or DEFAULT_HEADERS,
                proxies=_proxies(),
            )
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            kind = classify(exc)
            detail = kind_label(kind)
            if kind in {"connection_error", "proxy_error", "ssl_error"}:
                detail = f"{detail}: {str(exc)[:200]}"
            logger.info("%s 抓取 %s 失败（%s）", self.adapter_key, url, kind)
            raise HotSourceAdapterError(
                f"{self.adapter_key} 请求失败: {detail}", kind=kind
            ) from exc

    def _get_json(
        self, url: str, timeout: int = 20, headers: dict | None = None
    ):
        resp = self._request(url, timeout=timeout, headers=headers)
        try:
            return resp.json()
        except ValueError as exc:
            raise HotSourceAdapterError(
                f"{self.adapter_key} 响应不是合法 JSON", kind="parse_error"
            ) from exc


registry: dict[str, HotSourceAdapter] = {}


def register(adapter: HotSourceAdapter) -> None:
    if not adapter.adapter_key:
        raise HotSourceAdapterError("adapter 缺少 adapter_key", kind="parse_error")
    registry[adapter.adapter_key] = adapter


def get(key: str) -> HotSourceAdapter:
    adapter = registry.get(key)
    if not adapter:
        raise HotSourceAdapterError(f"未知 adapter: {key}")
    return adapter
