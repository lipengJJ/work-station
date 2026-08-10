from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class XhsTaskExtra(Base):
    """
    xhs 采集任务的扩展信息，和 Task 表一对一（task_id 既是主键也是外键）。

    Task 表是跨模块通用表，字段留了 params/result_summary 就够用；但 xhs 采集需要的
    进度（阶段 + 当前/总数）和预览用的完整笔记/评论 JSON 明显不适合塞进那个通用的一句话
    摘要字段，所以单独开一张表，不改动 Task 本身的结构。
    """

    __tablename__ = "xhs_task_extra"

    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    phase: Mapped[str] = mapped_column(String(32), default="queued")
    progress_current: Mapped[int] = mapped_column(default=0)
    progress_total: Mapped[int] = mapped_column(default=0)
    note_count: Mapped[int] = mapped_column(default=0)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    comments_json: Mapped[str | None] = mapped_column(Text, nullable=True)
