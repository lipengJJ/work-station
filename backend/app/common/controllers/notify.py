from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.database import get_db
from app.common.models import NotificationConfig, NotificationLog
from app.common.schemas.notify import (ChannelList,
    ManualSendIn,
    NotificationConfigIn,
    NotificationConfigOut,
    NotificationLogPage,
    SendResult,
    TestSendIn,
    TestAllResult,)
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
    """全部通道配置（多实例化后按实例一行，channel 可重复）。"""
    return list_configs(db)


@router.post("/configs", response_model=NotificationConfigOut)
def create_config(
    body: NotificationConfigIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """新增通道实例（同类型可配多个，remark 备注名区分）。"""
    if not body.channel:
        raise HTTPException(400, "缺少渠道类型")
    config = NotificationConfig(
        channel=body.channel,
        remark=body.remark,
        webhook_url=body.webhook_url,
        sendkey=body.sendkey,
        token=body.token,
        enabled=body.enabled,
        mention_all=body.mention_all,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


@router.put("/configs/{config_id}", response_model=NotificationConfigOut)
def update_config(
    config_id: int,
    body: NotificationConfigIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """更新通道实例（字段留空 = 不修改）。"""
    config = db.get(NotificationConfig, config_id)
    if not config:
        raise HTTPException(404, "通道实例不存在")
    if body.webhook_url:
        config.webhook_url = body.webhook_url
    if body.sendkey:
        config.sendkey = body.sendkey
    if body.token:
        config.token = body.token
    if body.remark:
        config.remark = body.remark
    config.enabled = body.enabled
    config.mention_all = body.mention_all
    db.commit()
    db.refresh(config)
    return config


@router.delete("/configs/{config_id}")
def delete_config(
    config_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """删除通道实例。"""
    config = db.get(NotificationConfig, config_id)
    if not config:
        raise HTTPException(404, "通道实例不存在")
    db.delete(config)
    db.commit()
    return {"success": True}


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


@router.post("/test", response_model=TestAllResult)
def test_send(
    body: TestSendIn | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """手动发送测试消息：不传 channel = 向所有启用实例发送；传 channel+remark = 仅测试该实例。"""
    content = (
        "【统一工作台】消息通知测试\n"
        "这是一条测试消息，如果你能收到，说明当前通知通道配置正确。"
    )
    if body and body.channel:
        target = next(
            (c for c in list_configs(db) if c.channel == body.channel and c.remark == (body.remark or "")),
            None,
        )
        if not target:
            return TestAllResult(success=False, total=0, success_count=0, message="未找到该渠道实例")
        ok, msg = send_by_config(target, "测试消息", content, msgtype="text")
        if not ok:
            missing = config_missing_hint(target)
            if missing:
                ok, msg = False, missing
        log_notification(db, target.channel, "测试消息", content, "success" if ok else "failed", None if ok else msg)
        return TestAllResult(
            success=ok, total=1, success_count=1 if ok else 0,
            message="该渠道发送成功" if ok else f"发送失败：{msg}",
            results=[{"channel": target.channel, "remark": target.remark, "success": ok, "message": msg}],
        )
    configs = [c for c in list_configs(db) if c.enabled]
    if not configs:
        return TestAllResult(success=False, total=0, success_count=0, message="还没有启用的通知渠道")
    ok_count = 0
    results = []
    for cfg in configs:
        missing = config_missing_hint(cfg)
        if missing:
            results.append({"channel": cfg.channel, "remark": cfg.remark, "success": False, "message": missing})
            continue
        ok, msg = send_by_config(cfg, "测试消息", content, msgtype="text")
        results.append({"channel": cfg.channel, "remark": cfg.remark, "success": ok, "message": msg})
        if ok:
            ok_count += 1
        log_notification(
            db, cfg.channel, "测试消息", content, "success" if ok else "failed", None if ok else msg,
        )
    return TestAllResult(
        success=ok_count == len(configs),
        total=len(configs),
        success_count=ok_count,
        message=f"{ok_count}/{len(configs)} 个渠道发送成功",
        results=results,
    )


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


