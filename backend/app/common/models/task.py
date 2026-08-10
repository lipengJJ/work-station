from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Task(Base):
    """
    统一任务表：股票分析跑批（module='stock'）和小红书采集任务（module='xhs'）都记在这里，
    任务中心页面按 status 分组读这张表。字段留了 params/result_summary，Phase 3 接入真实
    业务逻辑时不需要再改表结构。
    """

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    module: Mapped[str] = mapped_column(String(32), index=True)  # stock | xhs | ...
    task_type: Mapped[str] = mapped_column(String(64))  # analyze | xhs_search | ...
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending/running/success/failed
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
