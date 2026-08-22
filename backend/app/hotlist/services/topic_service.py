"""主题 CRUD + 源关联 + 待抓源解析（Phase 5）。

- slug：创建时按 name 生成候选值但允许改；生成后不允许修改（已发布报告路径断链）。
- 批量开关：全开 / 全关 / 指定集合。
- 待抓源解析：源自身未被熔断 且 被至少一个启用中的主题启用（§2.2 的 JOIN SQL）。
  兼容处理：不存在任何启用主题时退化为抓全部 enabled 源（老用户没有主题概念，
  不能因为没建主题就让既有抓取全部停掉）。
- 失效源置灰：连续失败 >=5 的关联源在列表里标记，提供一键批量关闭。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
import secrets
from typing import Optional

import numpy as np
from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.hotlist.models import (
    HotItem,
    HotSource,
    HotTopic,
    HotTopicEmbedding,
    HotTopicSource,
)
from app.hotlist.schemas.topic import TopicIn, TopicSourceOut, TopicUpdateIn

STALE_FAILURE_THRESHOLD = 5  # 连续「永久类」失败 >=5 才置灰，见 list_stale_source_ids

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


# ------------------------------------------------------------ 源关联 ----

def attach_source(
    db: Session, topic_id: int, source_id: str, enabled: bool = False,
    imported_from: str = "manual",
) -> HotTopicSource:
    """建关联（已存在则更新启用状态）。返回关联行。"""
    link = (
        db.query(HotTopicSource)
        .filter(
            HotTopicSource.topic_id == topic_id,
            HotTopicSource.source_id == source_id,
        )
        .first()
    )
    if link is None:
        link = HotTopicSource(
            topic_id=topic_id,
            source_id=source_id,
            enabled=enabled,
            imported_from=imported_from,
        )
        db.add(link)
    else:
        link.enabled = enabled
        link.imported_from = imported_from
    db.commit()
    db.refresh(link)
    return link


def detach_source(db: Session, topic_id: int, source_id: str) -> None:
    link = (
        db.query(HotTopicSource)
        .filter(
            HotTopicSource.topic_id == topic_id,
            HotTopicSource.source_id == source_id,
        )
        .first()
    )
    if link is None:
        raise ValueError("该源不在主题中")
    db.delete(link)
    db.commit()


def batch_set_sources(
    db: Session, topic_id: int, mode: str, source_ids: list[str] | None = None
) -> int:
    """批量开关：all_on / all_off / set（source_ids 集合，其余全关）。返回改动条数。

    set 语义：集合内的源启用、集合外的关闭；**缺失的关联行自动补建**（建主题后直接
    PUT mode=set 挂源，不再需要先 attach_source；补建行 imported_from='manual'）。
    脏数据防御：wanted 里不存在的源 id 跳过并记 warning，不炸。
    """
    links = (
        db.query(HotTopicSource)
        .filter(HotTopicSource.topic_id == topic_id)
        .all()
    )
    link_by_source = {link.source_id: link for link in links}
    changed = 0
    if mode == "all_on":
        for link in links:
            if not link.enabled:
                link.enabled = True
                changed += 1
    elif mode == "all_off":
        for link in links:
            if link.enabled:
                link.enabled = False
                changed += 1
    elif mode == "set":
        wanted = set(source_ids or [])
        # 补建缺失的关联行（只补 hot_sources 里真实存在的源）
        existing_ids = {
            row[0]
            for row in db.query(HotSource.id)
            .filter(HotSource.id.in_(wanted))
            .all()
        }
        for source_id in wanted:
            if source_id not in existing_ids:
                logger.warning(
                    f"hotlist 主题 {topic_id} 批量 set 跳过不存在的源: {source_id}"
                )
                continue
            if source_id not in link_by_source:
                db.add(
                    HotTopicSource(
                        topic_id=topic_id,
                        source_id=source_id,
                        enabled=True,
                        imported_from="manual",
                    )
                )
                changed += 1
        # 已存在的链接：集合内启用、集合外关闭
        for link in links:
            target = link.source_id in wanted
            if link.enabled != target:
                link.enabled = target
                changed += 1
    else:
        raise ValueError(f"未知批量模式: {mode}（可选：all_on/all_off/set）")
    db.commit()
    return changed


def list_topic_sources(db: Session, topic_id: int) -> list[TopicSourceOut]:
    """主题下的源列表：源信息 + 关联状态 + 健康状态 + 近 7 天贡献命中数。

    近 7 天贡献数：按 HotItem.first_crawl_time >= 7 天前统计每个源的条目数
    （第一次出现在本主题候选范围内即算贡献，不依赖规则命中）。
    """
    links = (
        db.query(HotTopicSource)
        .filter(HotTopicSource.topic_id == topic_id)
        .order_by(HotTopicSource.added_at.asc())
        .all()
    )
    if not links:
        return []
    source_ids = [link.source_id for link in links]
    sources = db.query(HotSource).filter(HotSource.id.in_(source_ids)).all()
    source_map = {s.id: s for s in sources}

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    counts: dict[str, int] = {}
    rows = (
        db.query(HotItem.source_id, func.count(HotItem.id))
        .filter(
            HotItem.source_id.in_(source_ids),
            HotItem.first_crawl_time >= cutoff,
        )
        .group_by(HotItem.source_id)
        .all()
    )
    counts = dict(rows)

    out: list[TopicSourceOut] = []
    for link in links:
        source = source_map.get(link.source_id)
        if source is None:
            continue
        out.append(
            TopicSourceOut(
                id=source.id,
                name=source.name,
                source_kind=source.source_kind,
                adapter=source.adapter,
                cron_expr=source.cron_expr,
                enabled=source.enabled,
                last_status=source.last_status,
                last_error=source.last_error,
                consecutive_failures=source.consecutive_failures,
                last_error_kind=source.last_error_kind,
                transient_failures=source.transient_failures,
                permanent_failures=source.permanent_failures,
                fail_count=source.fail_count,
                last_success_at=source.last_success_at,
                total_fetched=source.total_fetched,
                topic_enabled=link.enabled,
                imported_from=link.imported_from,
                hit_count_7d=counts.get(source.id, 0),
            )
        )
    return out


def list_stale_source_ids(db: Session, topic_id: int) -> list[str]:
    """主题下真正失效的源 id（供前端置灰 + 一键关闭）。

    判定只看 permanent_failures（404 / 解析失败 / 空 feed / 被拒），**不看**
    transient_failures（DNS 抖动、连接超时、上游 5xx、上游熔断）。
    否则一次本机断网或一个第三方上游挂掉，就能把几十个完全健康的源标成失效，
    用户点一下「一键关闭」就全关了，而且关掉之后不再抓取、无法自愈。
    """
    links = (
        db.query(HotTopicSource)
        .filter(
            HotTopicSource.topic_id == topic_id,
            HotTopicSource.enabled.is_(True),
        )
        .all()
    )
    if not links:
        return []
    source_ids = [link.source_id for link in links]
    stale = [
        row[0]
        for row in db.query(HotSource.id)
        .filter(
            HotSource.id.in_(source_ids),
            HotSource.permanent_failures >= STALE_FAILURE_THRESHOLD,
        )
        .all()
    ]
    return stale


def disable_stale_sources(db: Session, topic_id: int) -> int:
    """一键关闭主题下所有失效源（永久类失败 >=5 且本主题启用中）。返回关闭条数。

    只由用户显式点击触发，不会自动执行——自动关闭一旦误判就无法自愈。
    """
    stale = list_stale_source_ids(db, topic_id)
    if not stale:
        return 0
    changed = batch_set_sources(db, topic_id, "set", [
        link.source_id
        for link in db.query(HotTopicSource)
        .filter(
            HotTopicSource.topic_id == topic_id,
            HotTopicSource.enabled.is_(True),
        )
        .all()
        if link.source_id not in stale
    ])
    return changed


# ------------------------------------------------------------ 待抓源解析 ----

def enabled_topic_exists(db: Session) -> bool:
    return (
        db.query(HotTopic.id)
        .filter(HotTopic.enabled.is_(True))
        .limit(1)
        .first()
    ) is not None


def pending_sources(db: Session) -> list[HotSource]:
    """待抓源：源自身 enabled 且被至少一个启用中的主题启用。

    兼容：没有任何启用主题时退化为全部 enabled 源（Phase 5 之前的行为）。
    """
    base = db.query(HotSource).filter(HotSource.enabled.is_(True))
    if not enabled_topic_exists(db):
        return base.order_by(HotSource.sort_order.asc()).all()

    topic_ids = [
        row[0]
        for row in db.query(HotTopic.id)
        .filter(HotTopic.enabled.is_(True))
        .all()
    ]
    used_source_ids = {
        row[0]
        for row in db.query(HotTopicSource.source_id)
        .filter(
            HotTopicSource.topic_id.in_(topic_ids),
            HotTopicSource.enabled.is_(True),
        )
        .all()
    }
    if not used_source_ids:
        return []
    return (
        base.filter(HotSource.id.in_(used_source_ids))
        .order_by(HotSource.sort_order.asc())
        .all()
    )


def source_count_for_topic(db: Session, topic_id: int) -> int:
    """主题启用的源数量（规模护栏：>100 前端警告）。"""
    return (
        db.query(HotTopicSource)
        .filter(
            HotTopicSource.topic_id == topic_id,
            HotTopicSource.enabled.is_(True),
        )
        .count()
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
            provider=provider, model=model, texts=[query_text], task_type=TASK_QUERY
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
