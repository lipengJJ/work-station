"""AI 热点定时推送控制器：/api/ai-trending/push/*（全部需要登录）。

只做参数校验与编排，业务逻辑在 services 层：
- GET  /config   推送配置（webhook_url 掩码、secret 只回 _set）
- PUT  /config   保存配置（校验失败 400；保存后 reschedule 定时任务）
- GET  /latest   最近一次推送记录（PushLogOut | null）
- POST /test     测试推送（5 分钟内存限频 429；失败也返回 200 + log 行）
"""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai_trending.models import AiTrendingPushConfig, AiTrendingPushLog
from app.ai_trending.schemas.push import (
    PushConfigIn,
    PushConfigOut,
    PushLogOut,
    PushTestIn,
)
from app.ai_trending.services.push_service import push_service
from app.ai_trending.services.push_webhook import mask_webhook_url, validate_webhook_url
from app.ai_trending.services.scheduler_jobs import reschedule_push_job
from app.core.database import get_db
from app.core.deps import get_current_user

router = APIRouter(prefix="/api/ai-trending/push", tags=["ai-trending-push"])

# 测试推送限频：进程内内存锁 + 时间戳（5 分钟 1 次，与 /refresh 同模式）
_TEST_LOCK = threading.Lock()
_last_test_push: float | None = None
TEST_COOLDOWN_SECONDS = 300

_PUSH_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def _to_config_out(cfg: AiTrendingPushConfig) -> PushConfigOut:
    """ORM → 出参：URL 掩码、secret 只回 _set。"""
    return PushConfigOut(
        enabled=cfg.enabled,
        webhook_url=mask_webhook_url(cfg.webhook_url or ""),
        webhook_secret_set=bool(cfg.webhook_secret),
        keyword=cfg.keyword,
        push_time=cfg.push_time,
        top_n=cfg.top_n,
        summary_prompt=cfg.summary_prompt,
    )


def _valid_push_time(value: str) -> bool:
    """HH:MM 且时 0-23、分 0-59。"""
    if not _PUSH_TIME_RE.match(value or ""):
        return False
    hour, minute = int(value[:2]), int(value[3:5])
    return 0 <= hour <= 23 and 0 <= minute <= 59


# ------------------------------------------------------------------ 配置 ----
@router.get("/config", deprecated=True)
def get_config(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> PushConfigOut:
    cfg = push_service.get_config(db)
    return _to_config_out(cfg)


@router.put("/config", deprecated=True)
def update_config(
    body: PushConfigIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> PushConfigOut:
    cfg = push_service.get_config(db)

    url = (body.webhook_url or "").strip()
    # 前端掩码回显值（含 ****）表示保持原值
    if url and "****" in url:
        url = cfg.webhook_url or ""
    elif url and not validate_webhook_url(url):
        raise HTTPException(
            400, "webhook_url 格式非法：需为 https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
        )
    if not _valid_push_time(body.push_time):
        raise HTTPException(400, "push_time 格式非法：需为 HH:MM 且时 0-23、分 0-59")
    if body.enabled and not url:
        raise HTTPException(400, "请先填写 Webhook URL 再开启推送")

    cfg.enabled = body.enabled
    cfg.webhook_url = url
    # secret：不传(None)=保持原值，传 ""=清除
    if body.webhook_secret is not None:
        cfg.webhook_secret = body.webhook_secret or None
    # keyword：不传(None)=保持原值，传 ""=清除
    if body.keyword is not None:
        cfg.keyword = body.keyword or None
    cfg.push_time = body.push_time
    cfg.top_n = body.top_n
    if body.summary_prompt is not None:
        cfg.summary_prompt = body.summary_prompt or None
    cfg.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.expire_all()
    # 读最新配置重调度定时任务
    reschedule_push_job(db)

    cfg = push_service.get_config(db)
    return _to_config_out(cfg)


# ------------------------------------------------------------------ 记录 ----
@router.get("/latest", deprecated=True)
def get_latest(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> PushLogOut | None:
    row = (
        db.query(AiTrendingPushLog)
        .order_by(AiTrendingPushLog.id.desc())
        .first()
    )
    return PushLogOut.model_validate(row) if row else None


# ------------------------------------------------------------------ 测试 ----
@router.post("/test", deprecated=True)
def test_push(
    body: PushTestIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> PushLogOut:
    global _last_test_push
    now = time.time()
    with _TEST_LOCK:
        if _last_test_push is not None:
            remaining = TEST_COOLDOWN_SECONDS - (now - _last_test_push)
            if remaining > 0:
                raise HTTPException(
                    429, f"测试推送过于频繁，请 {int(remaining) + 1} 秒后重试"
                )
        _last_test_push = now

    cfg = push_service.get_config(db)
    override = body.model_dump(exclude_none=True)
    # 测试覆盖语义：空串视为"不覆盖"（与 PUT 的 secret/keyword 区分），回退到已存配置
    if "webhook_url" in override and not (override["webhook_url"] or "").strip():
        override.pop("webhook_url")
    merged_url = (override.get("webhook_url") or cfg.webhook_url or "").strip()
    if not merged_url:
        raise HTTPException(400, "请先配置 Webhook URL 再测试推送")

    result = push_service.run_push(db, force=True, config_override=override)
    if result is None:
        raise HTTPException(400, "推送未执行：请检查推送配置")
    return result
