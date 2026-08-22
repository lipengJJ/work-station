"""抓取编排：域名校验 → 入库 upsert → 榜位历史 → 脱榜检测 → 权重 → 源状态 → 批次记录。

adapter 内部已含重试；这一层负责「一个源失败不影响其他源」的隔离（per-source try/except +
rollback）、去重入库、以及移植自 TrendRadar core/data.py 思路的脱榜检测。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import random
import socket
import time
from urllib.parse import urlsplit

from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.common.services.embedding_config import (
    get_embedding_dimension,
    get_embedding_model,
    get_embedding_provider,
)
from app.common.services.embedding_gateway.service import build_model_key
from app.common.utils.text import hours_since
from app.common.utils.url import normalize_url
from app.hotlist.models import (
    HotCrawlRecord,
    HotCrawlSourceStatus,
    HotItem,
    HotRankHistory,
    HotSemanticHit,
    HotSource,
    HotTopic,
    HotTopicSource,
)
from app.hotlist.services import embedding_service, push_service, ranking
from app.hotlist.services.adapters import get as get_adapter
from app.hotlist.services.adapters.base import (
    HOST_TRIP_KINDS,
    TRANSIENT_KINDS,
    HotSourceAdapterError,
    RawEntry,
)
from app.hotlist.services.security import check_domain_safety

SOURCE_INTERVAL_RANGE = (0.08, 0.12)  # 源间随机间隔，防限流

# 同一上游 host 在本批次内连续失败到这个次数就熔断，剩下同 host 的源直接跳过。
# 库里 60+ 个源指向同一个第三方 RSS 代理，上游一挂就是逐个等超时 + 逐个记失败；
# 熔断只作用于本批次，下一轮重新尝试，上游恢复即自愈。
HOST_FAILURE_THRESHOLD = 3

# 批次前网络预检用的域名。用 DNS 解析而不是 HTTP 请求：快，且不依赖某个站点可达。
NETWORK_PROBE_HOSTS = ("www.baidu.com", "one.one.one.one")
NETWORK_PROBE_TIMEOUT = 3.0
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
    # source_id -> success/failed/skipped
    per_source: dict[str, str] = field(default_factory=dict)
    skipped: bool = False
    """整批跳过（本机网络不可用）。跳过时不写任何源状态，见 run_crawl。"""
    reason: str = ""


def network_available(timeout: float = NETWORK_PROBE_TIMEOUT) -> bool:
    """本机网络（主要是 DNS）是否可用。

    笔记本合盖一夜后第一次定时抓取，网络往往还没恢复，此时 80 个源会一起报
    NameResolutionError 并各记一次失败。用 socket.getaddrinfo 探一下即可判断——
    比发 HTTP 请求快，且不依赖某个具体站点可达。
    """
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        for host in NETWORK_PROBE_HOSTS:
            try:
                socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
                return True
            except OSError:
                continue
        return False
    finally:
        socket.setdefaulttimeout(old)


def _source_host(source: HotSource) -> str:
    """源的上游 host（从 adapter_params.url 取）。取不到返回 ""，不参与熔断。"""
    try:
        url = json.loads(source.adapter_params or "{}").get("url", "")
    except (ValueError, AttributeError):
        return ""
    if not url:
        return ""
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def run_crawl(
    db: Session,
    source_ids: list[str] | None = None,
    trigger: str = "cron",
) -> CrawlResult:
    """跑一批抓取。source_ids 为空跑全部待抓源（见 pending_sources：源自身未被熔断
    且被至少一个启用中的主题启用；无主题时退化为全部 enabled 源）；
    串行执行，任一源失败不阻塞其他源。"""
    crawl_time = datetime.now(timezone.utc)
    stat_date = crawl_time.strftime("%Y-%m-%d")

    if source_ids:
        sources = (
            db.query(HotSource)
            .filter(HotSource.enabled.is_(True), HotSource.id.in_(source_ids))
            .order_by(HotSource.sort_order.asc())
            .all()
        )
    else:
        from app.hotlist.services.topic_service import pending_sources

        sources = pending_sources(db)

    result = CrawlResult(crawl_time=crawl_time, source_count=len(sources))
    status_rows: list[dict] = []
    newly_hit_topic_ids: set[int] = set()

    # 本机网络不可用时整批跳过，且**不写任何源状态**——否则一次断网会让全部源的
    # 失败计数平白加 1，几次下来健康的源就被判成失效了。
    if sources and not network_available():
        logger.warning(
            f"本机网络不可用（DNS 探测失败），跳过本轮抓取的 {len(sources)} 个源，"
            "不累加任何失败计数"
        )
        result.skipped = True
        result.reason = "network_unavailable"
        return result

    # 上游 host 熔断（仅本批次有效）
    host_failures: dict[str, int] = {}
    host_tripped: set[str] = set()

    for source in sources:
        host = _source_host(source)
        if host and host in host_tripped:
            update_source_status(
                db, source, ok=False,
                error=f"上游 {host} 本轮已熔断，跳过（不判定为源失效）",
                kind="upstream_down",
            )
            status_rows.append({
                "source_id": source.id, "status": "failed",
                "item_count": 0, "error": f"上游 {host} 本轮已熔断，跳过",
            })
            result.failed_count += 1
            result.per_source[source.id] = "failed"
            continue
        try:
            adapter = get_adapter(source.adapter)
            params = json.loads(source.adapter_params or "{}")
            entries = adapter.fetch(params)

            bad = check_domain_safety(entries, source.expected_domain)
            if bad:
                raise HotSourceAdapterError(
                    f"域名安全校验未通过: {bad}", kind="domain_unsafe"
                )

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
            detect_off_list(
                db, source.id, prev_crawl_time, current_urls, crawl_time
            )

            recompute_weights(db, source, touched)
            db.commit()

            # 文章业务事务到此结束：best-effort 补算语义向量。
            # 向量服务故障只记状态，绝不能回滚已提交的文章数据。
            try:
                embedding_service.ensure_item_embeddings(
                    db, [it for it, _ in touched], best_effort=True
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"hotlist 源 {source.id} 文章向量补算失败（不影响抓取）: {exc}")

            # 语义命中：向量写入后，对引用该源且开启实时推送的主题做语义匹配
            try:
                newly_hit_topic_ids |= match_semantic_and_record_hits(
                    db, source.id, touched
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"hotlist 源 {source.id} 语义命中评估失败（不影响抓取）: {exc}")

            update_source_status(db, source, ok=True, fetched=len(entries))
            host_failures.pop(host, None)
            status_rows.append(
                {
                    "source_id": source.id,
                    "status": "success",
                    "item_count": len(entries),
                    "error": "",
                }
            )
            result.total_items += len(entries)
            result.per_source[source.id] = "success"
        except Exception as exc:  # noqa: BLE001  任一源失败不阻塞其他源
            db.rollback()
            kind = getattr(exc, "kind", "") or "connection_error"
            logger.warning(
                f"hotlist 源 {source.id} 抓取失败（{kind}）: {exc}"
            )
            # 只有「整个 host 不可达」类的错误才累计熔断：403/404/解析失败是
            # 单个源自己的问题，不能拖累同 host 的其他源。
            if host and kind in HOST_TRIP_KINDS:
                host_failures[host] = host_failures.get(host, 0) + 1
                if host_failures[host] >= HOST_FAILURE_THRESHOLD:
                    host_tripped.add(host)
                    remaining = sum(
                        1 for s2 in sources
                        if _source_host(s2) == host
                        and s2.id not in result.per_source
                        and s2.id != source.id
                    )
                    logger.warning(
                        f"上游 {host} 本轮连续失败 {HOST_FAILURE_THRESHOLD} 次，"
                        f"熔断，跳过其余 {remaining} 个同 host 的源"
                    )
            # rollback 后原对象已过期，重新拿一次避免脏状态
            fresh_source = db.get(HotSource, source.id)
            if fresh_source is not None:
                update_source_status(
                    db, fresh_source, ok=False, error=str(exc), kind=kind
                )
            status_rows.append(
                {
                    "source_id": source.id,
                    "status": "failed",
                    "item_count": 0,
                    "error": str(exc)[:500],
                }
            )
            result.failed_count += 1
            result.per_source[source.id] = "failed"
        time.sleep(random.uniform(*SOURCE_INTERVAL_RANGE))

    write_crawl_record(db, result, stat_date, trigger, status_rows)

    # 批次内累积后统一评估推送（而不是每个源命中就推一次），避免同一主题在一次批次里
    # 因为命中分散在多个源而被拆成好几条推送消息
    for topic_id in newly_hit_topic_ids:
        push_service.notify_topic_hits(db, topic_id)

    return result


def upsert_items(
    db: Session,
    source: HotSource,
    entries: list[RawEntry],
    crawl_time: datetime,
    stat_date: str,
) -> list[tuple[HotItem, int]]:
    """按 (source_id, normalize_url(url)) upsert；url 为空的条目按
    (source_id, stat_date, title) 兜底查。
    返回本批次触达的 (item, rank)，供榜位历史/权重复用，避免重复查询。"""
    touched: list[tuple[HotItem, int]] = []
    for entry in entries:
        title = (entry.title or "").strip()[:512]
        if not title:
            continue
        url = normalize_url(entry.url)[:1024]
        mobile_url = (
            normalize_url(entry.mobile_url)[:1024]
            if entry.mobile_url
            else ""
        )

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
        # RSS feed 自带全文（content:encoded）→ 顺带写全文缓存，L2 放大时不再发请求
        if entry.full_content:
            _upsert_full_content(db, item, entry.full_content, crawl_time)
        touched.append((item, entry.rank))
    return touched


def _upsert_full_content(
    db: Session, item: HotItem, content: str, crawl_time: datetime
) -> None:
    """全文缓存 upsert：RSS 自带的正文直接入库（同一 item 只写一次，不覆盖人工抓取结果）。"""
    from app.hotlist.models import HotItemContent

    cached = db.get(HotItemContent, item.id)
    if cached is not None and cached.status == "success":
        return  # 已有成功缓存（可能来自页面抓取），不覆盖
    db.add(
        HotItemContent(
            item_id=item.id,
            content=content,
            char_count=len(content),
            status="success",
            fetched_at=crawl_time,
        )
    )


def write_rank_history(
    db: Session,
    touched: list[tuple[HotItem, int]],
    crawl_time: datetime,
) -> None:
    for item, rank in touched:
        db.add(
            HotRankHistory(item_id=item.id, rank=rank, crawl_time=crawl_time)
        )


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


def recompute_weights(
    db: Session,
    source: HotSource,
    touched: list[tuple[HotItem, int]],
) -> None:
    if not touched:
        return
    now = datetime.now(timezone.utc)
    weight_config = ranking.get_weight_config(db)
    for item, _rank in touched:
        ranks = json.loads(item.ranks_json or "[]")
        decay = ranking.decay_factor(
            source.decay_half_life_hours,
            hours_since(item.published_at, now),
        )
        item.weight = ranking.calculate_weight(
            ranks,
            item.crawl_count,
            weight_config=weight_config,
            decay=decay,
        )


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


def update_source_status(
    db: Session,
    source: HotSource,
    ok: bool,
    error: str = "",
    fetched: int = 0,
    kind: str = "",
) -> None:
    """写源健康状态。

    失败按 kind 分流到 transient_failures / permanent_failures 两个计数：
    失效判定（topic_service.list_stale_source_ids）只看 permanent_failures，
    所以 DNS 抖动、上游挂掉这类不是源自身问题的失败，不会把健康的源判成失效。
    """
    now = datetime.now(timezone.utc)
    source.last_fetched_at = now
    if ok:
        source.last_status = "success"
        source.last_error = ""
        source.last_error_kind = ""
        source.consecutive_failures = 0
        source.transient_failures = 0
        source.permanent_failures = 0
        source.last_success_at = now
        source.total_fetched = (source.total_fetched or 0) + fetched
    else:
        source.last_status = "failed"
        source.last_error = (error or "")[:500]
        source.last_error_kind = kind or "connection_error"
        source.consecutive_failures = (source.consecutive_failures or 0) + 1
        if source.last_error_kind in TRANSIENT_KINDS:
            source.transient_failures = (source.transient_failures or 0) + 1
        else:
            source.permanent_failures = (source.permanent_failures or 0) + 1
            if source.permanent_failures >= 3:
                source.fail_count = (source.fail_count or 0) + 1
    source.updated_at = now
    db.commit()


def write_crawl_record(
    db: Session,
    result: CrawlResult,
    stat_date: str,
    trigger: str,
    status_rows: list[dict],
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
    """按 SQLITE_BATCH_SIZE 分批 DELETE ... WHERE column IN (...)，避开
    SQLite 999 参数上限。"""
    deleted = 0
    for i in range(0, len(ids), SQLITE_BATCH_SIZE):
        chunk = ids[i : i + SQLITE_BATCH_SIZE]
        deleted += (
            db.query(model)
            .filter(column.in_(chunk))
            .delete(synchronize_session=False)
        )
    return deleted


def cleanup_old_items(db: Session) -> int:
    """保留策略：先删超过 RETENTION_DAYS 天（按 stat_date）的条目，再删至最多 MAX_ITEMS 条
    （按 last_crawl_time 保留最新）。
    语义沿用旧 ai_trending/services/collector.py::cleanup_old_items，
    删除前先显式清关联的 HotRankHistory / HotSemanticHit（SQLite 外键默认不强制，不能依赖 DB 级
    CASCADE），避免清理后榜位曲线/语义命中记录悬空。同时按同样的 RETENTION_DAYS 清理过期的
    HotCrawlRecord + HotCrawlSourceStatus（批次记录本身不大，但也不该无限增长）。

    main.py lifespan 里 scheduler_jobs.register_all_enabled_jobs()
    会把它挂成每日 03:30 job。
    """
    cutoff_date = (
        datetime.now(timezone.utc)
        - timedelta(days=RETENTION_DAYS)
    ).strftime("%Y-%m-%d")

    expired_ids = [
        row[0]
        for row in db.query(HotItem.id)
        .filter(HotItem.stat_date < cutoff_date)
        .all()
    ]
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
        _delete_in_batches(
            db, HotRankHistory, HotRankHistory.item_id, expired_ids
        )
        _delete_in_batches(
            db, HotSemanticHit, HotSemanticHit.item_id, expired_ids
        )
        deleted_items = _delete_in_batches(
            db, HotItem, HotItem.id, expired_ids
        )
        db.commit()

    expired_record_ids = [
        row[0]
        for row in db.query(HotCrawlRecord.id)
        .filter(HotCrawlRecord.stat_date < cutoff_date)
        .all()
    ]
    if expired_record_ids:
        _delete_in_batches(
            db, HotCrawlSourceStatus, HotCrawlSourceStatus.crawl_record_id,
            expired_record_ids,
        )
        _delete_in_batches(
            db, HotCrawlRecord, HotCrawlRecord.id, expired_record_ids
        )
        db.commit()

    return deleted_items
