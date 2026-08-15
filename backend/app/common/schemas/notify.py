from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel: str
    remark: str = ""
    webhook_url: str
    sendkey: str
    token: str
    enabled: bool
    mention_all: bool
    created_at: datetime
    updated_at: datetime


class NotificationConfigIn(BaseModel):
    # 长度上限与 ORM 列保持一致（NotificationConfig.channel String(32) / webhook_url String(512) / sendkey|token String(256)）
    channel: str | None = Field(default=None, max_length=32)  # 路径携带时忽略；保留字段用于旧调用兼容
    remark: str = Field(default="", max_length=64)  # 备注名（同类型多实例区分，如"研发群"）
    webhook_url: str = Field(default="", max_length=512)  # 企业微信机器人完整 webhook 地址（含 key 参数）
    sendkey: str = Field(default="", max_length=256)  # Server酱 SendKey
    token: str = Field(default="", max_length=256)  # PushPlus Token（预留）
    enabled: bool = False
    mention_all: bool = False


class ChannelFieldDef(BaseModel):
    """通道配置弹窗的字段定义（数据驱动渲染）"""

    key: str
    label: str
    type: str = "text"  # text | password | textarea | switch
    mono: bool = False
    placeholder: str | None = None
    extra: str | None = None


class ChannelInfo(BaseModel):
    """通道目录项：元信息 + 实时配置状态（G4 公共入口）"""

    channel: str
    label: str
    icon: str = "bell"
    description: str = ""
    configured: bool = False
    enabled: bool = False
    summary: str = ""
    capabilities: list[str] = []
    fields: list[ChannelFieldDef] = []
    not_implemented: bool = False


class ChannelList(BaseModel):
    channels: list[ChannelInfo]


class NotificationLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel: str
    title: str
    content: str | None
    status: str
    error_msg: str | None
    created_at: datetime


class TestItemResult(BaseModel):
    channel: str
    remark: str = ""
    success: bool
    message: str = ""


class TestAllResult(BaseModel):
    success: bool
    total: int
    success_count: int
    message: str = ""
    results: list[TestItemResult] = []


class NotificationLogPage(BaseModel):
    items: list[NotificationLogOut]
    total: int
    page: int
    page_size: int


class SendResult(BaseModel):
    success: bool
    message: str


class TestSendIn(BaseModel):
    channel: str | None = Field(default=None, max_length=32)  # 指定测试通道；不传=第一个启用通道


class ManualSendIn(BaseModel):
    channel: str | None = Field(default=None, max_length=32)  # 指定发送通道；不传=第一个启用通道
    title: str = Field(default="手动通知", max_length=256)  # 长度与 NotificationLog.title String(256) 一致
    content: str = ""
    msgtype: str = "text"  # text | markdown
