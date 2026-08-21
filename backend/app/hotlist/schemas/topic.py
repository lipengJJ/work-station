"""主题请求/响应模型。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------- 主题 ----

DIGEST_STRATEGIES = ("simple", "two_stage", "funnel")
DIGEST_PERIODS = ("daily", "weekly")
PUBLISH_FORMATS = ("json", "html")
HIT_NOTIFY_FREQUENCIES = ("realtime", "1h", "6h", "12h", "daily")


class TopicIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    slug: str = Field("", max_length=64)
    """创建时留空 = 按 name 自动生成；已发布过不允许改（controller 校验）。"""
    description: str = ""
    enabled: bool = True
    sort_order: int = 0

    skill_key: str = ""
    template_key: str | None = None
    extra_question: str = ""

    digest_strategy: str = "funnel"
    digest_period: str = "weekly"
    digest_cron: str = "0 8 * * 1"
    max_items: int = Field(500, ge=1, le=5000)
    shortlist_size: int = Field(80, ge=1, le=1000)
    fulltext_size: int = Field(15, ge=0, le=200)
    compare_with_previous: bool = True

    publish_enabled: bool = False
    publish_formats: list[str] = Field(
        default_factory=lambda: ["json", "html"]
    )

    # 报告定时推送
    report_notify_enabled: bool = False
    report_notify_channel_ids: list[int] = Field(default_factory=list)
    report_notify_time_start: str | None = None
    report_notify_time_end: str | None = None

    # 实时命中推送（自 hot_keyword_rules 迁移）
    hit_notify_enabled: bool = False
    hit_notify_channel_ids: list[int] = Field(default_factory=list)
    hit_notify_time_start: str | None = None
    hit_notify_time_end: str | None = None
    hit_notify_frequency: str = "realtime"
    """realtime / 1h / 6h / 12h / daily"""
    hit_notify_only_on_hit: bool = True
    hit_notify_pending_hits: int = 0
    hit_notify_pending_since: datetime | None = None

    @field_validator("digest_strategy")
    @classmethod
    def _check_strategy(cls, v: str) -> str:
        if v not in DIGEST_STRATEGIES:
            raise ValueError(f"未知裁剪策略: {v}（可选：{'/'.join(DIGEST_STRATEGIES)}）")
        return v

    @field_validator("digest_period")
    @classmethod
    def _check_period(cls, v: str) -> str:
        if v not in DIGEST_PERIODS:
            raise ValueError(f"未知周期: {v}（可选：daily/weekly）")
        return v

    @field_validator("publish_formats")
    @classmethod
    def _check_formats(cls, v: list[str]) -> list[str]:
        for fmt in v:
            if fmt not in PUBLISH_FORMATS:
                raise ValueError(f"未知发布格式: {fmt}（可选：json/html）")
        return v

    @field_validator(
        "report_notify_time_start",
        "report_notify_time_end",
        "hit_notify_time_start",
        "hit_notify_time_end",
    )
    @classmethod
    def _check_notify_time(cls, v: str | None) -> str | None:
        if v is not None and (len(v) != 5 or v[2] != ":"):
            raise ValueError(f"时间格式应为 HH:MM：{v!r}")
        return v

    @field_validator("hit_notify_frequency")
    @classmethod
    def _check_hit_frequency(cls, v: str) -> str:
        if v not in HIT_NOTIFY_FREQUENCIES:
            raise ValueError(
                f"hit_notify_frequency 需为 {list(HIT_NOTIFY_FREQUENCIES)} 之一"
            )
        return v

    @field_validator(
        "publish_formats",
        "report_notify_channel_ids",
        "hit_notify_channel_ids",
        mode="before",
    )
    @classmethod
    def _parse_json_array(cls, v: object) -> object:
        """DB 里是 JSON 字符串，序列化出参时解析成数组（入参直接传数组，原样返回）。"""
        if isinstance(v, str):
            try:
                import json

                data = json.loads(v)
                return data if isinstance(data, list) else []
            except (ValueError, TypeError):
                return []
        return v


class TopicOut(TopicIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    enabled_source_count: int = 0
    """本主题启用中的源数（controller 回填，规模护栏展示用）。"""


class TopicUpdateIn(BaseModel):
    """全字段可选，覆盖式保存（未传字段不修改）。"""

    name: str | None = Field(None, min_length=1, max_length=64)
    description: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None
    skill_key: str | None = None
    template_key: str | None = None
    extra_question: str | None = None
    digest_strategy: str | None = None
    digest_period: str | None = None
    digest_cron: str | None = None
    max_items: int | None = Field(None, ge=1, le=5000)
    shortlist_size: int | None = Field(None, ge=1, le=1000)
    fulltext_size: int | None = Field(None, ge=0, le=200)
    compare_with_previous: bool | None = None
    publish_enabled: bool | None = None
    publish_formats: list[str] | None = None
    report_notify_enabled: bool | None = None
    report_notify_channel_ids: list[int] | None = None
    report_notify_time_start: str | None = None
    report_notify_time_end: str | None = None
    hit_notify_enabled: bool | None = None
    hit_notify_channel_ids: list[int] | None = None
    hit_notify_time_start: str | None = None
    hit_notify_time_end: str | None = None
    hit_notify_frequency: str | None = None
    hit_notify_only_on_hit: bool | None = None
    hit_notify_pending_hits: int | None = None
    hit_notify_pending_since: datetime | None = None


# ---------------------------------------------------------------- 源关联 ----

class TopicSourceOut(BaseModel):
    """主题下的源列表行：源信息 + 关联启用状态 + 健康状态 + 近 7 天贡献数。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    source_kind: str
    adapter: str
    cron_expr: str
    enabled: bool = True          # HotSource.enabled（全局熔断）
    last_status: str = ""
    last_error: str = ""
    consecutive_failures: int = 0
    fail_count: int = 0
    last_success_at: datetime | None = None
    total_fetched: int = 0
    topic_enabled: bool = False   # HotTopicSource.enabled（本主题内开关）
    imported_from: str = ""
    hit_count_7d: int = 0         # 近 7 天贡献的命中条目数（controller/service 回填）


class TopicSourceBatchIn(BaseModel):
    """批量开关：mode = all_on / all_off / set；set 模式下给 source_ids 集合。"""

    mode: str
    source_ids: list[str] = Field(default_factory=list)


class ImportOpmlIn(BaseModel):
    """OPML 导入：二选一（opml_text 优先于 opml_url）。"""

    opml_text: str = ""
    opml_url: str = ""


class OpmlImportResult(BaseModel):
    created: list[str] = Field(default_factory=list)   # 新建的源 id
    reused: list[str] = Field(default_factory=list)    # 复用已有源 id
    skipped: int = 0                                   # 跳过（重复或 xmlUrl 非法）
    source_ids: list[str] = Field(default_factory=list)  # 新建+复用的全部源 id
    detail: str = ""
