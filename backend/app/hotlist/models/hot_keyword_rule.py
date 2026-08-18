from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class HotKeywordRule(Base):
    """频率词规则：吸收原 ai_trending 的「主题订阅」（topic + topic push config）。

    一行 = 一组关键词规则（rule_type="group"）或一条全局过滤词（rule_type="global_filter"）。
    词组内 normal_words 是 OR、required_words 是 AND、exclude_words 是 NOT，
    每个词存成 {"word": "...", "is_regex": bool, "display_name": str|None}
    ——这正是 keyword_rules.py::_parse_word 的产物结构（不含 compiled pattern，
    JSON 不能存正则对象，is_regex=True 的词加载时重新 re.compile）。

    与移植自 TrendRadar 的原始文本 DSL 的一处刻意不同：exclude_words 按规则（组）独立生效，
    不是「文件里任意一行 !词 全局排除所有组」那种因为单文件顺序解析产生的副作用——
    数据库按行独立存储后没理由继续保留这个反直觉行为，见 services/keyword_rules.py 头部说明。

    推送配置字段直接照抄 XhsTrackingTask（app/xhs/models/xhs_tracking_task.py），
    语义完全对得上：同一套「时段 + 频率 + 仅命中时推送 + 暂存汇总」逻辑，push_service.py
    （Phase 4）可以照搬 xhs/services/tracking.py 的推送编排。
    """

    __tablename__ = "hot_keyword_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_type: Mapped[str] = mapped_column(String(16), default="group", index=True)
    """group = 词组规则；global_filter = 全局过滤词（命中即从所有词组匹配结果里剔除）。"""

    display_name: Mapped[str] = mapped_column(String(64), default="")
    normal_words: Mapped[str] = mapped_column(Text, default="[]")  # JSON: 普通词（组内 OR）
    required_words: Mapped[str] = mapped_column(Text, default="[]")  # JSON: 必须词（AND）
    exclude_words: Mapped[str] = mapped_column(Text, default="[]")  # JSON: 排除词（NOT，按本规则生效）
    source_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON: 限定源；[] = 全部源
    max_count: Mapped[int] = mapped_column(Integer, default=0)  # 每组最多显示条数，0 = 不限
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # ---- 推送配置（对齐 XhsTrackingTask，字段名/语义完全一致）----
    notify_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_channel_ids: Mapped[str] = mapped_column(Text, default="[]")  # JSON list[int]
    notify_time_start: Mapped[str | None] = mapped_column(String(8), nullable=True)  # "HH:mm"
    notify_time_end: Mapped[str | None] = mapped_column(String(8), nullable=True)
    notify_frequency: Mapped[str] = mapped_column(String(16), default="realtime")  # realtime/1h/6h/12h/daily
    notify_only_on_hit: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_pending_hits: Mapped[int] = mapped_column(Integer, default=0)
    notify_pending_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
