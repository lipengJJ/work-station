from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StorageSnapshot(Base):
    """
    存储使用快照：首页"存储趋势"折线图的数据源。
    由 GET /api/home/storage 惰性采样（距上次采样 ≥ 5 分钟才插一条），
    保留最近 24 小时（约 288 条），观察数据库/素材占用的增长趋势。
    """

    __tablename__ = "storage_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    db_size: Mapped[int] = mapped_column(BigInteger, default=0)
    storage_size: Mapped[int] = mapped_column(BigInteger, default=0)
    note_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
