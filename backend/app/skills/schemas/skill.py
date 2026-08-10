from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SkillSummaryOut(BaseModel):
    skill_key: str
    display_name: str
    description: str
    category: str | None
    source_type: str
    enabled: bool
    risk_level: str
    version: str | None
    template_count: int
    created_at: datetime
    updated_at: datetime


class SkillTemplateOut(BaseModel):
    template_key: str
    name: str
    description: str | None
    prompt_path: str | None
    output_template_path: str | None
    input_schema: dict[str, Any] | None = None


class SkillRuntimeOut(BaseModel):
    preferred_provider: str | None = None
    recommended_model: str | None = None
    tools: dict[str, bool] = {}


class SkillValidationOut(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]
    risk_level: str
    total_size: int
    file_count: int


class SkillDetailOut(SkillSummaryOut):
    instruction: str | None = None
    default_prompt: str | None = None
    tags: list[str] = []
    runtime: SkillRuntimeOut | None = None
    validation: SkillValidationOut | None = None
    templates: list[SkillTemplateOut] = []


class SkillVersionOut(BaseModel):
    id: int
    version: str
    content_hash: str
    is_current: bool
    created_at: datetime


class FileNodeOut(BaseModel):
    name: str
    path: str
    type: str
    size: int | None = None
    children: list[FileNodeOut] = []


class FileContentOut(BaseModel):
    path: str
    content: str
    truncated: bool


class FileContentUpdateIn(BaseModel):
    path: str
    content: str


class FileSaveOut(BaseModel):
    path: str
    saved: bool
    manifest_error: str | None = None
    validation: SkillValidationOut | None = None


FileNodeOut.model_rebuild()
