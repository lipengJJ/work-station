"""文章条目处理管道：upsert 入库 → 榜位历史 → 脱榜检测 → 权重。

从 crawl_service 拆出：run_crawl 的「整批后端编排」留在 crawl_service，
这里只负责「单个源已经抓到 entries 之后的条目级转换」，不感知抓取/限流/熔断。
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

from sqlalchemy.orm import Session

from app.common.utils.text import hours_since
from app.common.utils.url import normalize_url
from app.hotlist.models import HotItem, HotRankHistory, HotSource
from app.hotlist.services import ranking
from app.hotlist.services.adapters.base import RawEntry

RANKS_JSON_KEEP = 50


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