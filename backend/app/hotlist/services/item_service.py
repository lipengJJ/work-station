"""热榜条目查询服务：榜单列表 / 条目详情的查询逻辑集中在这里。

controller（hotlist.py）只做参数解析、HTTP 异常转换与编排，不再直接拼 ORM
查询，避免 Web 层与表结构耦合（Google 规范：分层单向依赖，controller 不直达数据层）。
"""
from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.hotlist.models import (
    HotItem,
    HotRankHistory,
    HotSemanticHit,
    HotSource,
    HotTopic,
)
from app.hotlist.schemas.item import (
    ItemDetailOut,
    ItemOut,
    ItemPage,
    RankPointOut,
)
from app.hotlist.services import source_service

VALID_SORTS = {"weight", "rank", "time"}


def get_item(db: Session, item_id: int) -> HotItem | None:
    """按 id 取条目；不存在返回 None。"""
    return db.get(HotItem, item_id)


def _escape_like(value: str) -> str:
    """转义 LIKE 通配符（% _ \\），避免用户输入的关键词被当成模式匹配。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def attach_hit_rules(db: Session, items_out: list[ItemOut]) -> None:
    """批量回填每条条目命中的主题显示名（一次 join 查询，避免逐条查询 N+1）。"""
    if not items_out:
        return
    item_ids = [it.id for it in items_out]
    rows = (
        db.query(HotSemanticHit.item_id, HotTopic.name)
        .join(HotTopic, HotTopic.id == HotSemanticHit.topic_id)
        .filter(HotSemanticHit.item_id.in_(item_ids))
        .all()
    )
    names_by_item: dict[int, list[str]] = {}
    for item_id, name in rows:
        names_by_item.setdefault(item_id, []).append(name or "未命名主题")
    for it in items_out:
        it.hit_rules = names_by_item.get(it.id, [])


def list_items(
    db: Session,
    *,
    q: str,
    group: str,
    stat_date: str,
    sort: str,
    hit_only: bool,
    page: int,
    page_size: int,
) -> ItemPage:
    """按筛选条件分页查询条目。sort 非法或 group 不存在时抛 ValueError，由 controller 转 400。"""
    if sort not in VALID_SORTS:
        raise ValueError(f"未知排序: {sort}（可选：weight/rank/time）")

    query = db.query(HotItem)
    if group:
        group_source_ids = source_service.resolve_group_source_ids(db, group)
        if group_source_ids:
            query = query.filter(HotItem.source_id.in_(group_source_ids))
        else:
            # 分组存在但一个源都没有，直接返回空结果
            query = query.filter(HotItem.id == -1)
    if stat_date:
        query = query.filter(HotItem.stat_date == stat_date)
    if hit_only:
        # 只保留有语义命中记录（HotSemanticHit）的条目
        hit_item_ids = [
            row[0]
            for row in db.query(HotSemanticHit.item_id.distinct()).all()
        ]
        query = query.filter(HotItem.id.in_(hit_item_ids))
    keyword = q.strip()
    if keyword:
        pattern = f"%{_escape_like(keyword)}%"
        matching_source_ids = [
            row[0]
            for row in (
                db.query(HotSource.id)
                .filter(HotSource.name.like(pattern, escape="\\"))
                .all()
            )
        ]
        conditions = [
            HotItem.title.like(pattern, escape="\\"),
            HotItem.summary.like(pattern, escape="\\"),
        ]
        if matching_source_ids:
            conditions.append(HotItem.source_id.in_(matching_source_ids))
        query = query.filter(or_(*conditions))

    if sort == "time":
        query = query.order_by(HotItem.last_crawl_time.desc(), HotItem.id.desc())
    elif sort == "rank":
        query = query.order_by(HotItem.rank.asc(), HotItem.weight.desc())
    else:
        query = query.order_by(HotItem.weight.desc(), HotItem.id.desc())

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items_out = [ItemOut.model_validate(row) for row in rows]
    attach_hit_rules(db, items_out)
    return ItemPage(
        items=items_out,
        total=total,
        page=page,
        page_size=page_size,
    )


def get_item_detail(db: Session, item_id: int) -> ItemDetailOut | None:
    """条目详情 + 榜位时间线；条目不存在返回 None。"""
    item = get_item(db, item_id)
    if item is None:
        return None
    history = (
        db.query(HotRankHistory)
        .filter(HotRankHistory.item_id == item_id)
        .order_by(HotRankHistory.crawl_time.asc())
        .all()
    )
    item_out = ItemOut.model_validate(item)
    attach_hit_rules(db, [item_out])
    return ItemDetailOut(
        item=item_out,
        history=[RankPointOut.model_validate(row) for row in history],
    )