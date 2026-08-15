from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AiTrendingTopicHit(Base):
    """主题命中记录：主题维度去重（Unique(topic_id, item_id)），只引用不复制条目数据。

    - item_id 引用 ai_trending_items.id（全局热点池），主题详情通过 join hits+items 查询；
    - matched P0 恒 True（预留过滤语义）；first_seen_at 是详情「最新」排序键；
    - 删除主题 / 清理 items 时必须显式删 hits（SQLite 外键默认不强制，不依赖 DB 级 CASCADE）。
    """

    __tablename__ = "ai_trending_topic_hit"
    __table_args__ = (
        UniqueConstraint("topic_id", "item_id", name="uq_ai_trending_topic_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(
        ForeignKey("ai_trending_topic.id"), index=True
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("ai_trending_items.id"), index=True
    )
    matched: Mapped[bool] = mapped_column(Boolean, default=True)  # P0 恒 True
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
