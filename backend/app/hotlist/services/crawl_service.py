"""抓取编排：域名校验 → 入库 upsert → 榜位历史 → 脱榜检测 → 权重 → 源状态 → 批次记录。

adapter 内部已含重试；这一层负责「一个源失败不影响其他源」的隔离（per-source try/except +
rollback）、去重入库、以及移植自 TrendRadar core/data.py 思路的脱榜检测。
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.common.utils.text import hours_since
from app.common.utils.url import normalize_url
from app.hotlist.models import (
    HotCrawlRecord,
    HotCrawlSourceStatus,
    HotItem,
    HotRankHistory,
    HotRuleHit,
    HotSource,
)
from app.hotlist.services import keyword_rules, push_service, ranking
from app.hotlist.services.adapters import get as get_adapter
from app.hotlist.services.adapters.base import HotSourceAdapterError, RawEntry
from app.hotlist.services.security import check_domain_safety

SOURCE_INTERVAL_RANGE = (0.08, 0.12)  # 源间随机间隔，防限流
RANKS_JSON_KEEP = 50

# ------------------------------------------------------------ 保留策略 ----
RETENTION_DAYS = 7  # 超过 7 天（按 stat_date）的条目清理
MAX_ITEMS = 5000  # 18 个源、每源几十条，比旧 ai_trending（7 源）的 2000 上限相应调高
SQLITE_BATCH_SIZE = 500  # 批量删除时的分批大小，留足余量避开 SQLite 999 参数上限


@dataclass
class CrawlResult:
    crawl_time: datetime
    total_items: int = 0
    source_count: int = 0
    failed_count: int = 0
    per_source: dict[str, str] = field(default_factory=dict)  # source_id -> success/failed


def run_crawl(db: Session, source_ids: list[str] | None = None, trigger: str = "cron") -> CrawlResult:
    """跑一批抓取。source_ids 为空跑全部 enabled 源；串行执行，任一源失败不阻塞其他源。"""
    crawl_time = datetime.now(timezone.utc)
    stat_date = crawl_time.strftime("%Y-%m-%d")

    query = db.query(HotSource).filter(HotSource.enabled.is_(True))
    if source_ids:
        query = query.filter(HotSource.id.in_(source_ids))
    sources = query.order_by(HotSource.sort_order.asc()).all()

    result = CrawlResult(crawl_time=crawl_time, source_count=len(sources))
    status_rows: list[dict] = []
    newly_hit_rule_ids: set[int] = set()

    for source in sources:
        try:
            adapter = get_adapter(source.adapter)
            params = json.loads(source.adapter_params or "{}")
            entries = adapter.fetch(params)

            bad = check_domain_safety(entries, source.expected_domain)
            if bad:
                raise HotSourceAdapterError(f"域名安全校验未通过: {bad}")

            # 上一批次时间戳：取该源现存条目里 last_crawl_time 的最大值，必须在
            # upsert_items 覆写 last_crawl_time 之前取，否则「上一批」就等于「这一批」了
            prev_crawl_time = (
                db.query(func.max(HotItem.last_crawl_time))
                .filter(HotItem.source_id == source.id)
                .scalar()
            )

            touched = upsert_items(db, source, entries, crawl_time, stat_date)
            write_rank_history(db, touched, crawl_time)

            current_urls = {normalize_url(e.url) for e in entries if e.url}
            detect_off_list(db, source.id, prev_crawl_time, current_urls, crawl_time)

            recompute_weights(db, source, touched)
            newly_hit_rule_ids |= match_rules_and_record_hits(db, source.id, touched)
            db.commit()

            update_source_status(db, source, ok=True, fetched=len(entries))
            status_rows.append(
                {"source_id": source.id, "status": "success", "item_count": len(entries), "error": ""}
            )
            result.total_items += len(entries)
            result.per_source[source.id] = "success"
        except Exception as exc:  # noqa: BLE001  任一源失败不阻塞其他源
            db.rollback()
            logger.warning(f"hotlist 源 {source.id} 抓取失败: {exc}")
            # rollback 后原对象已过期，重新拿一次避免脏状态
            fresh_source = db.get(HotSource, source.id)
            if fresh_source is not None:
                update_source_status(db, fresh_source, ok=False, error=str(exc))
            status_rows.append(
                {"source_id": source.id, "status": "failed", "item_count": 0, "error": str(exc)[:500]}
            )
            result.failed_count += 1
            result.per_source[source.id] = "failed"
        time.sleep(random.uniform(*SOURCE_INTERVAL_RANGE))

    write_crawl_record(db, result, stat_date, trigger, status_rows)

    # 批次内累积后统一评估推送（而不是每个源命中就推一次），避免同一规则在一次批次里
    # 因为命中分散在多个源而被拆成好几条推送消息
    for rule_id in newly_hit_rule_ids:
        push_service.notify_rule_hits(db, rule_id)

    return result


def upsert_items(
    db: Session, source: HotSource, entries: list[RawEntry], crawl_time: datetime, stat_date: str
) -> list[tuple[HotItem, int]]:
    """按 (source_id, normalize_url(url)) upsert；url 为空的条目按 (source_id, stat_date, title) 兜底查。
    返回本批次触达的 (item, rank)，供榜位历史/权重复用，避免重复查询。"""
    touched: list[tuple[HotItem, int]] = []
    for entry in entries:
        title = (entry.title or "").strip()[:512]
        if not title:
            continue
        url = normalize_url(entry.url)[:1024]
        mobile_url = normalize_url(entry.mobile_url)[:1024] if entry.mobile_url else ""

        if url:
            existing = (
                db.query(HotItem)
                .filter(HotItem.source_id == source.id, HotItem.url == url)
                .first()
            )
        else:
            existing = (
                db.query(HotItem)
                .filter(
                    HotItem.source_id == source.id,
                    HotItem.stat_date == stat_date,
                    HotItem.title == title,
                )
                .first()
            )

        if existing is None:
            item = HotItem(
                source_id=source.id,
                title=title,
                url=url,
                mobile_url=mobile_url,
                summary=entry.summary or "",
                stat_date=stat_date,
                rank=entry.rank,
                best_rank=entry.rank,
                ranks_json=json.dumps([entry.rank]),
                first_crawl_time=crawl_time,
                last_crawl_time=crawl_time,
                crawl_count=1,
                published_at=entry.published_at,
                metrics=json.dumps(entry.metrics, ensure_ascii=False),
                created_at=crawl_time,
                updated_at=crawl_time,
            )
            db.add(item)
            db.flush()  # 拿到自增 id，供 write_rank_history 用
        else:
            item = existing
            item.title = title
            item.rank = entry.rank
            if mobile_url:
                item.mobile_url = mobile_url
            item.last_crawl_time = crawl_time
            item.crawl_count = (item.crawl_count or 0) + 1
            item.best_rank = min(item.best_rank or entry.rank, entry.rank)
            ranks = json.loads(item.ranks_json or "[]")
            ranks.append(entry.rank)
            item.ranks_json = json.dumps(ranks[-RANKS_JSON_KEEP:])
            if entry.metrics:
                item.metrics = json.dumps(entry.metrics, ensure_ascii=False)
            item.updated_at = crawl_time
        touched.append((item, entry.rank))
    return touched


def write_rank_history(db: Session, touched: list[tuple[HotItem, int]], crawl_time: datetime) -> None:
    for item, rank in touched:
        db.add(HotRankHistory(item_id=item.id, rank=rank, crawl_time=crawl_time))


def detect_off_list(
    db: Session,
    source_id: str,
    prev_crawl_time: datetime | None,
    current_urls: set[str],
    crawl_time: datetime,
) -> None:
    """脱榜检测：上一批（last_crawl_time == prev_crawl_time）在榜、这批不在的条目标记脱榜。

    不用「NOT IN 一堆当前 URL」的写法——当前批 URL 多时会撞 SQLite 999 参数上限。
    改为只查上一批次的条目（数量等于该源榜单长度，通常几十条，不是全表扫），
    在 Python 里跟当前 URL 集合做差集，同样是一条 SQL 且天然不受参数上限影响。
    当天第一次抓取（prev_crawl_time 为空）没有历史批次可比较，直接跳过。
    """
    if prev_crawl_time is None:
        return
    rows = (
        db.query(HotItem)
        .filter(
            HotItem.source_id == source_id,
            HotItem.last_crawl_time == prev_crawl_time,
            HotItem.url != "",
        )
        .all()
    )
    for item in rows:
        if item.url in current_urls:
            continue
        db.add(HotRankHistory(item_id=item.id, rank=0, crawl_time=crawl_time))
        item.rank = 0


def recompute_weights(db: Session, source: HotSource, touched: list[tuple[HotItem, int]]) -> None:
    if not touched:
        return
    now = datetime.now(timezone.utc)
    weight_config = ranking.get_weight_config(db)
    for item, _rank in touched:
        ranks = json.loads(item.ranks_json or "[]")
        decay = ranking.decay_factor(source.decay_half_life_hours, hours_since(item.published_at, now))
        item.weight = ranking.calculate_weight(ranks, item.crawl_count, weight_config=weight_config, decay=decay)


def match_rules_and_record_hits(db: Session, source_id: str, touched: list[tuple[HotItem, int]]) -> set[int]:
    """用当前源适用的启用规则跑一遍标题匹配，新命中写 HotRuleHit（(rule_id, item_id) 去重，
    同一条目对同一规则只记一次——重复出现在榜单上不会重复计命中/重复推送）。
    返回本次新增了命中的规则 id 集合，供调用方决定要不要触发推送评估。"""
    if not touched:
        return set()
    word_groups, _filter_words, global_filters = keyword_rules.load_rules(db, source_id=source_id)
    if not word_groups and not global_filters:
        return set()

    item_ids = [item.id for item, _rank in touched]
    existing = {
        (rule_id, item_id)
        for rule_id, item_id in db.query(HotRuleHit.rule_id, HotRuleHit.item_id)
        .filter(HotRuleHit.item_id.in_(item_ids))
        .all()
    }

    now = datetime.now(timezone.utc)
    newly_hit_rule_ids: set[int] = set()
    for item, _rank in touched:
        # 标题 + 摘要一起匹配：GitHub/HN/RSS 这类源，真正的信号常在摘要里
        # （比如仓库名 "nautilus_trader" 不含「trading」，但 description 写着 "trading engine"）
        match_text = f"{item.title} {item.summary}"
        for rule_id in keyword_rules.match_groups(match_text, word_groups, global_filters):
            key = (rule_id, item.id)
            if key in existing:
                continue
            db.add(HotRuleHit(rule_id=rule_id, item_id=item.id, matched_at=now, notified=False))
            existing.add(key)
            newly_hit_rule_ids.add(rule_id)
    return newly_hit_rule_ids


def update_source_status(db: Session, source: HotSource, ok: bool, error: str = "", fetched: int = 0) -> None:
    now = datetime.now(timezone.utc)
    source.last_fetched_at = now
    if ok:
        source.last_status = "success"
        source.last_error = ""
        source.consecutive_failures = 0
        source.last_success_at = now
        source.total_fetched = (source.total_fetched or 0) + fetched
    else:
        source.last_status = "failed"
        source.last_error = (error or "")[:500]
        source.consecutive_failures = (source.consecutive_failures or 0) + 1
        if source.consecutive_failures >= 3:
            source.fail_count = (source.fail_count or 0) + 1
    source.updated_at = now
    db.commit()


def write_crawl_record(
    db: Session, result: CrawlResult, stat_date: str, trigger: str, status_rows: list[dict]
) -> None:
    record = HotCrawlRecord(
        crawl_time=result.crawl_time,
        stat_date=stat_date,
        total_items=result.total_items,
        source_count=result.source_count,
        failed_count=result.failed_count,
        trigger=trigger,
        created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.flush()
    for row in status_rows:
        db.add(HotCrawlSourceStatus(crawl_record_id=record.id, **row))
    db.commit()


def _delete_in_batches(db: Session, model, column, ids: list) -> int:
    """按 SQLITE_BATCH_SIZE 分批 DELETE ... WHERE column IN (...)，避开 SQLite 999 参数上限。"""
    deleted = 0
    for i in range(0, len(ids), SQLITE_BATCH_SIZE):
        chunk = ids[i : i + SQLITE_BATCH_SIZE]
        deleted += (
            db.query(model).filter(column.in_(chunk)).delete(synchronize_session=False)
        )
    return deleted


def cleanup_old_items(db: Session) -> int:
    """保留策略：先删超过 RETENTION_DAYS 天（按 stat_date）的条目，再删至最多 MAX_ITEMS 条
    （按 last_crawl_time 保留最新）。语义沿用旧 ai_trending/services/collector.py::cleanup_old_items，
    删除前先显式清关联的 HotRankHistory / HotRuleHit（SQLite 外键默认不强制，不能依赖 DB 级
    CASCADE），避免清理后榜位曲线/命中记录悬空。同时按同样的 RETENTION_DAYS 清理过期的
    HotCrawlRecord + HotCrawlSourceStatus（批次记录本身不大，但也不该无限增长）。

    main.py lifespan 里 scheduler_jobs.register_all_enabled_jobs() 会把它挂成每日 03:30 job。
    """
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")

    expired_ids = [row[0] for row in db.query(HotItem.id).filter(HotItem.stat_date < cutoff_date).all()]
    total = db.query(HotItem).count()
    if total > MAX_ITEMS:
        excess = total - MAX_ITEMS
        old_ids = [
            row[0]
            for row in db.query(HotItem.id)
            .order_by(HotItem.last_crawl_time.asc(), HotItem.id.asc())
            .limit(excess)
            .all()
        ]
        expired_ids = list(dict.fromkeys(expired_ids + old_ids))

    deleted_items = 0
    if expired_ids:
        _delete_in_batches(db, HotRankHistory, HotRankHistory.item_id, expired_ids)
        _delete_in_batches(db, HotRuleHit, HotRuleHit.item_id, expired_ids)
        deleted_items = _delete_in_batches(db, HotItem, HotItem.id, expired_ids)
        db.commit()

    expired_record_ids = [
        row[0] for row in db.query(HotCrawlRecord.id).filter(HotCrawlRecord.stat_date < cutoff_date).all()
    ]
    if expired_record_ids:
        _delete_in_batches(db, HotCrawlSourceStatus, HotCrawlSourceStatus.crawl_record_id, expired_record_ids)
        _delete_in_batches(db, HotCrawlRecord, HotCrawlRecord.id, expired_record_ids)
        db.commit()

    return deleted_items
