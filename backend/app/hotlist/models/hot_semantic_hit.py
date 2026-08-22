"""语义命中表：文章向量成功写入后，与该主题查询向量做相似度计算，超过主题阈值即写入。

push_service 只消费本表，不再理解旧关键词规则 / rule_id /「无规则等于全部命中」等语义。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HotSemanticHit(Base):
    __tablename__ = "hot_semantic_hits"
    __table_args__ = (
        UniqueConstraint("topic_id", "item_id", name="uq_semantic_hit_topic_item"),
        Index("ix_semantic_hits_notify", "topic_id", "notified", "matched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("hot_topics.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("hot_items.id", ondelete="CASCADE"), index=True
    )
    semantic_score: Mapped[float] = mapped_column(Float)
    model_key: Mapped[str] = mapped_column(String(160))
    query_hash: Mapped[str] = mapped_column(String(64))
    matched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
