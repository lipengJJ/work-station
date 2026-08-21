"""热点条目表。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class HotItem(Base):
    """热点条目（去重后的主记录，一条 = 某个源上的一个话题/内容）。

    去重键是 (source_id, url) 的部分唯一索引（url 非空时生效）。url 为空的条目
    （少数热榜不给链接）不进唯一约束，由应用层按 (source_id, stat_date, title) 兜底查一次。

    刻意「不做」跨源合并：同一篇文章同时上了 HN 和 GitHub Trending，这两条各自留着。
    旧 ai_trending 的做法是跨源同 URL 只留热度最高的一条，那会把「多个榜同时在推」
    这个本身有价值的信号抹掉。要折叠展示是前端的事。
    """

    __tablename__ = "hot_items"
    __table_args__ = (
        # SQLite 支持部分唯一索引：只对非空 URL 去重
        Index(
            "ux_hot_items_source_url",
            "source_id",
            "url",
            unique=True,
            sqlite_where=text("url != ''"),
        ),
        Index("ix_hot_items_source_last", "source_id", "last_crawl_time"),
        Index("ix_hot_items_date_weight", "stat_date", "weight"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    url: Mapped[str] = mapped_column(String(1024), default="")  # 已归一化
    mobile_url: Mapped[str] = mapped_column(String(1024), default="")
    summary: Mapped[str] = mapped_column(Text, default="")

    stat_date: Mapped[str] = mapped_column(String(10), index=True)
    """YYYY-MM-DD，语义是「**首次发现日期**」，不是「所属日期」。

    TrendRadar 用「一天一个 SQLite 文件」做天级隔离、每天重新插入，所以它的日期是分区键；
    这里唯一键是全局的 (source_id, url)，一条记录跨天只有一行，日期就退化成了首见日。

    ⚠️ 所以「今日在榜」这类范围查询一律用 last_crawl_time，不要用 stat_date——
    GitHub 周榜里上周就上榜、这周还在榜的项目，stat_date 停在上周，
    用 stat_date 过滤会把它整个漏掉。stat_date 只用于「今天新发现了多少条」和数据清理统计。"""

    rank: Mapped[int] = mapped_column(Integer, default=0)
    """最新一次抓取时的榜位（1 起）。0 表示本批次已脱榜。"""

    best_rank: Mapped[int] = mapped_column(Integer, default=999)
    ranks_json: Mapped[str] = mapped_column(Text, default="[]")
    """历史榜位缓存（最近 N 次，JSON 数组）。权重公式要全部榜位，
    每次去 hot_rank_history 聚合太贵，写入时顺带更新这一列。"""

    first_crawl_time: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    last_crawl_time: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    crawl_count: Mapped[int] = mapped_column(Integer, default=1)

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    """源给了才有（RSS / arXiv），热榜类基本为 None。参与时间衰减计算。"""

    metrics: Mapped[str] = mapped_column(Text, default="{}")
    """JSON：points / stars_today / trendingScore 等源原始指标。**仅用于展示**，不参与打分。
    打分统一用榜位——旧模块那套 MAX_REF 参考上限（HN 10000 / GitHub 5000 / HF 1000000）
    是拍脑袋定的，跨源可比性并不成立。"""

    weight: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    """写入时算好，列表页直接 ORDER BY weight DESC，不在查询时现算。"""

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
