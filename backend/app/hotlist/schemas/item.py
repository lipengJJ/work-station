"""热点条目请求/响应模型。"""
from __future__ import annotations

from datetime import datetime
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ItemOut(BaseModel):
    """热点条目出参。ranks_json / metrics 在 DB 里是 JSON 字符串，序列化时解析成对象
    （写法照抄旧 ai_trending schemas/trending.py::_parse_heat_meta）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: str
    title: str
    url: str = ""
    mobile_url: str = ""
    summary: str = ""
    stat_date: str
    rank: int = 0
    best_rank: int = 999
    ranks_json: list[int] = Field(default_factory=list)
    first_crawl_time: datetime | None = None
    last_crawl_time: datetime | None = None
    crawl_count: int = 1
    published_at: datetime | None = None
    metrics: dict = Field(default_factory=dict)
    weight: float = 0.0
    hit_rules: list[str] = Field(default_factory=list)
    """命中的频率词规则显示名（controller 批量查询后回填，不是 ORM 字段）。"""

    @field_validator("ranks_json", mode="before")
    @classmethod
    def _parse_ranks(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                return []
        return value or []

    @field_validator("metrics", mode="before")
    @classmethod
    def _parse_metrics(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                return {}
        return value or {}


class ItemPage(BaseModel):
    items: list[ItemOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class RankPointOut(BaseModel):
    """条目详情的榜位时间线上一个点。rank = 0 表示该批次脱榜。"""

    model_config = ConfigDict(from_attributes=True)

    rank: int
    crawl_time: datetime


class ItemDetailOut(BaseModel):
    item: ItemOut
    history: list[RankPointOut] = Field(default_factory=list)


class ItemFulltextOut(BaseModel):
    """条目全文（trafilatura 抽取的 Markdown，保留标题层级/图片/链接）。

    status：success（有全文，content 非空）/ skipped（robots 禁止或疑似付费墙）/
    failed（抓取失败或正文过短）。skipped/failed 时 content 为空，前端退化展示
    summary + 原文外链。
    """

    status: str
    content: str = ""
    char_count: int = 0
    error: str = ""
    fetched_at: datetime | None = None


class GroupSummaryOut(BaseModel):
    """数据源分组 AI 总结。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    group_filter: str = ""
    status: str = "running"
    content: str = ""
    error: str = ""
    item_count: int = 0
    model: str = ""
    created_at: datetime


class EmbeddingStatusOut(BaseModel):
    """文章语义向量索引进度：供榜单页展示补偿任务的完成情况。"""

    total: int = 0
    indexed: int = 0
    pending: int = 0
    failed: int = 0
    running: bool = False
    """是否有手动补算任务正在后台执行。"""
