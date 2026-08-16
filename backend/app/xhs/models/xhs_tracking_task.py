from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class XhsTrackingTask(Base):
    """
    追踪任务：按关键词 + 过滤条件周期性搜索小红书，命中的笔记存进 XhsTrackingHit。
    定时执行靠 APScheduler（app/xhs/tracking.py::register_job）按 interval_minutes
    往 xhs 那个单线程 worker 队列（app/xhs/tasks.py）里丢一个扫描任务，跟普通采集任务
    共用同一个串行 worker，避免和小红书风控冲突。
    """

    __tablename__ = "xhs_tracking_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    keyword: Mapped[str] = mapped_column(String(255))

    require_num: Mapped[int] = mapped_column(Integer, default=50)
    sort_type_choice: Mapped[int] = mapped_column(Integer, default=0)
    note_type: Mapped[int] = mapped_column(Integer, default=0)
    note_time: Mapped[int] = mapped_column(Integer, default=0)
    note_range: Mapped[int] = mapped_column(Integer, default=0)

    must_include: Mapped[str] = mapped_column(Text, default="[]")  # JSON list[str]
    must_exclude: Mapped[str] = mapped_column(Text, default="[]")  # JSON list[str]

    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # ---- 机器人通知配置（系统设置 > 消息通知 的渠道，按任务个性化推送） ----
    notify_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # 通知总开关
    notify_channel_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON list[int] 已选渠道 id
    notify_time_start: Mapped[str | None] = mapped_column(String(8), nullable=True)  # "HH:mm"，null=不限时段
    notify_time_end: Mapped[str | None] = mapped_column(String(8), nullable=True)
    notify_frequency: Mapped[str] = mapped_column(String(16), default="realtime")  # realtime/1h/6h/12h/daily
    notify_only_on_hit: Mapped[bool] = mapped_column(Boolean, default=True)  # 仅在有新命中时通知
    # 汇总推送暂存：时段外/频率未到的命中合并
    notify_pending_hits: Mapped[int] = mapped_column(Integer, default=0)
    notify_pending_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ---- AI 智能筛选配置（阶段 3，自定义 Prompt） ----
    ai_filter_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_filter_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)  # 用户 Prompt（不含系统追加）
    ai_filter_min_confidence: Mapped[float] = mapped_column(Float, default=0.6)

    status: Mapped[str] = mapped_column(String(16), default="idle")  # idle/running/failed
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_hit_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
