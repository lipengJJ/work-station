from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class XhsTrackingHit(Base):
    """
    追踪任务扫描到的笔记去重记录：每个 (tracking_task_id, note_id) 只记一行，无论有没有
    命中过滤条件——没命中的行只是"这篇笔记见过了、下次扫描跳过"的占位，只有 matched=True
    才会存完整笔记内容（note_json）给用户看。
    """

    __tablename__ = "xhs_tracking_hits"
    __table_args__ = (UniqueConstraint("tracking_task_id", "note_id", name="uq_tracking_task_note"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tracking_task_id: Mapped[int] = mapped_column(ForeignKey("xhs_tracking_tasks.id"), index=True)
    note_id: Mapped[str] = mapped_column(String(64), index=True)
    matched: Mapped[bool] = mapped_column(Boolean, default=False)
    note_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- AI 预处理 + 智能筛选结果（阶段 2/3） ----
    ai_process_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/success/failed
    ai_structured_data: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 结构化字段
    ai_is_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ai_match_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)  # 模型原始返回（排查解析失败）

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
