"""新增检测：一个标题只要其 first_crawl_time < 最新批次时间就算历史标题，不算新增；
即使同标题有多条记录（URL 不同），只要任一条是历史的，整个标题就不算新增。

移植自 TrendRadar (https://github.com/sansan0/TrendRadar) core/data.py 的判据，改动一处：
「最新批次时间」按源分别计算，不是全局一个时间戳。TrendRadar 原版一次 cron tick 会把所有
平台一起抓完，天然共享同一个批次时间戳；hotlist 里每个源的 cron_expr 各自独立（Phase 1 的
设计初衷就是让抓取频率能在前端单独改），同一时刻只有极少数源恰好被抓过，用全局时间戳
会导致「当前榜单」在真实运行时几乎总是空的。按源分别取「最新批次」才是这个架构下对的语义。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.hotlist.models import HotItem


def latest_crawl_time(
    db: Session, stat_date: str, source_id: str
) -> datetime | None:
    """单个源当天最新一批的时间戳；当天还没抓过时返回 None。"""
    return (
        db.query(func.max(HotItem.last_crawl_time))
        .filter(HotItem.stat_date == stat_date, HotItem.source_id == source_id)
        .scalar()
    )


def _scoped_source_ids(
    db: Session, stat_date: str, source_ids: list[str] | None
) -> list[str]:
    """展开为当天实际有数据的源 id 列表；source_ids 为空时 = 当天出现过数据的全部源。"""
    q = db.query(HotItem.source_id.distinct()).filter(
        HotItem.stat_date == stat_date
    )
    if source_ids:
        q = q.filter(HotItem.source_id.in_(source_ids))
    return [row[0] for row in q.all()]


def incremental_items(
    db: Session, stat_date: str, source_ids: list[str] | None = None
) -> list[HotItem]:
    """各源「最新批次」里的新增条目，汇总返回。当某源当天第一次抓取（没有历史批次）时，
    该源最新批次全部算新增。"""
    result: list[HotItem] = []
    for source_id in _scoped_source_ids(db, stat_date, source_ids):
        latest = latest_crawl_time(db, stat_date, source_id)
        if latest is None:
            continue
        historical_titles = {
            row[0]
            for row in db.query(HotItem.title)
            .filter(
                HotItem.stat_date == stat_date,
                HotItem.source_id == source_id,
                HotItem.first_crawl_time < latest,
            )
            .all()
        }
        rows = (
            db.query(HotItem)
            .filter(
                HotItem.stat_date == stat_date,
                HotItem.source_id == source_id,
                HotItem.last_crawl_time == latest,
            )
            .all()
        )
        result.extend(
            item for item in rows if item.title not in historical_titles
        )
    return result


def current_items(
    db: Session, stat_date: str, source_ids: list[str] | None = None
) -> list[HotItem]:
    """各源「当前榜单」（last_crawl_time == 该源最新批次时间）汇总。统计信息（crawl_count /
    weight）取自全历史——HotItem 本身就是跨批次聚合出的一行，不用额外处理。"""
    result: list[HotItem] = []
    for source_id in _scoped_source_ids(db, stat_date, source_ids):
        latest = latest_crawl_time(db, stat_date, source_id)
        if latest is None:
            continue
        rows = (
            db.query(HotItem)
            .filter(
                HotItem.stat_date == stat_date,
                HotItem.source_id == source_id,
                HotItem.last_crawl_time == latest,
            )
            .all()
        )
        result.extend(rows)
    return result
