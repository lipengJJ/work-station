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


def _ensure_notification_config_sendkey() -> None:
    """
    轻量加列：老库的 notification_config 表可能没有 sendkey 列，而
    Base.metadata.create_all 只会建新表、不会 ALTER 已有表。
    方案：启动（init_db）时 inspect 一次，缺列则 ALTER TABLE 补上；任何异常只记日志，
    绝不让老库在启动/seed 时炸掉。进程内只检查一次。
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
        if "sendkey" in columns:
            return
        # SQLite 允许带 DEFAULT 的 ADD COLUMN；不声明 NOT NULL，兼容已有行的 NULL 值
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE notification_config "
                    "ADD COLUMN sendkey VARCHAR(256) DEFAULT ''"
                )
            )
        logger.warning("notification_config 表已补充 sendkey 列（Server酱 通道）")
    except Exception:
        logger.exception(
            "检查/补充 notification_config.sendkey 列失败，Server酱 通道可能不可用"
        )


def init_db() -> None:
    # noqa: F401  各域的 models 子包只是被 import 一下确保类注册到 Base.metadata 上，
    # 不在这里直接用——按域拆分后模型定义各自归属 common/stock/xhs，不再有一个统一的
    # app.models 聚合包
    from app.analysis import models as analysis_models  # noqa: F401
    from app.common import models as common_models  # noqa: F401
    from app.resource import models as resource_models  # noqa: F401
    from app.skills import models as skills_models  # noqa: F401
    from app.stock import models as stock_models  # noqa: F401
    from app.xhs import models as xhs_models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    # 老库补列（Server酱 sendkey）
    _ensure_notification_config_sendkey()
