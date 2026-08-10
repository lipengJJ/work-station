from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TokenStatus(BaseModel):
    has_token: bool
    preview: str | None
    updated_at: str | None


class ManualTokenIn(BaseModel):
    cookies: str = Field(..., min_length=10)


class PhoneSendIn(BaseModel):
    phone: str
    zone: str = "86"


class PhoneVerifyIn(BaseModel):
    phone: str
    code: str
    zone: str = "86"


class BatchDeleteNotesIn(BaseModel):
    note_ids: list[str] = Field(..., min_length=1)


class CollectTaskIn(BaseModel):
    keyword: str = Field(..., min_length=1)
    require_num: int = Field(50, ge=1, le=1000)
    sort_type_choice: int = 0
    note_type: int = 0
    note_time: int = 0
    note_range: int = 0
    save_choice: str = "excel"
    fetch_comments: bool = False
    max_comments_per_note: int | None = None
    comment_interval_seconds: float | None = None


class IncrementalCollectIn(BaseModel):
    increment_count: int = Field(50, ge=1, le=500)


class NoteAnalysisCreateIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    note_ids: list[str] | None = None  # 不传 = 用项目里全部笔记
    template: str | None = None  # 不传 = 用默认模板（general）；skill_key 有值时忽略这个字段
    skill_key: str | None = None  # 传了就走通用 Skill Runtime，笔记作为业务上下文注入
    skill_template_key: str | None = None
    enable_search: bool = False  # 只在 skill_key 有值时生效，默认关闭避免意外触发联网工具调用


class NoteAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    question: str
    status: str
    result: str | None
    error: str | None
    model: str
    template: str | None
    feedback: str | None
    created_at: datetime


class AnalysisProjectCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)


class RenameProjectIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)


class SetFeedbackIn(BaseModel):
    feedback: str | None = Field(None, pattern="^(up|down)$")


class AddProjectNotesIn(BaseModel):
    task_id: int
    note_ids: list[str] = Field(..., min_length=1)


class SaveReportIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    note_ids: list[str] = Field(..., min_length=1)


class SaveCombinedReportIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    note_ids: list[str] = Field(..., min_length=1)
    # 多轮对话不是每轮都要存进报告，让调用方明确指定要包含哪几轮
    analysis_ids: list[int] = Field(..., min_length=1)


class AppendReportIn(BaseModel):
    note_ids: list[str] = Field(..., min_length=1)
    analysis_ids: list[int] = Field(..., min_length=1)


class TrackingTaskIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    keyword: str = Field(..., min_length=1)
    require_num: int = Field(50, ge=1, le=1000)
    sort_type_choice: int = 0
    note_type: int = 0
    note_time: int = 0
    note_range: int = 0
    must_include: list[str] = Field(default_factory=list)
    must_exclude: list[str] = Field(default_factory=list)
    interval_minutes: int = Field(60, ge=5, le=10080)
    enabled: bool = True
