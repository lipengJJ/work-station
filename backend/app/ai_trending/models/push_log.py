from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, inspect, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.database import Base, engine


class AiTrendingPushLog(Base):
    """AI 热点定时推送记录（每次推送一行，测试推送同样落一行）。

    - pushed_at 存 UTC（与既有模型一致），对外 isoformat；
    - status 枚举：success（AI 正常 + webhook 成功）/ degraded（AI 失败走规则降级但
      webhook 成功）/ failed（webhook 最终失败或当日无热点）；
    - error 截断 500 字；summary_preview = 完整 markdown 前 500 字（前端状态卡展示用）；
    - topic_id：新增可空列，非空 = 主题推送记录，空 = 全局推送记录（P0 主题推送不执行）。
    """

    __tablename__ = "ai_trending_push_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pushed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    items_count: Mapped[int] = mapped_column(Integer, default=0)
    summary_preview: Mapped[str] = mapped_column(Text, default="")
    # 主题级推送记录标记（P1 主题推送接入后使用）；NULL = 全局推送记录
    topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


def ensure_push_log_topic_id(db: Session | None = None) -> None:
    """幂等轻量迁移：确保 ai_trending_push_log 表存在 topic_id 列。

    新建库由 ORM create_all 直接建出该列；存量库 create_all 不会给已存在表加列，
    这里用 sqlalchemy.inspect 查列，缺列则执行 ALTER TABLE ADD COLUMN。
    在 init_db() 的 create_all 之后调用（幂等，重启安全），不引 alembic、零新增依赖。
    """
    bind = db.get_bind() if db is not None else engine
    inspector = inspect(bind)
    if "ai_trending_push_log" not in inspector.get_table_names():
        # 表尚不存在（如首次建库流程异常），create_all 会连带建出含 topic_id 的表
        return
    columns = {col["name"] for col in inspector.get_columns("ai_trending_push_log")}
    if "topic_id" in columns:
        return
    with bind.begin() as conn:
        conn.execute(text("ALTER TABLE ai_trending_push_log ADD COLUMN topic_id INTEGER"))
