"""NewsNow 聚合 API adapter：一个类驱动全部中文热榜平台（微博/知乎/抖音/头条…）。

移植自 TrendRadar (https://github.com/sansan0/TrendRadar) crawler/fetcher.py，
改动：
  - print → loguru；
  - 批量编排（原 crawl_websites）移到 crawl_service.py，本文件只负责单个源的请求 + 解析；
  - 域名安全校验独立到 services/security.py，供其余 adapter 复用；
  - api_url 从 ApiConfig 读（key: hotlist_newsnow_api_url），留空用公共实例默认值。
"""
from __future__ import annotations

import random
import time

from loguru import logger

from app.common.models import ApiConfig
from app.core.database import SessionLocal
from app.hotlist.services.adapters.base import (
    HotSourceAdapter,
    HotSourceAdapterError,
    RawEntry,
    register,
)

DEFAULT_API_URL = "https://newsnow.busiyi.world/api/s"
API_URL_CONFIG_NAME = "hotlist_newsnow_api_url"

# 初始请求失败后重试 2 次，退避 = 基础值 + 随机抖动 + 按次数递增
RETRY_BASE_DELAYS = (3, 5)


class NewsNowAdapter(HotSourceAdapter):
    adapter_key = "newsnow"

    def _api_url(self) -> str:
        db = SessionLocal()
        try:
            row = db.query(ApiConfig).filter(ApiConfig.name == API_URL_CONFIG_NAME).first()
            value = (row.value.strip() if row and row.value else "")
            return value or DEFAULT_API_URL
        finally:
            db.close()

    def _get_json_with_retry(self, url: str) -> dict:
        last_error = ""
        for attempt in range(len(RETRY_BASE_DELAYS) + 1):
            try:
                return self._get_json(url, timeout=20)
            except HotSourceAdapterError as exc:
                last_error = str(exc)
            if attempt < len(RETRY_BASE_DELAYS):
                delay = RETRY_BASE_DELAYS[attempt] + random.uniform(0, 2) + attempt * 2
                logger.warning(
                    f"newsnow 第 {attempt + 1} 次请求失败: {last_error}，{delay:.1f}s 后重试"
                )
                time.sleep(delay)
        raise HotSourceAdapterError(f"newsnow 连续请求失败: {last_error}")

    def fetch(self, params: dict) -> list[RawEntry]:
        platform = params.get("platform", "")
        if not platform:
            raise HotSourceAdapterError("newsnow adapter 缺少 platform 参数")
        url = f"{self._api_url()}?id={platform}&latest"
        data = self._get_json_with_retry(url)
        if data.get("status") not in ("success", "cache"):
            raise HotSourceAdapterError(f"响应状态异常: {data.get('status')}")

        entries: list[RawEntry] = []
        for idx, item in enumerate(data.get("items", []), 1):
            title = item.get("title")
            # 跳过无效标题（None / float / 空串）——原实现踩过这个坑，保留
            if title is None or isinstance(title, float) or not str(title).strip():
                continue
            entries.append(
                RawEntry(
                    rank=idx,
                    title=str(title).strip(),
                    url=item.get("url") or "",
                    mobile_url=item.get("mobileUrl") or "",
                )
            )
        return entries


register(NewsNowAdapter())
