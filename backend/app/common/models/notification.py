from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NotificationConfig(Base):
    """
    系统设置 > 消息通知：通知通道配置（企业微信机器人 / Server酱）。
    单例配置——表里最多一行（id=1），保存接口按固定 id 覆盖，避免出现多行配置让
    发送逻辑不知道该用哪条。
    channel 语义：wecom_webhook=企业微信群机器人（默认）；serverchan=Server酱。
    """

    __tablename__ = "notification_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), default="wecom_webhook")
    webhook_url: Mapped[str] = mapped_column(String(512), default="")  # 企业微信机器人 webhook（含 key 参数）
    sendkey: Mapped[str] = mapped_column(String(256), default="")  # Server酱 SendKey（channel='serverchan' 时使用）
    enabled: Mapped[bool] = mapped_column(default=False)  # 总开关：关闭时不发任何任务通知
    mention_all: Mapped[bool] = mapped_column(default=False)  # text 消息是否 @所有人
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class NotificationLog(Base):
    """
    消息通知发送记录：任务完成/失败通知、手动测试发送都会记一条。
    发送失败也照常落库（status='failed' + error_msg），方便在页面上排查 webhook 问题。
    """

    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), default="wecom_webhook")
    title: Mapped[str] = mapped_column(String(256), default="")
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="success", index=True)  # success/failed
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
