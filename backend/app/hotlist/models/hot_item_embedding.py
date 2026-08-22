"""文章向量表：与 hot_items 一一对应，存当前生效的标题摘要向量。

SQLite 第一版用 little-endian float32 BLOB（numpy frombuffer 读取），写入前做 L2 归一化，
召回时矩阵点积即余弦相似度。每篇文章只保存当前生效向量；模型或预处理版本变化时原位覆盖，
不维护多版本向量。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HotItemEmbedding(Base):
    __tablename__ = "hot_item_embeddings"
    __table_args__ = (
        Index("ix_hot_item_embeddings_status", "status", "updated_at"),
    )

    item_id: Mapped[int] = mapped_column(
        ForeignKey("hot_items.id", ondelete="CASCADE"), primary_key=True
    )
    model_key: Mapped[str] = mapped_column(String(160))
    preprocess_version: Mapped[str] = mapped_column(String(32), default="item-v1")
    dimension: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(16), default="success")
    error: Mapped[str] = mapped_column(Text, default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
