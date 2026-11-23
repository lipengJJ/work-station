"""语义命中：文章向量写入后，用启用实时推送的主题做语义匹配并落 HotSemanticHit。

从 crawl_service 拆出：这是「抓取完成后的语义侧处理」，依赖 embedding_service，
与抓取编排本身无关。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.common.services.embedding_config import (
    get_embedding_dimension,
    get_embedding_model,
    get_embedding_provider,
)
from app.common.services.embedding_gateway.service import build_model_key
from app.hotlist.models import HotItem, HotSemanticHit, HotTopic, HotTopicSource
from app.hotlist.services import embedding_service


def match_semantic_and_record_hits(
    db: Session,
    source_id: str,
    touched: list[tuple[HotItem, int]],
) -> set[int]:
    """文章向量写入后，用「引用了该源且启用 + 开启实时推送」的主题做语义匹配，
    超过主题阈值即写 HotSemanticHit。

    返回本批次有新命中的 **topic_id** 集合，供调用方按主题触发推送评估。
    命中行携带 query_hash，需求变更后旧命中不会被推送（见 push_service）。
    """
    if not touched:
        return set()

    topics = (
        db.query(HotTopic)
        .join(HotTopicSource, HotTopicSource.topic_id == HotTopic.id)
        .filter(
            HotTopicSource.source_id == source_id,
            HotTopicSource.enabled.is_(True),
            HotTopic.enabled.is_(True),
            HotTopic.hit_notify_enabled.is_(True),
        )
        .all()
    )
    if not topics:
        return set()

    items = [item for item, _rank in touched]
    provider = get_embedding_provider(db)
    model = get_embedding_model(db)
    dimension = get_embedding_dimension(db)
    model_key = build_model_key(provider, model, dimension)
    now = datetime.now(timezone.utc)
    newly_hit_topic_ids: set[int] = set()

    for topic in topics:
        if not (topic.interest_query or "").strip():
            continue
        topic_vec = embedding_service.get_topic_vector(db, topic.id)
        if topic_vec is None:
            continue
        retrieved, _missing = embedding_service.rank_with_query(
            db,
            topic,
            items,
            topic_vec,
            threshold=topic.similarity_threshold,
            limit=200,
        )
        if not retrieved:
            continue
        query_hash = embedding_service.content_hash(
            embedding_service.QUERY_PREPROCESS_VERSION,
            embedding_service.build_query_text(topic.interest_query),
        )
        for r in retrieved:
            # (topic_id, item_id) 去重：同一条目对同一主题只记一次命中
            if (
                db.query(HotSemanticHit)
                .filter(
                    HotSemanticHit.topic_id == topic.id,
                    HotSemanticHit.item_id == r.item.id,
                )
                .first()
            ):
                continue
            db.add(
                HotSemanticHit(
                    topic_id=topic.id,
                    item_id=r.item.id,
                    semantic_score=r.semantic_score,
                    model_key=model_key,
                    query_hash=query_hash,
                    matched_at=now,
                    notified=False,
                )
            )
        newly_hit_topic_ids.add(topic.id)
    db.commit()
    return newly_hit_topic_ids