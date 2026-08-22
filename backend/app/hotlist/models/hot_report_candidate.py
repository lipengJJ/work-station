"""报告召回快照：记录每篇候选文章在本期报告中的各项分数与入选状态。

解决三个问题：解释某篇文章为什么入选；模型或需求变化后仍能复现历史报告；
为后续阈值调优和人工反馈提供数据。
"""
from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class HotReportCandidate(Base):
    __tablename__ = "hot_report_candidates"

    report_id: Mapped[int] = mapped_column(
        ForeignKey("hot_topic_reports.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("hot_items.id", ondelete="CASCADE"), primary_key=True
    )
    semantic_score: Mapped[float] = mapped_column(Float)
    hot_score: Mapped[float] = mapped_column(Float)
    freshness_score: Mapped[float] = mapped_column(Float)
    final_score: Mapped[float] = mapped_column(Float)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    rank_no: Mapped[int] = mapped_column(Integer, default=0)
    model_key: Mapped[str] = mapped_column(String(160), default="")
    query_hash: Mapped[str] = mapped_column(String(64), default="")
