"""主题管理：/api/hotlist/topics/*（全部需要登录）。

- GET/POST/PUT/DELETE /topics            主题 CRUD
- GET  /topics/{id}/sources              源列表（健康状态 + 近 7 天贡献数）
- PUT  /topics/{id}/sources              批量开关（all_on/all_off/set）
- POST /topics/{id}/sources/import-opml  导入（上传文本或传 URL）
- POST /topics/{id}/sources/disable-stale  一键关闭连续失败 >=5 的源
- DELETE /topics/{id}/sources/{source_id}  解除关联
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.hotlist.models import HotTopic
from app.hotlist.schemas.topic import (
    ImportOpmlIn,
    OpmlImportResult,
    SemanticPreviewIn,
    SemanticPreviewOut,
    TopicIn,
    TopicOut,
    TopicSourceBatchIn,
    TopicSourceOut,
    TopicUpdateIn,
)
from app.hotlist.services import opml_service, topic_service

router = APIRouter(prefix="/api/hotlist/topics", tags=["hotlist-topics"])

# 规模护栏：单主题启用源数超过该值前端必须给出明确警告
MAX_ENABLED_SOURCES_WARN = 100


@router.get("")
def list_topics(
    db: Session = Depends(get_db), _=Depends(get_current_user)
) -> list[TopicOut]:
    topics = topic_service.list_topics(db)
    out = []
    for topic in topics:
        item = TopicOut.model_validate(topic)
        item.enabled_source_count = topic_service.source_count_for_topic(
            db, topic.id
        )
        out.append(item)
    return out


@router.post("")
def create_topic(
    data: TopicIn, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> TopicOut:
    try:
        topic = topic_service.create_topic(db, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    out = TopicOut.model_validate(topic)
    out.enabled_source_count = 0
    return out


@router.get("/{topic_id}")
def get_topic(
    topic_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> TopicOut:
    topic = topic_service.get_topic(db, topic_id)
    if topic is None:
        raise HTTPException(404, "主题不存在")
    out = TopicOut.model_validate(topic)
    out.enabled_source_count = topic_service.source_count_for_topic(
        db, topic_id
    )
    return out


@router.put("/{topic_id}")
def update_topic(
    topic_id: int,
    data: TopicUpdateIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> TopicOut:
    try:
        topic = topic_service.update_topic(db, topic_id, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    out = TopicOut.model_validate(topic)
    out.enabled_source_count = topic_service.source_count_for_topic(
        db, topic_id
    )
    return out


@router.delete("/{topic_id}")
def delete_topic(
    topic_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> dict:
    try:
        topic_service.delete_topic(db, topic_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


# ------------------------------------------------------------ 源关联 ----

@router.get("/{topic_id}/sources")
def list_sources(
    topic_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> list[TopicSourceOut]:
    _ensure_topic(db, topic_id)
    return topic_service.list_topic_sources(db, topic_id)


@router.put("/{topic_id}/sources")
def batch_sources(
    topic_id: int,
    data: TopicSourceBatchIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> dict:
    _ensure_topic(db, topic_id)
    try:
        changed = topic_service.batch_set_sources(
            db, topic_id, data.mode, data.source_ids
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    enabled = topic_service.source_count_for_topic(db, topic_id)
    if enabled > MAX_ENABLED_SOURCES_WARN:
        logger.warning(
            f"主题 {topic_id} 启用源数达 {enabled}，超过规模护栏 {MAX_ENABLED_SOURCES_WARN}"
        )
    return {"ok": True, "changed": changed, "enabled_count": enabled}


@router.post("/{topic_id}/sources/import-opml")
def import_opml(
    topic_id: int,
    data: ImportOpmlIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> OpmlImportResult:
    _ensure_topic(db, topic_id)
    try:
        content = data.opml_text
        if not (content or "").strip() and data.opml_url:
            content = opml_service.fetch_opml(data.opml_url)
        if not (content or "").strip():
            raise ValueError("请提供 OPML 文本或 URL")
        filename = (
            data.opml_url.rstrip("/").split("/")[-1][:100]
            if data.opml_url
            else ""
        )
        imported_from = f"opml:{filename}" if filename else "opml:paste"
        # topic 场景：只关联主题（group_id=None），源不额外归组
        result = opml_service.import_opml(
            db,
            content,
            group_id=None,
            topic_id=topic_id,
            imported_from=imported_from,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result


@router.post("/{topic_id}/sources/disable-stale")
def disable_stale(
    topic_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> dict:
    _ensure_topic(db, topic_id)
    changed = topic_service.disable_stale_sources(db, topic_id)
    return {"ok": True, "disabled": changed}


@router.delete("/{topic_id}/sources/{source_id}")
def detach_source(
    topic_id: int,
    source_id: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> dict:
    _ensure_topic(db, topic_id)
    try:
        topic_service.detach_source(db, topic_id, source_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


def _ensure_topic(db: Session, topic_id: int) -> HotTopic:
    topic = topic_service.get_topic(db, topic_id)
    if topic is None:
        raise HTTPException(404, "主题不存在")
    return topic


@router.post("/{topic_id}/semantic-preview", response_model=SemanticPreviewOut)
def semantic_preview(
    topic_id: int,
    payload: SemanticPreviewIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> SemanticPreviewOut:
    """语义检索预览：用临时关注需求生成查询向量并召回近 N 天候选（不落库）。"""
    topic = topic_service.get_topic(db, topic_id)
    if topic is None:
        raise HTTPException(404, "主题不存在")
    try:
        result = topic_service.preview_semantic_retrieval(
            db,
            topic,
            payload.interest_query,
            period_days=payload.period_days,
            similarity_threshold=payload.similarity_threshold,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return SemanticPreviewOut(**result)
