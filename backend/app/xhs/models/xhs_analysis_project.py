from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class XhsAnalysisProject(Base):
    """
    AI 分析项目：用户自己起的一个分析主题（比如"普吉岛分析"），笔记从任意采集任务里挑进来，
    不限于某一次采集——项目和笔记是多对多关系，靠 XhsAnalysisProjectNote 关联。
    """

    __tablename__ = "xhs_analysis_projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class XhsAnalysisProjectNote(Base):
    """
    项目 <-> 笔记的关联：笔记内容本身还是没有独立表，这里只存"引用"（笔记来自哪个采集任务 +
    笔记 id），展示/分析时回源读 XhsTaskExtra.result_json。移出项目只删这行关联，不影响原始
    采集任务的数据。
    """

    __tablename__ = "xhs_analysis_project_notes"
    __table_args__ = (UniqueConstraint("project_id", "note_id", name="uq_project_note"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("xhs_analysis_projects.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    note_id: Mapped[str] = mapped_column(String(64), index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
