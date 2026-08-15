from __future__ import annotations

from collections.abc import Generator

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 进程内只做一次老库检查（避免每次请求都 inspect 一遍表结构）
_schema_checked = False


def _ensure_notification_config_schema() -> None:
    """
    轻量老库兼容（无 Alembic，create_all 只建新表不 ALTER 已有表）：
    1. notification_config 补 sendkey / token 列（已有列跳过）；
    2. channel 列补唯一索引（多通道化：每通道一行）。
    任何异常只记日志，绝不让老库在启动/seed 时炸掉；进程内只检查一次，幂等。
    """
    global _schema_checked
    if _schema_checked:
        return
    _schema_checked = True
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "notification_config" not in inspector.get_table_names():
            return
        columns = {c["name"] for c in inspector.get_columns("notification_config")}
        with engine.begin() as conn:
            # SQLite 允许带 DEFAULT 的 ADD COLUMN；不声明 NOT NULL，兼容已有行的 NULL 值
            if "sendkey" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE notification_config "
                        "ADD COLUMN sendkey VARCHAR(256) DEFAULT ''"
                    )
                )
                logger.warning("notification_config 表已补充 sendkey 列（Server酱 通道）")
            if "token" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE notification_config "
                        "ADD COLUMN token VARCHAR(256) DEFAULT ''"
                    )
                )
                logger.warning("notification_config 表已补充 token 列（PushPlus 预留通道）")
        # channel 唯一索引（多通道化）；SQLite 老表单例一行，无重复值风险
        index_names = {ix["name"] for ix in inspector.get_indexes("notification_config")}
        if "ix_notification_config_channel" not in index_names:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX ix_notification_config_channel "
                        "ON notification_config (channel)"
                    )
                )
            logger.warning("notification_config 表已补充 channel 唯一索引（多通道化）")
    except Exception:
        logger.exception("检查/补充 notification_config 表结构失败，部分通知通道可能不可用")


def init_db() -> None:
    # noqa: F401  各域的 models 子包只是被 import 一下确保类注册到 Base.metadata 上，
    # 不在这里直接用——按域拆分后模型定义各自归属 common/stock/xhs，不再有一个统一的
    # app.models 聚合包
    from app.ai_trending import models as ai_trending_models  # noqa: F401
    from app.analysis import models as analysis_models  # noqa: F401
    from app.common import models as common_models  # noqa: F401
    from app.resource import models as resource_models  # noqa: F401
    from app.skills import models as skills_models  # noqa: F401
    from app.stock import models as stock_models  # noqa: F401
    from app.xhs import models as xhs_models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    # AI 热点推送记录表轻量迁移：存量库 create_all 不会给已存在表加列，
    # 这里幂等补 topic_id 列（新库 ORM 已建，函数内部自动跳过）
    from app.ai_trending.models.push_log import ensure_push_log_topic_id

    ensure_push_log_topic_id()
    # 老库兼容：通知配置补列（sendkey/token）+ channel 唯一索引（多通道化）
    _ensure_notification_config_schema()
