"""热榜主题表。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HotTopic(Base):
    """主题 = 一组源 + 一组关键词 + 一个分析 Skill + 一个周期 + 一个通知渠道 的绑定。

    v1 曾把主题订阅折进 HotKeywordRule，是错的：规则只负责「这条命中不命中」，
    而主题要回答「看哪些源、用什么 Skill、多久出一份、发给谁」。规则是主题的一个组成部分。
    """

    __tablename__ = "hot_topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    """对象存储路径要用，必须是 URL 安全的 ASCII。创建时按 name 生成候选值但允许改，
    生成后不允许修改——改了会导致已发布的报告路径断链。"""
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # ---------------------------------------------------------- 分析配置 ----
    skill_key: Mapped[str] = mapped_column(String(64), default="")
    """指向 skills 表。空 = 用内置默认周报 Prompt（让用户不配 Skill 也能先跑起来）。"""
    template_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extra_question: Mapped[str] = mapped_column(Text, default="")
    """每次分析追加的自定义要求，透传给 prepare_run 的 question。仅影响报告写作，不影响文章检索。"""

    # ---------------------------------------------------------- 语义检索配置 ----
    interest_query: Mapped[str] = mapped_column(Text, default="")
    """用户自然语言关注需求，例如「我想看 AI 工具链相关的新闻或者知识」。决定「找什么」。"""
    retrieval_mode: Mapped[str] = mapped_column(String(16), default="semantic")
    """第一版只开放 semantic；保留未来 hybrid 值。"""
    similarity_threshold: Mapped[float] = mapped_column(Float, default=0.35)
    """语义召回门槛，模型相关，必须通过预览/样本校准，不能视为通用常量。"""
    retrieval_size: Mapped[int] = mapped_column(Integer, default=100)
    """语义召回给 Funnel 的最大条数，建议范围 10~500。"""

    digest_strategy: Mapped[str] = mapped_column(String(16), default="funnel")
    """裁剪策略：simple / two_stage / funnel。不同主题可以不同——
    条目少的窄主题用 simple 反而更好，别全局一刀切。"""

    # daily / weekly
    digest_period: Mapped[str] = mapped_column(String(16), default="weekly")
    digest_cron: Mapped[str] = mapped_column(String(64), default="0 8 * * 1")
    # 进入 L0 的上限
    max_items: Mapped[int] = mapped_column(Integer, default=500)
    # L0 选出多少条进 L1
    shortlist_size: Mapped[int] = mapped_column(Integer, default=80)
    # L1 之后抓多少条全文
    fulltext_size: Mapped[int] = mapped_column(Integer, default=15)
    compare_with_previous: Mapped[bool] = mapped_column(Boolean, default=True)

    # ---------------------------------------------------------- 发布配置 ----
    publish_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    publish_formats: Mapped[str] = mapped_column(
        String(64), default='["json","html"]'
    )

    # ------------------------------------ 通知配置（字段对齐 XhsTrackingTask）----
    # 报告定时推送（原 notify_*，改名消除歧义；老列保留在库中不读）
    report_notify_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    report_notify_channel_ids: Mapped[str] = mapped_column(Text, default="[]")
    report_notify_time_start: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )
    report_notify_time_end: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )

    # ---- 实时命中推送（自 hot_keyword_rules 迁移，老列保留在库中不读）----
    hit_notify_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    hit_notify_channel_ids: Mapped[str] = mapped_column(Text, default="[]")
    hit_notify_time_start: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )
    hit_notify_time_end: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )
    hit_notify_frequency: Mapped[str] = mapped_column(
        String(16), default="realtime"
    )
    """realtime / 1h / 6h / 12h / daily"""
    hit_notify_only_on_hit: Mapped[bool] = mapped_column(Boolean, default=True)
    hit_notify_pending_hits: Mapped[int] = mapped_column(Integer, default=0)
    hit_notify_pending_since: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=_utcnow
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )
