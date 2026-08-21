"""源分组请求/响应模型。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SourceGroupIn(BaseModel):
    """创建源分组。"""

    name: str = Field(..., min_length=1, max_length=64)
    description: str = ""
    color: str = ""
    sort_order: int = 0


class SourceGroupUpdateIn(BaseModel):
    """更新源分组：字段全部可选，只传要改的（配合 exclude_unset 使用）。"""

    name: str | None = Field(None, min_length=1, max_length=64)
    description: str | None = None
    color: str | None = None
    sort_order: int | None = None


class SourceGroupOut(BaseModel):
    """源分组出参：source_count（组内源数）由 controller 回填。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str = ""
    color: str = ""
    sort_order: int = 0
    is_builtin: bool = False
    source_count: int = 0
