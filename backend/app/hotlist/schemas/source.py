"""源请求/响应模型。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SourceOut(BaseModel):
    """源 + 健康状态，一次性返回（两者在表里本来就是 1:1）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str = ""
    source_kind: str = "hotlist"
    adapter: str = ""
    expected_domain: str = ""
    decay_half_life_hours: float = 0.0
    cron_expr: str = "*/30 * * * *"
    enabled: bool = True
    sort_order: int = 0
    group_id: int | None = None
    """所属分组（hot_source_groups.id）。NULL = 未分组。"""

    last_fetched_at: datetime | None = None
    last_status: str = ""
    last_error: str = ""
    consecutive_failures: int = 0
    fail_count: int = 0
    last_success_at: datetime | None = None
    total_fetched: int = 0


class SourceIn(BaseModel):
    """更新已有源：字段全部可选，只传要改的（配合 exclude_unset 使用）。"""

    name: str | None = None
    enabled: bool | None = None
    cron_expr: str | None = None
    expected_domain: str | None = None
    decay_half_life_hours: float | None = None
    sort_order: int | None = None


class SourceCreateIn(BaseModel):
    """新建自定义源，主要给 RSS 用。"""

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    adapter: str = Field(min_length=1, max_length=32)
    adapter_params: dict = Field(default_factory=dict)
    source_kind: str = "hotlist"
    expected_domain: str = ""
    decay_half_life_hours: float = 0.0
    cron_expr: str = "*/30 * * * *"
    enabled: bool = True
    sort_order: int = 0
    group_id: int | None = None


class SourceBatchIn(BaseModel):
    """批量操作：移组与启停可同时给（先移组再启停），也可只给其一。
    group_id 显式传 null = 移出分组（用 exclude_unset 区分「没传」与「传 null」）。"""

    source_ids: list[str] = Field(default_factory=list)
    group_id: int | None = None
    enabled: bool | None = None


class SourceImportOpmlIn(BaseModel):
    """OPML 批量导入到分组：content（文本）与 opml_url（远端）二选一，content 优先。"""

    content: str = ""
    opml_url: str = ""
    group_id: int | None = None
