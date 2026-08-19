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
            if "smtp_host" not in columns:
                conn.execute(text("ALTER TABLE notification_config ADD COLUMN smtp_host VARCHAR(255) DEFAULT ''"))
                conn.execute(text("ALTER TABLE notification_config ADD COLUMN smtp_port INTEGER DEFAULT 465"))
                conn.execute(text("ALTER TABLE notification_config ADD COLUMN smtp_user VARCHAR(255) DEFAULT ''"))
                conn.execute(text("ALTER TABLE notification_config ADD COLUMN smtp_password VARCHAR(255) DEFAULT ''"))
                conn.execute(text("ALTER TABLE notification_config ADD COLUMN smtp_use_ssl BOOLEAN DEFAULT 1"))
                conn.execute(text("ALTER TABLE notification_config ADD COLUMN email_to VARCHAR(512) DEFAULT ''"))
                logger.warning("notification_config 表已补充 email 通道相关列（SMTP）")
        # 多实例化：移除 channel 唯一索引（同类型可配多个实例）；老库补 remark 列；
        # SQLite 老表内嵌 UNIQUE 约束生成的 autoindex 无法 DROP，只能重建表移除。
        with engine.begin() as conn:
            index_names = {ix["name"] for ix in inspector.get_indexes("notification_config")}
            if "ix_notification_config_channel" in index_names:
                conn.execute(text("DROP INDEX ix_notification_config_channel"))
                logger.warning("notification_config 表已移除 channel 唯一索引（多实例化）")
            if "remark" not in columns:
                conn.execute(
                    text("ALTER TABLE notification_config ADD COLUMN remark VARCHAR(64) DEFAULT ''")
                )
                logger.warning("notification_config 表已补充 remark 列（多实例备注名）")
            auto_rows = conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND tbl_name='notification_config' AND name LIKE 'sqlite_autoindex%'"
                )
            ).fetchall()
            if auto_rows:
                # 这个重建分支只在「从没跑过多实例化迁移」的老库上触发；此时上面几步已经把
                # email 相关列加上了，这里的列表必须跟着补，否则重建完这些列就白加了。
                conn.execute(
                    text(
                        "CREATE TABLE notification_config_new ("
                        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                        "channel VARCHAR(32) NOT NULL DEFAULT 'wecom_webhook', "
                        "remark VARCHAR(64) DEFAULT '', "
                        "webhook_url VARCHAR(512) DEFAULT '', "
                        "sendkey VARCHAR(256) DEFAULT '', "
                        "token VARCHAR(256) DEFAULT '', "
                        "enabled BOOLEAN DEFAULT 0, "
                        "mention_all BOOLEAN DEFAULT 0, "
                        "smtp_host VARCHAR(255) DEFAULT '', "
                        "smtp_port INTEGER DEFAULT 465, "
                        "smtp_user VARCHAR(255) DEFAULT '', "
                        "smtp_password VARCHAR(255) DEFAULT '', "
                        "smtp_use_ssl BOOLEAN DEFAULT 1, "
                        "email_to VARCHAR(512) DEFAULT '', "
                        "created_at DATETIME, "
                        "updated_at DATETIME)"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO notification_config_new (id, channel, remark, webhook_url, "
                        "sendkey, token, enabled, mention_all, smtp_host, smtp_port, smtp_user, "
                        "smtp_password, smtp_use_ssl, email_to, created_at, updated_at) "
                        "SELECT id, channel, COALESCE(remark, ''), webhook_url, sendkey, token, "
                        "enabled, mention_all, COALESCE(smtp_host, ''), COALESCE(smtp_port, 465), "
                        "COALESCE(smtp_user, ''), COALESCE(smtp_password, ''), COALESCE(smtp_use_ssl, 1), "
                        "COALESCE(email_to, ''), created_at, updated_at FROM notification_config"
                    )
                )
                conn.execute(text("DROP TABLE notification_config"))
                conn.execute(text("ALTER TABLE notification_config_new RENAME TO notification_config"))
                logger.warning("notification_config 表已重建（移除 channel 唯一约束，支持多实例）")

    except Exception:
        logger.exception("检查/补充 notification_config 表结构失败，部分通知通道可能不可用")


def _ensure_tracking_ai_schema() -> None:
    """追踪任务 AI 筛选相关列（任务表 3 列 + 命中表 6 列，幂等）。"""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        task_adds = {
            "ai_filter_enabled": "BOOLEAN DEFAULT 0",
            "ai_filter_prompt": "TEXT",
            "ai_filter_min_confidence": "FLOAT DEFAULT 0.6",
        }
        hit_adds = {
            "ai_process_status": "VARCHAR(16) DEFAULT 'pending'",
            "ai_structured_data": "TEXT",
            "ai_is_match": "BOOLEAN",
            "ai_match_reason": "TEXT",
            "ai_confidence": "FLOAT",
            "ai_raw_response": "TEXT",
        }
        with engine.begin() as conn:
            if "xhs_tracking_tasks" in inspector.get_table_names():
                cols = {c["name"] for c in inspector.get_columns("xhs_tracking_tasks")}
                for name, ddl in task_adds.items():
                    if name not in cols:
                        conn.execute(text(f"ALTER TABLE xhs_tracking_tasks ADD COLUMN {name} {ddl}"))
            if "xhs_tracking_hits" in inspector.get_table_names():
                cols2 = {c["name"] for c in inspector.get_columns("xhs_tracking_hits")}
                for name, ddl in hit_adds.items():
                    if name not in cols2:
                        conn.execute(text(f"ALTER TABLE xhs_tracking_hits ADD COLUMN {name} {ddl}"))
        logger.warning("追踪任务 AI 筛选相关列已补充")
    except Exception:
        logger.exception("补充追踪任务 AI 筛选列失败")


def _ensure_tracking_task_notify_schema() -> None:
    """追踪任务表补机器人通知相关列（幂等，老库兼容）。"""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "xhs_tracking_tasks" not in inspector.get_table_names():
            return
        columns = {c["name"] for c in inspector.get_columns("xhs_tracking_tasks")}
        adds = {
            "notify_enabled": "BOOLEAN DEFAULT 0",
            "notify_channel_ids": "TEXT DEFAULT '[]'",
            "notify_time_start": "VARCHAR(8)",
            "notify_time_end": "VARCHAR(8)",
            "notify_frequency": "VARCHAR(16) DEFAULT 'realtime'",
            "notify_only_on_hit": "BOOLEAN DEFAULT 1",
            "notify_pending_hits": "INTEGER DEFAULT 0",
            "notify_pending_since": "DATETIME",
        }
        with engine.begin() as conn:
            for name, ddl in adds.items():
                if name not in columns:
                    conn.execute(text(f"ALTER TABLE xhs_tracking_tasks ADD COLUMN {name} {ddl}"))
        logger.warning("xhs_tracking_tasks 表已补充机器人通知相关列")
    except Exception:
        logger.exception("补充 xhs_tracking_tasks 通知列失败")


def init_db() -> None:
    # noqa: F401  各域的 models 子包只是被 import 一下确保类注册到 Base.metadata 上，
    # 不在这里直接用——按域拆分后模型定义各自归属 common/stock/xhs，不再有一个统一的
    # app.models 聚合包
    from app.analysis import models as analysis_models  # noqa: F401
    from app.hotlist import models as hotlist_models  # noqa: F401
    from app.common import models as common_models  # noqa: F401
    from app.resource import models as resource_models  # noqa: F401
    from app.skills import models as skills_models  # noqa: F401
    from app.stock import models as stock_models  # noqa: F401
    from app.xhs import models as xhs_models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    # 老库兼容：通知配置补列（sendkey/token）+ channel 唯一索引（多通道化）
    _ensure_notification_config_schema()
    _ensure_tracking_task_notify_schema()
    _ensure_tracking_ai_schema()
