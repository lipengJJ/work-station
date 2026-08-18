"""热点源抓取器抽象基类 + RawEntry + 注册表。

与旧 ai_trending 的 TrendingSource / RawItem 的关键差别：RawEntry 有 rank（榜位），
没有 heat_score——打分统一由 services/ranking.py 按榜位算，adapter 不参与打分。
这样新增一个源只需要「请求 + 解析 + 按返回顺序排位」，不用再拍一个 MAX_REF 参考上限。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

import requests
from pydantic import BaseModel, Field

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; WorkBench-Hotlist/1.0; +https://github.com)",
}


class RawEntry(BaseModel):
    """adapter 产出的标准化条目。不落库，crawl_service 负责入库。"""

    rank: int = 0  # 1 起；adapter 按返回顺序 enumerate 填
    title: str = ""
    url: str = ""
    mobile_url: str = ""
    summary: str = ""
    published_at: datetime | None = None
    metrics: dict = Field(default_factory=dict)  # points / stars_today… 仅展示


class HotSourceAdapterError(Exception):
    """抓取/解析失败，message 可直接展示给用户。"""


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

    def _request(self, url: str, timeout: int = 20, headers: dict | None = None) -> requests.Response:
        """统一 GET：超时 + 异常语义收敛为 HotSourceAdapterError。"""
        try:
            resp = requests.get(url, timeout=timeout, headers=headers or DEFAULT_HEADERS)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            raise HotSourceAdapterError(f"{self.adapter_key} 请求失败: {exc}") from exc

    def _get_json(self, url: str, timeout: int = 20, headers: dict | None = None):
        resp = self._request(url, timeout=timeout, headers=headers)
        try:
            return resp.json()
        except ValueError as exc:
            raise HotSourceAdapterError(f"{self.adapter_key} 响应不是合法 JSON") from exc


registry: dict[str, HotSourceAdapter] = {}


def register(adapter: HotSourceAdapter) -> None:
    if not adapter.adapter_key:
        raise HotSourceAdapterError("adapter 缺少 adapter_key")
    registry[adapter.adapter_key] = adapter


def get(key: str) -> HotSourceAdapter:
    adapter = registry.get(key)
    if not adapter:
        raise HotSourceAdapterError(f"未知 adapter: {key}")
    return adapter
