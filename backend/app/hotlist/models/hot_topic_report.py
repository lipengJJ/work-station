"""主题报告表。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HotTopicReport(Base):
    """一期报告：正文 + 条目快照 + 发布状态。

    item_ids + candidate_ids 两个快照都别省。前者用于三周后回查「当时据什么这么说」
    （底层条目可能已被清理任务删掉），后者是效果度量的分母（引用覆盖率）。
    """

    __tablename__ = "hot_topic_reports"
    __table_args__ = (
        UniqueConstraint("topic_id", "period_key"),   # 同期重跑覆盖，不产生重复
        Index("ix_hot_topic_reports_topic_time", "topic_id", "period_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(Integer, index=True)
    period_key: Mapped[str] = mapped_column(String(32))
    """'2026-W34'（周报）/ '2026-08-19'（日报）"""
    period_start: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    period_end: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    status: Mapped[str] = mapped_column(String(16), default="pending")
    """pending / running / success / failed"""
    content_md: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    # JSON 数组，3~5 条核心结论
    highlights: Mapped[str] = mapped_column(Text, default="[]")

    item_ids: Mapped[str] = mapped_column(Text, default="[]")
    """JSON：本期引用的 HotItem id"""
    candidate_ids: Mapped[str] = mapped_column(Text, default="[]")
    """JSON：本期进入分析的 HotItem id（算引用覆盖率用）"""
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    source_count: Mapped[int] = mapped_column(Integer, default=0)

    strategy: Mapped[str] = mapped_column(String(16), default="")
    skill_key: Mapped[str] = mapped_column(String(64), default="")
    template_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str] = mapped_column(String(64), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    ai_call_count: Mapped[int] = mapped_column(Integer, default=0)

    publish_status: Mapped[str] = mapped_column(String(16), default="")
    """'' / success / failed"""
    # JSON: {"json": "...", "html": "..."}
    publish_urls: Mapped[str] = mapped_column(Text, default="{}")
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=_utcnow
    )
