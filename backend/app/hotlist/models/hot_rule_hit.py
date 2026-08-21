"""规则命中记录表。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class HotRuleHit(Base):
    """规则命中记录（原 AiTrendingTopicHit）。(rule_id, item_id) 唯一，
    保证同一条目对同一规则只记一次命中，也是推送去重的依据。"""

    __tablename__ = "hot_rule_hits"
    __table_args__ = (UniqueConstraint("rule_id", "item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(Integer, index=True)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    matched_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
