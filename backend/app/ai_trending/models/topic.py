from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AiTrendingTopic(Base):
    """AI 开发热点主题：按关键词定向检索各源，命中的条目通过 AiTrendingTopicHit 引用。

    与全局热榜（ai_trending_items）共享数据底座：
    - keywords 存 JSON 数组（json.dumps ensure_ascii=False），多关键词 OR 命中；
    - interval job 由 APScheduler 按 interval_minutes 注册（app/ai_trending/services/
      scheduler_jobs.py::register_topic_job），扫描逻辑在 topic_service.run_topic_scan；
    - push_* 四字段为「主题级推送配置」内嵌占位（P0 仅落库，不触发真实发送，
      实际通道由机器人模块分支接入）；channel 枚举 wecom/dingtalk/feishu/email。
    """

    __tablename__ = "ai_trending_topic"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    keywords: Mapped[str] = mapped_column(Text, default="[]")  # JSON list[str]，OR 命中

    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    status: Mapped[str] = mapped_column(String(16), default="idle")  # idle / running / failed
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_item_count: Mapped[int] = mapped_column(Integer, default=0)

    # ---- 内嵌推送配置（P0 仅保存；推送通道由机器人模块分支开发）----
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    push_channel: Mapped[str | None] = mapped_column(String(16), nullable=True)  # wecom/dingtalk/feishu/email
    push_frequency: Mapped[str] = mapped_column(String(16), default="daily")  # P0 仅 daily
    push_time: Mapped[str] = mapped_column(String(5), default="09:00")  # HH:MM 本地时区

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
