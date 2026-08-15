from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel: str
    webhook_url: str
    sendkey: str
    enabled: bool
    mention_all: bool
    created_at: datetime
    updated_at: datetime


class NotificationConfigIn(BaseModel):
    # 长度上限与 ORM 列保持一致（NotificationConfig.channel String(32) / webhook_url String(512) / sendkey String(256)）
    channel: str = Field(default="wecom_webhook", max_length=32)
    webhook_url: str = Field(default="", max_length=512)  # 企业微信机器人完整 webhook 地址（含 key 参数）
    sendkey: str = Field(default="", max_length=256)  # Server酱 SendKey（channel='serverchan' 时使用）
    enabled: bool = False
    mention_all: bool = False


class NotificationLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel: str
    title: str
    content: str | None
    status: str
    error_msg: str | None
    created_at: datetime


class NotificationLogPage(BaseModel):
    items: list[NotificationLogOut]
    total: int
    page: int
    page_size: int


class SendResult(BaseModel):
    success: bool
    message: str


class ManualSendIn(BaseModel):
    title: str = Field(default="手动通知", max_length=256)  # 长度与 NotificationLog.title String(256) 一致
    content: str = ""
    msgtype: str = "text"  # text | markdown
