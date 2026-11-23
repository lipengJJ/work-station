"""主题源关联：挂载/解除、批量开关、源列表（健康状态 + 贡献数）、失效源置灰。

从 topic_service 拆出：主题 CRUD / slug 归 topic_service，与源之间的关联关系及
由此衍生的健康度/失效判定归本模块，避免主题生命周期和源关联逻辑混在一个文件里。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.hotlist.models import HotItem, HotSource, HotTopicSource
from app.hotlist.schemas.topic import TopicSourceOut

STALE_FAILURE_THRESHOLD = 5  # 连续「永久类」失败 >=5 才置灰，见 list_stale_source_ids


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
                adapter=source.adapter,
                interval_hours=source.interval_hours,
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