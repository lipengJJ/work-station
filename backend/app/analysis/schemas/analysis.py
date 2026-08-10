from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class AnalysisOptionsIn(BaseModel):
    enable_search: bool = True
    thinking_enabled: Optional[bool] = None  # 不传时用系统配置里的默认值


class AnalysisCreateIn(BaseModel):
    skill_key: str = Field(..., min_length=1)
    template_key: Optional[str] = None
    model: Optional[str] = None  # 不传时用系统配置里的默认模型
    inputs: dict[str, Any] = Field(default_factory=dict)
    question: Optional[str] = Field(None, max_length=2000)  # 表单结构化输入之外的补充要求
    options: AnalysisOptionsIn = Field(default_factory=AnalysisOptionsIn)


class AnalysisRunOut(BaseModel):
    id: int
    request_id: str
    skill_key: str
    skill_version: str
    template_key: str | None
    provider: str
    model: str
    status: str
    input: dict[str, Any]
    output_text: str
    citations: list[dict[str, Any]]
    usage: dict[str, Any]
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None


class AnalysisRunDetailOut(AnalysisRunOut):
    system_snapshot: str
