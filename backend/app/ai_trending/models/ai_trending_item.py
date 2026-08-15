from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AiTrendingItem(Base):
    """AI 开发热点条目。

    跨源（HN / GitHub / arXiv / HF / InfoQ / 36氪）统一入库的一张表，source 字段区分来源；
    url_hash（归一化 URL 的 MD5）是去重键，跨源同 URL 只保留热度最高的一条。

    tags / heat_meta 以 JSON 字符串落库（json.dumps ensure_ascii=False），读取时 json.loads。
    """

    __tablename__ = "ai_trending_items"
    __table_args__ = (
        # 来源筛选 + 时间排序高频路径
        Index("ix_ai_trending_items_source_published_at", "source", "published_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    url: Mapped[str] = mapped_column(String(1024), default="")
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    heat_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    category: Mapped[str] = mapped_column(String(16), default="news", index=True)
    tags: Mapped[str] = mapped_column(String(255), default="[]")  # JSON 数组
    heat_meta: Mapped[str] = mapped_column(Text, default="{}")  # JSON 字典
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
