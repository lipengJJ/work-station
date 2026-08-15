from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AiTrendingPushConfig(Base):
    """AI 热点定时推送配置（单行，id 恒为 1）。

    约定：
    - enabled=False 时不注册定时 job（register_push_job 读取）；
    - webhook_url 明文存储（本地单用户可接受），API 回显掩码（key=****后4位）；
    - webhook_secret 只回 webhook_secret_set 布尔，不回显明文；
    - keyword 配置后内嵌推送消息标题（企微自定义关键词校验）；
    - push_time 为 HH:MM，由 APScheduler 按服务器本地时区解释。
    """

    __tablename__ = "ai_trending_push_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # 恒为 1（单行配置）
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    webhook_url: Mapped[str] = mapped_column(String(1024), default="")
    webhook_secret: Mapped[str | None] = mapped_column(String(128), nullable=True)
    keyword: Mapped[str | None] = mapped_column(String(128), nullable=True)
    push_time: Mapped[str] = mapped_column(String(5), default="09:00")
    top_n: Mapped[int] = mapped_column(Integer, default=10)
    summary_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
