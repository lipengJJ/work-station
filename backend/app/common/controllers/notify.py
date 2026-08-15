from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.database import get_db
from app.common.models import NotificationConfig, NotificationLog
from app.common.schemas.notify import (
    ManualSendIn,
    NotificationConfigIn,
    NotificationConfigOut,
    NotificationLogPage,
    SendResult,
)
from app.common.services.notify_service import log_notification, send_wecom_message

router = APIRouter(prefix="/api/notify", tags=["notify"])

# 单例配置固定 id：表里最多一行，保存时按这个 id 覆盖
_SINGLETON_ID = 1


def _get_config(db: Session) -> NotificationConfig | None:
    """读单例配置（按 id 最小的一条；正常只会有一行）。"""
    return db.get(NotificationConfig, _SINGLETON_ID)


@router.get("/config", response_model=NotificationConfigOut)
def get_config(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """获取当前通知配置；尚未保存过时返回默认值（不落库，保存时才写）。"""
    config = _get_config(db)
    if config:
        return config
    now = datetime.now(timezone.utc)
    return NotificationConfigOut(
        id=_SINGLETON_ID,
        channel="wecom_webhook",
        webhook_url="",
        enabled=False,
        mention_all=False,
        created_at=now,
        updated_at=now,
    )


@router.put("/config", response_model=NotificationConfigOut)
def save_config(
    body: NotificationConfigIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """保存通知配置（单例 upsert：不存在则新建 id=1，存在则覆盖）。"""
    config = _get_config(db)
    if not config:
        config = NotificationConfig(id=_SINGLETON_ID)
        db.add(config)
    config.channel = body.channel or "wecom_webhook"
    config.webhook_url = (body.webhook_url or "").strip()
    config.enabled = body.enabled
    config.mention_all = body.mention_all
    db.commit()
    db.refresh(config)
    return config


@router.post("/test", response_model=SendResult)
def test_send(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """手动触发一条测试消息到已配置的 webhook（不要求已启用，方便先测后开）。"""
    config = _get_config(db)
    if not config or not (config.webhook_url or "").strip():
        return SendResult(success=False, message="尚未配置 webhook 地址，请先填写并保存")
    content = (
        "【统一工作台】消息通知测试\n"
        "这是一条测试消息，如果你能收到，说明企业微信机器人配置正确。"
    )
    ok, msg = send_wecom_message(config.webhook_url, content)
    log_notification(
        db,
        config.channel,
        "测试消息",
        content,
        "success" if ok else "failed",
        None if ok else msg,
    )
    return SendResult(success=ok, message=msg)


@router.post("/send", response_model=SendResult)
def manual_send(
    body: ManualSendIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """手动发送一条自定义内容（text 或 markdown），供临时通知/联调用。"""
    config = _get_config(db)
    if not config or not (config.webhook_url or "").strip():
        return SendResult(success=False, message="尚未配置 webhook 地址，请先填写并保存")
    content = body.content.strip() or f"【统一工作台】{body.title}"
    ok, msg = send_wecom_message(config.webhook_url, content, msgtype=body.msgtype)
    log_notification(
        db,
        config.channel,
        body.title,
        content,
        "success" if ok else "failed",
        None if ok else msg,
    )
    return SendResult(success=ok, message=msg)


@router.get("/logs", response_model=NotificationLogPage)
def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """发送记录（分页，最近的在前）。"""
    total = db.query(NotificationLog).count()
    rows = (
        db.query(NotificationLog)
        .order_by(NotificationLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return NotificationLogPage(items=rows, total=total, page=page, page_size=page_size)
