"""热点源字典与健康状态表。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class HotSource(Base):
    """热点源字典 + 健康状态。

    一行 = 一个可抓取的榜单。中文热榜（微博/知乎/抖音…）与技术源（HN/GitHub/arXiv…）
    统一放这张表，靠 source_kind 区分；真正干活的抓取器由 adapter 字段指向
    services/adapters 注册表里的实现，adapter_params 是该实现需要的参数。

    这样设计的直接好处：一个 adapter 可以喂多行源——newsnow adapter 驱动全部中文热榜
    （params={"platform": "weibo"}），rss adapter 驱动任意订阅源（params={"url": "..."}），
    所以「新增一个 RSS 源」是前端点一下，不用写代码、不用重启。

    健康状态字段（last_* / consecutive_failures / fail_count）沿用原 ai_trending 的设计：
    源字典与健康状态本来就是 1:1，拆两张表只是徒增一次 join。
    """

    __tablename__ = "hot_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    source_kind: Mapped[str] = mapped_column(
        String(16), default="hotlist", index=True
    )
    """hotlist = 中文热榜；tech = 技术源。仅用于前端分组与筛选，不影响抓取逻辑。"""

    adapter: Mapped[str] = mapped_column(String(32), default="")
    adapter_params: Mapped[str] = mapped_column(Text, default="{}")  # JSON

    expected_domain: Mapped[str] = mapped_column(String(128), default="")
    """域名安全校验：填主域名（如 baidu.com），校验返回链接是否 HTTPS 且主机名匹配该域或其子域。
    用公共 NewsNow 实例时强烈建议配置，防第三方 API 返回被篡改/劫持的链接。"""

    decay_half_life_hours: Mapped[float] = mapped_column(Float, default=0.0)
    """权重时间衰减半衰期（小时）。0 = 不衰减（热榜靠 stat_date 按天分域，本来就没有陈旧问题）；
    24 = 论文/RSS；48 = HN/GitHub。一个公式覆盖两类源，见 services/ranking.py。"""

    cron_expr: Mapped[str] = mapped_column(String(64), default="*/30 * * * *")
    """5 段 cron。入库而不是写死常量，抓取频率可以在前端改，不用改代码重启。"""

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    group_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    """所属分组（hot_source_groups.id）。NULL = 未分组，前端归入「未分组」区。
    分组是纯粹的组织方式（1:N），与主题（N:N，走 hot_topic_sources）正交，
    不参与抓取调度与匹配逻辑。"""

    # ------------------------------------------------------------ 健康状态 ----
    last_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    # success / failed / ""
    last_status: Mapped[str] = mapped_column(String(16), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    total_fetched: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
