"""频率词规则表。"""

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

    废弃列（老库保留不读，见 core/database.py::_ensure_hotlist_topic_rule_schema）：
    source_ids —— 源范围已由主题的 hot_topic_sources 决定，规则不再存一份（冗余且会不一致）；
    notify_enabled / notify_channel_ids / notify_time_start / notify_time_end /
    notify_frequency / notify_only_on_hit / notify_pending_hits /
    notify_pending_since
    —— 实时命中推送已整体迁到 hot_topics.hit_notify_*，规则自身不再读写。
    """

    __tablename__ = "hot_keyword_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_type: Mapped[str] = mapped_column(
        String(16), default="group", index=True
    )
    """group = 词组规则；global_filter = 全局过滤词（命中即从所有词组匹配结果里剔除）。"""

    topic_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    """所属主题。NULL 表示全局规则：
       - rule_type='global_filter' 时恒为 NULL（全局过滤词对所有主题生效）
       - rule_type='group' 且 topic_id 为 NULL 的是历史遗留数据，迁移脚本会收编（见 §5）
    """

    display_name: Mapped[str] = mapped_column(String(64), default="")
    # JSON: 普通词（组内 OR）
    normal_words: Mapped[str] = mapped_column(Text, default="[]")
    # JSON: 必须词（AND）
    required_words: Mapped[str] = mapped_column(Text, default="[]")
    # JSON: 排除词（NOT，按本规则生效）
    exclude_words: Mapped[str] = mapped_column(Text, default="[]")
    # 每组最多显示条数，0 = 不限
    max_count: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
