from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ScheduleConfig(Base):
    """系统设置 > 定时任务：每个 module 一条 cron 风格的调度配置。"""

    __tablename__ = "schedule_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    module: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    hour: Mapped[int] = mapped_column(default=9)
    minute: Mapped[int] = mapped_column(default=0)
    days: Mapped[str] = mapped_column(String(32), default="mon-fri")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
