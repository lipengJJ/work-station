from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class HotCrawlRecord(Base):
    """一次抓取批次。crawl_time 是这一批的逻辑时间戳，同批次所有条目共用同一个值——
    「最新批次」「上一批次」这些判断全靠它，不能用各条目自己的写入时间。"""

    __tablename__ = "hot_crawl_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    crawl_time: Mapped[datetime] = mapped_column(DateTime, unique=True, index=True)
    stat_date: Mapped[str] = mapped_column(String(10), index=True)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    trigger: Mapped[str] = mapped_column(String(16), default="cron")  # cron / manual
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class HotCrawlSourceStatus(Base):
    """批次内每个源的成败明细（排查「那一批为什么少了微博」用）。"""

    __tablename__ = "hot_crawl_source_status"
    __table_args__ = (Index("ix_hot_crawl_status_record", "crawl_record_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    crawl_record_id: Mapped[int] = mapped_column(Integer, index=True)
    source_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="success")  # success / failed
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
