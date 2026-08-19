from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NotificationConfig(Base):
    """
    系统设置 > 消息通知：通知通道配置（**支持同类型多实例**）。
    channel 表示渠道类型（wecom_webhook=企业微信群机器人；serverchan=Server酱；
    pushplus=PushPlus；email=SMTP 邮件），同一类型可配置多个实例（如两个不同的企微群机器人），
    用 remark 备注名区分。每个实例独立 enabled，任务完成/失败通知扇出到所有启用实例。
    """

    __tablename__ = "notification_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), default="wecom_webhook")  # 渠道类型（可重复）
    remark: Mapped[str] = mapped_column(String(64), default="")  # 备注名（多实例区分，如"研发群"）
    webhook_url: Mapped[str] = mapped_column(String(512), default="")  # 企业微信机器人 webhook（含 key 参数）
    sendkey: Mapped[str] = mapped_column(String(256), default="")  # Server酱 SendKey
    token: Mapped[str] = mapped_column(String(256), default="")  # PushPlus Token（预留通道）
    enabled: Mapped[bool] = mapped_column(default=False)  # 本实例开关：关闭时不发任务通知
    mention_all: Mapped[bool] = mapped_column(default=False)  # text 消息是否 @所有人（企业微信）
    # ---- email 通道（SMTP）----
    smtp_host: Mapped[str] = mapped_column(String(255), default="")  # 如 smtp.qq.com
    smtp_port: Mapped[int] = mapped_column(Integer, default=465)
    smtp_user: Mapped[str] = mapped_column(String(255), default="")  # 发件邮箱，同时用作登录账号
    smtp_password: Mapped[str] = mapped_column(String(255), default="")  # SMTP 密码/授权码
    smtp_use_ssl: Mapped[bool] = mapped_column(Boolean, default=True)  # True=SSL(常见465)；False=STARTTLS(常见587)
    email_to: Mapped[str] = mapped_column(String(512), default="")  # 收件邮箱，逗号分隔支持多个
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
