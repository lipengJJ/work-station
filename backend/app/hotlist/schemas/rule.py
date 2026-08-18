from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_WORDS_PER_LIST = 30
MAX_WORD_LENGTH = 100
ALLOWED_NOTIFY_FREQUENCIES = ("realtime", "1h", "6h", "12h", "daily")


class WordIn(BaseModel):
    word: str = Field(min_length=1, max_length=MAX_WORD_LENGTH)
    is_regex: bool = False
    display_name: str | None = None


def _check_word_count(value: list[WordIn]) -> list[WordIn]:
    if len(value) > MAX_WORDS_PER_LIST:
        raise ValueError(f"每类词最多 {MAX_WORDS_PER_LIST} 个")
    return value


class RuleIn(BaseModel):
    """创建/更新词组规则（rule_type 固定为 group；global_filter 走 GlobalFilterIn）。"""

    display_name: str = Field("", max_length=64)
    normal_words: list[WordIn] = Field(default_factory=list)
    required_words: list[WordIn] = Field(default_factory=list)
    exclude_words: list[WordIn] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    max_count: int = Field(0, ge=0)
    enabled: bool = True
    sort_order: int = 0

    notify_enabled: bool = False
    notify_channel_ids: list[int] = Field(default_factory=list)
    notify_time_start: str | None = None
    notify_time_end: str | None = None
    notify_frequency: str = "realtime"
    notify_only_on_hit: bool = True

    _check_normal = field_validator("normal_words")(_check_word_count)
    _check_required = field_validator("required_words")(_check_word_count)
    _check_exclude = field_validator("exclude_words")(_check_word_count)

    @field_validator("notify_frequency")
    @classmethod
    def _check_frequency(cls, value: str) -> str:
        if value not in ALLOWED_NOTIFY_FREQUENCIES:
            raise ValueError(f"notify_frequency 需为 {list(ALLOWED_NOTIFY_FREQUENCIES)} 之一")
        return value


class GlobalFilterIn(BaseModel):
    """全局过滤词：只有一个 word 字段（纯文本，不支持正则，语义同 TrendRadar [GLOBAL_FILTER]）。"""

    word: str = Field(min_length=1, max_length=MAX_WORD_LENGTH)
    enabled: bool = True
    sort_order: int = 0


def _parse_json_list(value: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return []
    return value or []


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_type: str
    display_name: str = ""
    normal_words: list[dict] = Field(default_factory=list)
    required_words: list[dict] = Field(default_factory=list)
    exclude_words: list[dict] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    max_count: int = 0
    enabled: bool = True
    sort_order: int = 0

    notify_enabled: bool = False
    notify_channel_ids: list[int] = Field(default_factory=list)
    notify_time_start: str | None = None
    notify_time_end: str | None = None
    notify_frequency: str = "realtime"
    notify_only_on_hit: bool = True

    created_at: datetime | None = None
    updated_at: datetime | None = None

    _parse_normal = field_validator("normal_words", mode="before")(_parse_json_list)
    _parse_required = field_validator("required_words", mode="before")(_parse_json_list)
    _parse_exclude = field_validator("exclude_words", mode="before")(_parse_json_list)
    _parse_sources = field_validator("source_ids", mode="before")(_parse_json_list)
    _parse_channels = field_validator("notify_channel_ids", mode="before")(_parse_json_list)


class RuleImportIn(BaseModel):
    text: str = Field(min_length=1)


class RuleImportOut(BaseModel):
    created_groups: int = 0
    created_global_filters: int = 0


class RulePreviewIn(BaseModel):
    """试跑：不落库，拿当天已抓数据跑一遍匹配。直接传待测词，不依赖已保存的规则 id
    （这样「编辑中还没保存」也能预览）。"""

    normal_words: list[WordIn] = Field(default_factory=list)
    required_words: list[WordIn] = Field(default_factory=list)
    exclude_words: list[WordIn] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    sample_limit: int = Field(20, ge=1, le=100)


class RulePreviewOut(BaseModel):
    matched_count: int = 0
    samples: list[dict] = Field(default_factory=list)
