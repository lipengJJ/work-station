"""主题与源关联表。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HotTopicSource(Base):
    """主题与源的关联（多对多）。

    启用状态记在关联上，不记在源上：AI 主题里开着 Hacker News、财经主题里关着，
    互不影响；而 HN 全局只抓一次。
    """

    __tablename__ = "hot_topic_sources"
    __table_args__ = (UniqueConstraint("topic_id", "source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(Integer, index=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    imported_from: Mapped[str] = mapped_column(String(128), default="")
    """'opml:cn-ai-tools.opml' / 'manual' / 'builtin'，用于批量管理与重导。"""
    added_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
