from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AiTrendingSourceStatus(Base):
    """来源健康状态：供 /api/ai-trending/sources 与前端来源 Tab 警示角标使用。

    每次抓取尝试都会更新 last_fetched_at / last_status；
    成功清零 consecutive_failures 并刷新 last_success_at / 累加 total_fetched；
    连续失败 >= 3 时 fail_count += 1（UI 警示用，不自动清零）。
    """

    __tablename__ = "ai_trending_source_status"

    source_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(64), default="")
    category_type: Mapped[str] = mapped_column(String(16), default="news")
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), default="")  # success / failed / ""
    last_error: Mapped[str] = mapped_column(Text, default="")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_fetched: Mapped[int] = mapped_column(Integer, default=0)
