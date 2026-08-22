"""主题向量表：与 hot_topics 一一对应，存主题「关注需求」的查询向量。

保存主题时若 interest_query 的 hash 变化，不在此处同步调用外部模型；由保存后的后台任务
或报告生成前的 ensure 操作补算（将行更新为 pending）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HotTopicEmbedding(Base):
    __tablename__ = "hot_topic_embeddings"

    topic_id: Mapped[int] = mapped_column(
        ForeignKey("hot_topics.id", ondelete="CASCADE"), primary_key=True
    )
    model_key: Mapped[str] = mapped_column(String(160))
    preprocess_version: Mapped[str] = mapped_column(String(32), default="query-v1")
    dimension: Mapped[int] = mapped_column(Integer)
    query_hash: Mapped[str] = mapped_column(String(64))
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(16), default="success")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
