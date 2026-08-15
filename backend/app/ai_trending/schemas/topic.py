from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.ai_trending.schemas.trending import TrendingItemOut

_PUSH_TIME_RE = re.compile(r"^\d{2}:\d{2}$")

# 与 services/topic_service.py 保持一致（P0 对齐 xhs 频率集合）
ALLOWED_INTERVALS = (15, 30, 60, 180, 360, 720, 1440)
ALLOWED_CHANNELS = ("wecom", "dingtalk", "feishu", "email")
ALLOWED_FREQUENCIES = ("daily",)  # P0 仅 daily，P1 扩展 hourly 等
MAX_KEYWORDS = 20
MAX_KEYWORD_LEN = 50


# ------------------------------------------------------------ 推送配置 ----
class TopicPushConfigIn(BaseModel):
    """主题级推送配置入参：channel 枚举 + frequency 仅 daily + time HH:MM。

    校验失败由全局 RequestValidationError handler 统一转 400。
    """

    enabled: bool = False
    channel: str = "wecom"
    frequency: str = "daily"
    time: str = "09:00"

    @field_validator("channel")
    @classmethod
    def _check_channel(cls, value: str) -> str:
        value = (value or "").strip()
        if value not in ALLOWED_CHANNELS:
            raise ValueError(f"channel 需为 {list(ALLOWED_CHANNELS)} 之一")
        return value

    @field_validator("frequency")
    @classmethod
    def _check_frequency(cls, value: str) -> str:
        value = (value or "").strip()
        if value not in ALLOWED_FREQUENCIES:
            raise ValueError(f"frequency P0 仅支持 daily（{list(ALLOWED_FREQUENCIES)}）")
        return value

    @field_validator("time")
    @classmethod
    def _check_time(cls, value: str) -> str:
        value = (value or "").strip()
        if not _PUSH_TIME_RE.match(value):
            raise ValueError("time 需为 HH:MM 格式")
        hour, minute = int(value[:2]), int(value[3:5])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("time 时需 0-23、分需 0-59")
        return value


class TopicPushConfigOut(BaseModel):
    """主题级推送配置出参（与 ORM 内嵌四字段一一对应）。"""

    enabled: bool = False
    channel: str = "wecom"
    frequency: str = "daily"
    time: str = "09:00"


# ------------------------------------------------------------ 主题 ----
class TopicCreateIn(BaseModel):
    """创建主题入参：name/keywords 必填，interval/enabled/push 可选。"""

    name: str = Field(..., min_length=1, max_length=128)
    keywords: list[str] = Field(..., min_length=1)
    interval_minutes: int = Field(60)
    enabled: bool = True
    push: TopicPushConfigIn | None = None

    @field_validator("keywords")
    @classmethod
    def _check_keywords(cls, value: list[str]) -> list[str]:
        cleaned = [str(k).strip() for k in value if str(k).strip()]
        if not cleaned:
            raise ValueError("keywords 需至少一个非空关键词")
        if len(cleaned) > MAX_KEYWORDS:
            raise ValueError(f"keywords 最多 {MAX_KEYWORDS} 个关键词")
        for kw in cleaned:
            if len(kw) > MAX_KEYWORD_LEN:
                raise ValueError(f"单个关键词最长 {MAX_KEYWORD_LEN} 字")
        return cleaned

    @field_validator("interval_minutes")
    @classmethod
    def _check_interval(cls, value: int) -> int:
        if value not in ALLOWED_INTERVALS:
            raise ValueError(f"interval_minutes 需为 {list(ALLOWED_INTERVALS)} 之一")
        return value


class TopicUpdateIn(BaseModel):
    """更新主题入参：全部可选（只更新传入字段，未传保持原值）。"""

    name: str | None = Field(None, min_length=1, max_length=128)
    keywords: list[str] | None = None
    interval_minutes: int | None = None
    enabled: bool | None = None
    push: TopicPushConfigIn | None = None

    @field_validator("keywords")
    @classmethod
    def _check_keywords(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [str(k).strip() for k in value if str(k).strip()]
        if not cleaned:
            raise ValueError("keywords 需至少一个非空关键词")
        if len(cleaned) > MAX_KEYWORDS:
            raise ValueError(f"keywords 最多 {MAX_KEYWORDS} 个关键词")
        for kw in cleaned:
            if len(kw) > MAX_KEYWORD_LEN:
                raise ValueError(f"单个关键词最长 {MAX_KEYWORD_LEN} 字")
        return cleaned

    @field_validator("interval_minutes")
    @classmethod
    def _check_interval(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value not in ALLOWED_INTERVALS:
            raise ValueError(f"interval_minutes 需为 {list(ALLOWED_INTERVALS)} 之一")
        return value


class TopicOut(BaseModel):
    """主题出参：由 service serialize_topic 构造（含计算字段），不用 from_attributes。"""

    id: int
    name: str
    keywords: list[str]
    interval_minutes: int
    enabled: bool
    status: str  # idle / running / failed
    last_run_at: datetime | None = None
    last_run_message: str | None = None
    last_item_count: int = 0
    hit_count: int = 0  # 主题命中总数（matched=True 的 hits 数）
    next_run_at: str | None = None
    push: TopicPushConfigOut = TopicPushConfigOut()
    created_at: datetime | None = None


class TopicHitPage(BaseModel):
    """主题命中条目分页结果：items 复用 TrendingItemOut（join hits + items）。"""

    items: list[TrendingItemOut] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class TopicRunResultOut(BaseModel):
    """run-now 出参：接口只负责触发，实际扫描在 daemon 线程异步执行。"""

    success: bool = True
    message: str = ""
