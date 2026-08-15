from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.database import get_db
from app.common.models import NotificationConfig, NotificationLog
from app.common.schemas.notify import (
    ChannelList,
    ManualSendIn,
    NotificationConfigIn,
    NotificationConfigOut,
    NotificationLogPage,
    SendResult,
    TestSendIn,
)
from app.common.services.notify_service import (
    config_missing_hint,
    get_config_by_channel,
    list_channel_infos,
    list_configs,
    log_notification,
    normalize_channel,
    send_by_config,
    upsert_config,
)

router = APIRouter(prefix="/api/notify", tags=["notify"])


def _pick_channel(db: Session, channel: str | None) -> NotificationConfig | None:
    """
    选择发送/测试用的通道配置：
    - 指定 channel 且该通道已配置 → 用它；
    - 未指定 → 第一个已启用的通道（配置是否齐全由调用方 config_missing_hint 给出友好提示）；
    - 都没有 → 返回 None（调用方转成友好提示，保持 200 + success=false 语义）。
    """
    if channel:
        config = get_config_by_channel(db, channel)
        if config:
            return config
        return None

    for config in list_configs(db):
        if config.enabled:
            return config
    return None


def _channel_unavailable_msg(channel: str | None) -> str:
    return (
        f"通道 {channel} 尚未配置，请先保存配置"
        if channel
        else "尚未启用任何通知通道，请先在系统设置中配置并启用"
    )


def _default_config_out(channel: str) -> NotificationConfigOut:
    """未配置的通道返回默认值（不落库），前端少一层空值判断。"""
    now = datetime.now(timezone.utc)
    return NotificationConfigOut(
        id=0,
        channel=normalize_channel(channel),
        webhook_url="",
        sendkey="",
        token="",
        enabled=False,
        mention_all=False,
        created_at=now,
        updated_at=now,
    )


@router.get("/channels", response_model=ChannelList)
def list_channels(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """通道目录（G4 公共入口）：全部已注册通道的元信息 + 配置/启用状态，供其他模块查询可用通知方式。"""
    return ChannelList(channels=list_channel_infos(db))


@router.get("/configs", response_model=list[NotificationConfigOut])
def get_configs(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """全部通道配置（多通道化后按 channel 一行）。"""
    return list_configs(db)


@router.get("/config/{channel}", response_model=NotificationConfigOut)
def get_config(
    channel: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """单通道配置；尚未保存过时返回默认值（不落库，保存时才写）。"""
    config = get_config_by_channel(db, channel)
    return config if config else _default_config_out(channel)


@router.put("/config/{channel}", response_model=NotificationConfigOut)
def save_config(
    channel: str,
    body: NotificationConfigIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """保存单通道配置（upsert：按 channel 覆盖，老库单例数据自动承接为 wecom_webhook 行）。"""
    return upsert_config(
        db,
        channel,
        webhook_url=body.webhook_url,
        sendkey=body.sendkey,
        token=body.token,
        enabled=body.enabled,
        mention_all=body.mention_all,
    )


@router.post("/test", response_model=SendResult)
def test_send(
    body: TestSendIn | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """手动触发一条测试消息到指定通道（不传 channel = 第一个启用通道；不要求已启用，方便先测后开）。"""
    channel = (body.channel if body else None) or None
    config = _pick_channel(db, channel)
    if config is None:
        return SendResult(success=False, message=_channel_unavailable_msg(channel))
    missing = config_missing_hint(config)
    if missing:
        return SendResult(success=False, message=missing)
    content = (
        "【统一工作台】消息通知测试\n"
        "这是一条测试消息，如果你能收到，说明当前通知通道配置正确。"
    )
    ok, msg = send_by_config(config, "测试消息", content, msgtype="text")
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
    """手动发送一条自定义内容到指定通道（不传 channel = 第一个启用通道；企业微信 text/markdown；Server酱 标题+markdown 正文）。"""
    config = _pick_channel(db, body.channel or None)
    if config is None:
        return SendResult(success=False, message=_channel_unavailable_msg(body.channel or None))
    missing = config_missing_hint(config)
    if missing:
        return SendResult(success=False, message=missing)
    content = body.content.strip() or f"【统一工作台】{body.title}"
    ok, msg = send_by_config(config, body.title, content, msgtype=body.msgtype)
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
