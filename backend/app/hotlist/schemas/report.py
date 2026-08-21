"""主题报告请求/响应模型。"""
from __future__ import annotations

from datetime import datetime
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _parse_json_list(value: object) -> list[int]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return []
    return []


def _parse_json_obj(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            data = json.loads(value)
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


class ReportOut(BaseModel):
    """报告列表行 / 详情。JSON 字符串字段统一解析成对象。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    topic_id: int
    period_key: str
    period_start: datetime | None = None
    period_end: datetime | None = None
    status: str = ""
    summary: str = ""
    content_md: str = ""
    highlights: list[str] = Field(default_factory=list)
    item_ids: list[int] = Field(default_factory=list)
    candidate_ids: list[int] = Field(default_factory=list)
    item_count: int = 0
    source_count: int = 0
    strategy: str = ""
    skill_key: str = ""
    template_key: str | None = None
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    ai_call_count: int = 0
    publish_status: str = ""
    publish_urls: dict = Field(default_factory=dict)
    published_at: datetime | None = None
    error: str = ""
    created_at: datetime | None = None

    @field_validator("highlights", mode="before")
    @classmethod
    def _parse_highlights(cls, v: object) -> object:
        if isinstance(v, str):
            try:
                data = json.loads(v)
                return data if isinstance(data, list) else []
            except (ValueError, TypeError):
                return []
        return v or []

    @field_validator("item_ids", "candidate_ids", mode="before")
    @classmethod
    def _parse_ids(cls, v: object) -> object:
        return _parse_json_list(v)

    @field_validator("publish_urls", mode="before")
    @classmethod
    def _parse_urls(cls, v: object) -> object:
        return _parse_json_obj(v)


class ReportPage(BaseModel):
    reports: list[ReportOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class GenerateIn(BaseModel):
    """手动生成报告：可选指定时间范围与策略（A/B 用）。"""

    period_key: str = ""
    """留空自动按 digest_period 计算本期 key（周报 = ISO 周，日报 = 当天）。"""
    strategy: str = ""
    """留空用主题配置；可指定 simple/two_stage/funnel 做策略 A/B。"""
    max_items: int | None = Field(None, ge=1, le=5000)


class ReportItemRefOut(BaseModel):
    """报告引用的条目快照（带 source 名，方便前端渲染原文链接）。"""

    id: int
    title: str
    url: str = ""
    source_id: str = ""
    source_name: str = ""
    weight: float = 0.0
    published_at: datetime | None = None


class ReportDetailOut(ReportOut):
    topic_name: str = ""
    topic_slug: str = ""
    items: list[ReportItemRefOut] = Field(default_factory=list)
    """本期引用的条目明细（按 id 从 hot_items 现查；被清理任务删掉的条目跳过）。"""
    coverage: float = 0.0
    """引用覆盖率 = len(item_ids) / len(candidate_ids)，0~1；candidate 为空时为 0。"""
    prev_item_ids: list[int] = Field(default_factory=list)
    """上一期引用的条目 id（用于在 UI 上标"新出现/持续/已消退"）。"""


class CandidateOut(BaseModel):
    """漏检抽查：一期进入分析但未被引用的条目。"""

    id: int
    title: str
    url: str = ""
    source_id: str = ""
    source_name: str = ""
    weight: float = 0.0
    published_at: datetime | None = None
