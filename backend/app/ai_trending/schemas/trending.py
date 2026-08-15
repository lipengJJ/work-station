from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TrendingItemOut(BaseModel):
    """热点条目出参。tags / heat_meta 在 DB 里是 JSON 字符串，序列化时解析成对象。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    title: str
    url: str
    summary: str = ""
    heat_score: float = 0.0
    category: str = "news"
    tags: list[str] = Field(default_factory=list)
    heat_meta: dict = Field(default_factory=dict)
    published_at: datetime | None = None
    fetched_at: datetime | None = None
    created_at: datetime | None = None

    @field_validator("tags", mode="before")
    @classmethod
    def _parse_tags(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                return []
        return value or []

    @field_validator("heat_meta", mode="before")
    @classmethod
    def _parse_heat_meta(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                return {}
        return value or {}


class TrendingItemPage(BaseModel):
    """热点条目分页结果。"""

    items: list[TrendingItemOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class SourceStatusOut(BaseModel):
    """来源健康状态出参。"""

    model_config = ConfigDict(from_attributes=True)

    source_id: str
    source_name: str = ""
    category_type: str = "news"
    last_fetched_at: datetime | None = None
    last_status: str = ""
    last_error: str = ""
    consecutive_failures: int = 0
    fail_count: int = 0
    last_success_at: datetime | None = None
    total_fetched: int = 0


class RefreshOut(BaseModel):
    """手动刷新出参：接口只负责触发，实际抓取在 daemon 线程异步执行。"""

    triggered: bool = True
    message: str = ""
