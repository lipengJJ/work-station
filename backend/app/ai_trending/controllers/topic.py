"""AI 开发热点主题跟踪控制器：/api/ai-trending/topics/*（全部需要登录）。

只做参数校验与编排，业务逻辑在 services 层：
- topics CRUD（创建/更新/删除联动 APScheduler interval job）
- run-now 立即抓取（每主题 60s 内存限频 + running 防重入 + daemon 线程异步执行）
- items 主题命中列表（join hits+items 分页，items 字段对齐 TrendingItemOut）
- push-config 主题推送配置（channel 枚举/frequency 仅 daily/time HH:MM 校验；仅落库）
"""
from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.ai_trending.schemas.topic import (
    TopicCreateIn,
    TopicHitPage,
    TopicOut,
    TopicPushConfigIn,
    TopicPushConfigOut,
    TopicRunResultOut,
    TopicUpdateIn,
)
from app.ai_trending.services import topic_service
from app.core.database import get_db
from app.core.deps import get_current_user

router = APIRouter(prefix="/api/ai-trending", tags=["ai-trending-topic"])

VALID_SORTS = {"heat", "time"}


def _topic_or_404(db: Session, topic_id: int) -> Any:
    """取主题，不存在抛 404。"""
    topic = topic_service.get_topic(db, topic_id)
    if not topic:
        raise HTTPException(404, "主题不存在")
    return topic


# ------------------------------------------------------------------ 列表 ----
@router.get("/topics")
def list_topics(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> list[TopicOut]:
    """主题列表（created_at DESC，每条带 hit_count / next_run_at）。"""
    return [TopicOut(**t) for t in topic_service.list_topics(db)]


@router.post("/topics")
def create_topic(
    body: TopicCreateIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> TopicOut:
    """创建主题：name/keywords 必填；enabled 时注册 interval job。"""
    params = body.model_dump()
    return TopicOut(**topic_service.create_topic(db, params))


@router.get("/topics/{topic_id}")
def get_topic(
    topic_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> TopicOut:
    _topic_or_404(db, topic_id)
    topic = topic_service.get_topic(db, topic_id)
    return TopicOut(**topic_service.serialize_topic(db, topic))


@router.put("/topics/{topic_id}")
def update_topic(
    topic_id: int,
    body: TopicUpdateIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> TopicOut:
    """更新主题：全可选（只覆盖传入字段）；enabled/interval 变化自动重挂/注销 job。"""
    params = body.model_dump(exclude_unset=True)
    updated = topic_service.update_topic(db, topic_id, params)
    if not updated:
        raise HTTPException(404, "主题不存在")
    return TopicOut(**updated)


@router.delete("/topics/{topic_id}")
def delete_topic(
    topic_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> dict:
    """删除主题：注销 job + 显式删 topic_hit + 删主题（提示会清空该主题命中记录）。"""
    ok = topic_service.delete_topic(db, topic_id)
    if not ok:
        raise HTTPException(404, "主题不存在")
    return {"success": True}


# ------------------------------------------------------------------ 抓取 ----
@router.post("/topics/{topic_id}/run-now")
def run_topic_now(
    topic_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> TopicRunResultOut:
    """立即抓取：每主题 60s 限频（429）+ status=running 防重入（429）+ daemon 线程执行。"""
    topic = _topic_or_404(db, topic_id)
    if topic.status == "running":
        raise HTTPException(429, "该主题正在扫描中，请稍后重试")
    ok, message = topic_service.check_run_now_cooldown(topic_id)
    if not ok:
        raise HTTPException(429, message)

    def _worker() -> None:
        try:
            topic_service.run_topic_scan(topic_id)
        except Exception:  # noqa: BLE001  后台线程兜底
            from loguru import logger

            logger.exception(f"主题 {topic_id} run-now 后台线程异常")

    threading.Thread(target=_worker, daemon=True).start()
    return TopicRunResultOut(success=True, message="已触发抓取，约 10-30 秒后完成")


# ------------------------------------------------------------------ 命中 ----
@router.get("/topics/{topic_id}/items")
def list_topic_items(
    topic_id: int,
    sort: str = Query("heat", max_length=8),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> TopicHitPage:
    """主题命中列表：join hits+items（matched=True）；sort=heat 默认 / time 按 first_seen_at。"""
    _topic_or_404(db, topic_id)
    if sort not in VALID_SORTS:
        raise HTTPException(400, f"未知排序: {sort}（可选：heat/time）")
    result = topic_service.list_topic_items(
        db, topic_id, sort=sort, page=page, page_size=page_size
    )
    return TopicHitPage(**result)


# ------------------------------------------------------------ 推送配置 ----
@router.get("/topics/{topic_id}/push-config")
def get_topic_push_config(
    topic_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> TopicPushConfigOut:
    _topic_or_404(db, topic_id)
    cfg = topic_service.get_push_config(db, topic_id)
    return TopicPushConfigOut(**cfg)


@router.put("/topics/{topic_id}/push-config")
def update_topic_push_config(
    topic_id: int,
    body: TopicPushConfigIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> TopicPushConfigOut:
    """保存推送配置：校验 channel/frequency/time（Pydantic）→ 仅落库，不触发真实发送。"""
    _topic_or_404(db, topic_id)
    cfg = topic_service.set_push_config(db, topic_id, body.model_dump())
    return TopicPushConfigOut(**cfg)
