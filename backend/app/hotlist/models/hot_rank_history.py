"""榜位时间线表。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class HotRankHistory(Base):
    """榜位时间线：每次抓取给每个在榜条目记一行。

    rank = 0 表示该批次脱榜（上批在榜、这批不在）。用 0 编码脱榜是从 TrendRadar 借的，
    好处是不用单独建「脱榜表」，前端把这条曲线画出来，掉到底就是脱榜。
    """

    __tablename__ = "hot_rank_history"
    __table_args__ = (Index("ix_hot_rank_item_time", "item_id", "crawl_time"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    crawl_time: Mapped[datetime] = mapped_column(DateTime)
