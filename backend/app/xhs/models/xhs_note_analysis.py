from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class XhsNoteAnalysis(Base):
    """
    针对某个 AI 分析项目（XhsAnalysisProject）当前选中的笔记做的一次分析：笔记内容本身不
    重复存一份，分析时现读 XhsTaskExtra.result_json（同预览接口），这张表只记录"问的问题 +
    分析结论"这条历史。一个分析项目可以有多条分析记录。
    """

    __tablename__ = "xhs_note_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("xhs_analysis_projects.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running/success/failed
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(64))
    template: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 用的哪个分析模板，仅展示
    feedback: Mapped[str | None] = mapped_column(String(8), nullable=True)  # up/down/None
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
