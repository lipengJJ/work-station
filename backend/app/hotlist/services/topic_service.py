"""主题 CRUD + slug 生成 + 语义检索预览（Phase 5）。

- slug：创建时按 name 生成候选值但允许改；生成后不允许修改（已发布报告路径断链）。
- 源关联 / 失效源置灰归 topic_source_service；待抓源解析归 crawl_service。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
import secrets
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session

from app.hotlist.models import (
    HotTopic,
    HotTopicEmbedding,
    HotTopicSource,
)
from app.hotlist.schemas.topic import TopicIn, TopicUpdateIn

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def generate_slug(name: str) -> str:
    """按 name 生成 URL 安全的 ASCII slug；生成不了就退到随机后缀。"""
    base = _SLUG_RE.sub("-", (name or "").lower().strip()).strip("-")
    if len(base) < 2:
        base = f"topic-{secrets.token_hex(3)}"
    return base[:48]


def validate_slug(
    db: Session,
    slug: str,
    exclude_id: Optional[int] = None,
) -> str:
    """slug 合法性 + 唯一性校验（排除自身）。"""
    slug = (slug or "").strip()
    if not slug or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", slug):
        raise ValueError("slug 只允许小写字母/数字/连字符，且不能以连字符开头")
    q = db.query(HotTopic).filter(HotTopic.slug == slug)
    if exclude_id is not None:
        q = q.filter(HotTopic.id != exclude_id)
    if q.first() is not None:
        raise ValueError(f"slug 已存在: {slug}")
    return slug


# ---------------------------------------------------------------- CRUD ----

def create_topic(db: Session, data: TopicIn) -> HotTopic:
    slug = validate_slug(db, data.slug or generate_slug(data.name))
    topic = HotTopic(
        name=data.name.strip(),
        slug=slug,
        description=data.description,
        enabled=data.enabled,
        sort_order=data.sort_order,
        setup_done=data.setup_done,
        skill_key=data.skill_key,
        template_key=data.template_key,
        extra_question=data.extra_question,
        interest_query=data.interest_query,
        retrieval_mode=data.retrieval_mode,
        similarity_threshold=data.similarity_threshold,
        retrieval_size=data.retrieval_size,
        digest_strategy=data.digest_strategy,
        digest_period=data.digest_period,
        digest_cron=data.digest_cron,
        max_items=data.max_items,
        shortlist_size=data.shortlist_size,
        fulltext_size=data.fulltext_size,
        compare_with_previous=data.compare_with_previous,
        publish_enabled=data.publish_enabled,
        publish_formats=json.dumps(data.publish_formats, ensure_ascii=False),
        report_notify_enabled=data.report_notify_enabled,
        report_notify_channel_ids=json.dumps(data.report_notify_channel_ids),
        report_notify_time_start=data.report_notify_time_start,
        report_notify_time_end=data.report_notify_time_end,
        hit_notify_enabled=data.hit_notify_enabled,
        hit_notify_channel_ids=json.dumps(data.hit_notify_channel_ids),
        hit_notify_time_start=data.hit_notify_time_start,
        hit_notify_time_end=data.hit_notify_time_end,
        hit_notify_frequency=data.hit_notify_frequency,
        hit_notify_only_on_hit=data.hit_notify_only_on_hit,
        hit_notify_pending_hits=data.hit_notify_pending_hits,
        hit_notify_pending_since=data.hit_notify_pending_since,
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return topic


def update_topic(db: Session, topic_id: int, data: TopicUpdateIn) -> HotTopic:
    topic = db.get(HotTopic, topic_id)
    if topic is None:
        raise ValueError("主题不存在")
    updates = data.model_dump(exclude_unset=True)
    # slug 不允许修改（无论传没传都忽略）
    updates.pop("slug", None)
    if "name" in updates and updates["name"]:
        updates["name"] = updates["name"].strip()
    if "publish_formats" in updates and updates["publish_formats"] is not None:
        updates["publish_formats"] = json.dumps(
            updates["publish_formats"], ensure_ascii=False
        )
    if (
        "report_notify_channel_ids" in updates
        and updates["report_notify_channel_ids"] is not None
    ):
        updates["report_notify_channel_ids"] = json.dumps(
            updates["report_notify_channel_ids"]
        )
    if (
        "hit_notify_channel_ids" in updates
        and updates["hit_notify_channel_ids"] is not None
    ):
        updates["hit_notify_channel_ids"] = json.dumps(
            updates["hit_notify_channel_ids"]
        )
    old_interest = topic.interest_query  # setattr 前记录旧值
    for key, value in updates.items():
        setattr(topic, key, value)
    # 关注需求变化：使主题向量失效（删除行，下次 ensure 补算），避免旧需求向量被误用
    if (
        "interest_query" in updates
        and updates["interest_query"] is not None
        and updates["interest_query"] != (old_interest or "")
    ):
        db.query(HotTopicEmbedding).filter(
            HotTopicEmbedding.topic_id == topic_id
        ).delete()
        # 需求变更后旧语义命中不可再推送（query_hash 不匹配）
        from app.hotlist.models import HotSemanticHit
        db.query(HotSemanticHit).filter(
            HotSemanticHit.topic_id == topic_id, HotSemanticHit.notified.is_(False)
        ).delete()
    db.commit()
    db.refresh(topic)
    return topic


def delete_topic(db: Session, topic_id: int) -> None:
    topic = db.get(HotTopic, topic_id)
    if topic is None:
        raise ValueError("主题不存在")
    db.query(HotTopicSource).filter(
        HotTopicSource.topic_id == topic_id
    ).delete()
    # 报告保留（内容有快照，主题删了历史报告仍可读）；不级联删
    db.delete(topic)
    db.commit()


def get_topic(db: Session, topic_id: int) -> Optional[HotTopic]:
    return db.get(HotTopic, topic_id)


def get_topic_by_slug(db: Session, slug: str) -> Optional[HotTopic]:
    return db.query(HotTopic).filter(HotTopic.slug == slug).first()


def list_topics(db: Session) -> list[HotTopic]:
    return (
        db.query(HotTopic)
        .order_by(HotTopic.sort_order.asc(), HotTopic.id.asc())
        .all()
    )


def preview_semantic_retrieval(
    db: Session,
    topic: HotTopic,
    interest_query: str,
    period_days: int = 7,
    similarity_threshold: float | None = None,
    limit: int = 20,
) -> dict:
    """语义检索预览：用临时 interest_query 生成查询向量（不落库，避免不必要的向量费用），
    取近 period_days 候选池做语义召回，返回索引统计 + Top 结果。"""
    from app.common.services.embedding_config import (
        get_embedding_api_key,
        get_embedding_dimension,
        get_embedding_model,
        get_embedding_provider,
    )
    from app.common.services.embedding_gateway.base import (
        EmbeddingRequest,
        TASK_QUERY,
    )
    from app.common.services.embedding_gateway.service import build_model_key, embed
    from app.hotlist.services import embedding_service
    from app.hotlist.services.topic_report_service import fetch_candidate_pool

    provider = get_embedding_provider(db)
    model = get_embedding_model(db)
    dimension = get_embedding_dimension(db)
    api_key = get_embedding_api_key(db)
    if not api_key:
        raise ValueError("未配置 Embedding API Key（系统设置 → API 配置 → embedding_*）")
    model_key = build_model_key(provider, model, dimension)

    query_text = embedding_service.build_query_text(interest_query)
    result = embed(
        EmbeddingRequest(
            provider=provider,
            model=model,
            texts=[query_text],
            task_type=TASK_QUERY,
            dimension=dimension,
        ),
        api_key,
    )
    query_vec = embedding_service.normalize_vector(
        np.asarray(result.vectors[0], dtype=np.float32)
    )

    period_end = datetime.now(timezone.utc)
    period_start = period_end - timedelta(days=period_days)
    pool = fetch_candidate_pool(db, topic, period_start, period_end)
    indexed_count = sum(
        1 for it in pool if embedding_service.get_item_vector(db, it.id) is not None
    )

    retrieved, missing = embedding_service.rank_with_query(
        db,
        topic,
        pool,
        query_vec,
        threshold=similarity_threshold,
        limit=limit,
    )
    return {
        "indexed_count": indexed_count,
        "missing_embedding_count": missing,
        "matched_count": len(retrieved),
        "model_key": model_key,
        "items": [
            {
                "item": {
                    "id": r.item.id,
                    "title": r.item.title,
                    "source_id": r.item.source_id,
                    "published_at": r.item.published_at,
                    "last_crawl_time": r.item.last_crawl_time,
                },
                "semantic_score": r.semantic_score,
                "hot_score": r.hot_score,
                "final_score": r.final_score,
            }
            for r in retrieved[:limit]
        ],
    }