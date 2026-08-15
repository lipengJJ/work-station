"""
测试公共环境（conftest）：

- 使用独立的临时 SQLite 数据库，绝不触碰生产 workbench.db；
- 必须在导入任何 app.* 模块之前设置 WORKBENCH_DATABASE_URL（app.core.database 在
  import 时就会基于 settings.database_url 创建 engine/SessionLocal）。
"""
from __future__ import annotations

import os
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="workbench_notify_test_")
os.environ["WORKBENCH_DATABASE_URL"] = f"sqlite:///{_TMP_DIR}/test_notify.db"

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# 导入 app 包（此时环境变量已生效，engine 指向临时库）
from app.common.controllers.notify import router as notify_router
from app.common.models import NotificationConfig, NotificationLog, Task, User  # noqa: F401
from app.core.database import Base, SessionLocal, engine
from app.core.security import create_access_token


@pytest.fixture()
def db():
    """建表 + 提供一个可用的会话；用例结束清空所有表。"""
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    """只挂载 notify 路由的最小 FastAPI 应用（真实 JWT 鉴权 + 真实 get_db）。"""
    app = FastAPI()
    app.include_router(notify_router)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_headers(db):
    """创建测试用户并返回带合法 JWT 的请求头。"""
    user = User(username="tester", hashed_password="not-used")
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token("tester")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- 造数工具 ----

def seed_config(
    db,
    *,
    enabled: bool = True,
    webhook_url: str = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
    mention_all: bool = False,
    channel: str = "wecom_webhook",
    sendkey: str = "",
    token: str = "",
) -> NotificationConfig:
    """写入/覆盖指定 channel 的配置（多通道化：每通道一行，channel 唯一）。"""
    cfg = (
        db.query(NotificationConfig)
        .filter(NotificationConfig.channel == channel)
        .first()
    )
    if cfg is None:
        cfg = NotificationConfig(channel=channel)
        db.add(cfg)
    cfg.webhook_url = webhook_url
    cfg.sendkey = sendkey
    cfg.token = token
    cfg.enabled = enabled
    cfg.mention_all = mention_all
    db.commit()
    db.refresh(cfg)
    return cfg


_UNSET = object()


def seed_task(
    db,
    *,
    status: str = "success",
    task_type: str = "xhs_search",
    module: str = "xhs",
    params: dict | None = None,
    result_summary: str | None = "采集到 12 篇笔记",
    started_at: object = _UNSET,
    finished_at: object = _UNSET,
) -> Task:
    """写入一条任务记录并返回（含自增 id）。

    默认 started_at/finished_at 取当前时间；显式传 None 会保持 None（用于测试
    「任务没有起止时间」的场景）。
    """
    now = datetime.now(timezone.utc)
    task = Task(
        module=module,
        task_type=task_type,
        status=status,
        params=params or {"keyword": "测试关键词"},
        result_summary=result_summary,
        created_at=now,
        started_at=now if started_at is _UNSET else started_at,
        finished_at=now if finished_at is _UNSET else finished_at,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_logs(db) -> list[NotificationLog]:
    """读取全部发送记录（按 id 升序，方便断言顺序）。"""
    return (
        db.query(NotificationLog)
        .order_by(NotificationLog.id.asc())
        .all()
    )
