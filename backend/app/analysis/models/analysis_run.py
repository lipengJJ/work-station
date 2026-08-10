from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AnalysisRun(Base):
    """
    一次"选 Skill + 模板 + 填表单"的执行记录（设计文档 6.4 节）。skill_version_id 在创建时
    就固定下来，Skill 后续升级版本不影响这条记录的 system_snapshot 和结果的可解释性。
    context_refs_json 是给以后阶段 5（小红书/股票业务数据引用）预留的字段，第一版本
    Skill Runtime 还没有业务数据源接入，暂时固定写 "[]"。
    """

    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"), index=True)
    skill_version_id: Mapped[int] = mapped_column(ForeignKey("skill_versions.id"))
    template_id: Mapped[int | None] = mapped_column(ForeignKey("skill_templates.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), default="gemini")
    model: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="running")  # running/completed/failed
    input_json: Mapped[str] = mapped_column(Text)
    context_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    system_snapshot: Mapped[str] = mapped_column(Text)
    output_text: Mapped[str] = mapped_column(Text, default="")
    citations_json: Mapped[str] = mapped_column(Text, default="[]")
    usage_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
