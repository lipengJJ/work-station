from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai_trending.services.push_webhook import validate_webhook_url

_PUSH_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


class PushConfigIn(BaseModel):
    """推送配置入参。

    保存语义：webhook_secret / keyword / summary_prompt 不传(None)=保持原值，传 ""=清除；
    webhook_url 传掩码值（含 ****）=保持原值（前端回显掩码后再保存的场景）。
    """

    enabled: bool
    webhook_url: str = ""
    webhook_secret: str | None = None
    keyword: str | None = None
    push_time: str = "09:00"
    top_n: int = Field(10, ge=1, le=50)
    summary_prompt: str | None = None

    @field_validator("webhook_url")
    @classmethod
    def _check_webhook_url(cls, value: str) -> str:
        value = (value or "").strip()
        if value and "****" not in value and not validate_webhook_url(value):
            raise ValueError(
                "webhook_url 格式非法：需为 https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
            )
        return value

    @field_validator("push_time")
    @classmethod
    def _check_push_time(cls, value: str) -> str:
        value = (value or "").strip()
        if not _PUSH_TIME_RE.match(value):
            raise ValueError("push_time 需为 HH:MM 格式")
        hour, minute = int(value[:2]), int(value[3:5])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("push_time 时需 0-23、分需 0-59")
        return value


class PushConfigOut(BaseModel):
    """推送配置出参。webhook_url 已掩码（key=****后4位）；secret 只回 webhook_secret_set。"""

    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    webhook_url: str
    webhook_secret_set: bool
    keyword: str | None = None
    push_time: str
    top_n: int
    summary_prompt: str | None = None


class PushTestIn(BaseModel):
    """测试推送入参：全部可选，提供则本次测试覆盖配置（不持久化）。"""

    enabled: bool | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = None
    keyword: str | None = None
    push_time: str | None = None
    top_n: int | None = Field(None, ge=1, le=50)
    summary_prompt: str | None = None


class PushLogOut(BaseModel):
    """推送记录出参。status: success / degraded / failed。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    pushed_at: datetime
    status: str
    error: str = ""
    items_count: int = 0
    summary_preview: str = ""
