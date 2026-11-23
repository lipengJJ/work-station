"""源分组表。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HotSourceGroup(Base):
    """源分组：组织方式（1:N，一个源一个分组），与主题(N:N)正交，唯一交互点是
    「主题选源时可按分组批量勾选」。

    ⚠️ 与「主题」是两个正交维度，不要混淆：
      - 分组：一个源属于一个分组（1:N），回答「这个源是干什么的」
      - 主题：一个源可被多个主题引用（N:N，走 hot_topic_sources），回答「我要订阅什么」

    crawl_enabled 是分组唯一参与抓取调度的开关：默认关闭，源只靠被启用中的主题
    订阅触发自动抓取；开了这个开关，组内源不管有没有主题订阅都会常驻自动抓取
    （给"先攒着数据、以后再建主题"这种场景用）。手动点击"立即抓取"不受此限制。
    """

    __tablename__ = "hot_source_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)  # 「股票财经」
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(16), default="")  # 前端标签色，可空
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # 内置分组不允许删除
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    crawl_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=_utcnow
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )
