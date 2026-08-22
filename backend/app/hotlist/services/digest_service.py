"""热点摘要三模式（daily / incremental / current）组装。

拆成四个纯函数，不照抄旧 ai_trending 参考的 TrendRadar analyzer.py::count_word_frequency
（400 行、17 个参数，是 CLI 里为避免全局状态一路传参的产物）：

    select_scope(db, mode, stat_date, source_ids) -> list[HotItem]
    group_by_topic_hits(db, items)                 -> dict[topic_id, list[HotItem]]
    rank_within_group(items, max_count)            -> list[HotItem]
    build_digest(db, mode, stat_date, source_ids)  -> dict

分组依据不再是关键词规则，而是语义检索写入的 HotSemanticHit：条目被哪个主题
语义召回，就归到哪个主题组（rule_id 字段沿用旧字段名，值为 topic_id）。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.hotlist.models import HotItem, HotSemanticHit, HotTopic
from app.hotlist.services import diff_service


def select_scope(
    db: Session, mode: str, stat_date: str, source_ids: list[str] | None = None
) -> list[HotItem]:
    """按模式选数据范围：daily=当天全部；incremental=只看新增；current=当前榜单。"""
    if mode == "incremental":
        return diff_service.incremental_items(db, stat_date, source_ids)
    if mode == "current":
        return diff_service.current_items(db, stat_date, source_ids)
    q = db.query(HotItem).filter(HotItem.stat_date == stat_date)
    if source_ids:
        q = q.filter(HotItem.source_id.in_(source_ids))
    return q.all()


def group_by_topic_hits(db: Session, items: list[HotItem]) -> dict[int, list[HotItem]]:
    """按语义命中把条目分到各自命中的主题下；一个条目命中多个主题时，每个主题都记一份。"""
    if not items:
        return {}
    item_ids = [it.id for it in items]
    rows = (
        db.query(HotSemanticHit.topic_id, HotSemanticHit.item_id)
        .filter(HotSemanticHit.item_id.in_(item_ids))
        .all()
    )
    grouped: dict[int, list[HotItem]] = {}
    by_id = {it.id: it for it in items}
    for topic_id, item_id in rows:
        item = by_id.get(item_id)
        if item is not None:
            grouped.setdefault(topic_id, []).append(item)
    return grouped


def rank_within_group(
    items: list[HotItem], max_count: int = 0
) -> list[HotItem]:
    """组内排序（按 weight 降序）+ max_count 限量（0 = 不限）。"""
    ordered = sorted(items, key=lambda it: (it.weight, it.id), reverse=True)
    return ordered[:max_count] if max_count > 0 else ordered


def build_digest(
    db: Session, mode: str, stat_date: str, source_ids: list[str] | None = None
) -> dict:
    """摘要组装主入口。没有任何语义命中时退化成「全部条目」一组，
    保证摘要页在还没有语义命中时也有内容可看，不是一片空白。"""
    items = select_scope(db, mode, stat_date, source_ids)
    if not items:
        return {
            "mode": mode,
            "stat_date": stat_date,
            "total_items": 0,
            "groups": [],
        }

    grouped = group_by_topic_hits(db, items)

    if not grouped:
        ranked = rank_within_group(items)
        groups_out = (
            [{"rule_id": None, "display_name": "全部条目", "items": ranked}]
            if ranked
            else []
        )
        return {
            "mode": mode,
            "stat_date": stat_date,
            "total_items": len(items),
            "groups": groups_out,
        }

    topic_meta = {
        t.id: t
        for t in db.query(HotTopic)
        .filter(HotTopic.id.in_(grouped.keys()))
        .all()
    }

    groups_out = []
    for topic_id, group_items in grouped.items():
        meta = topic_meta.get(topic_id)
        ranked = rank_within_group(group_items, meta.max_items if meta else 0)
        groups_out.append(
            {
                "rule_id": topic_id,
                "display_name": meta.name if meta else "未命名主题",
                "items": ranked,
            }
        )
    groups_out.sort(key=lambda g: -len(g["items"]))

    return {
        "mode": mode,
        "stat_date": stat_date,
        "total_items": len(items),
        "groups": groups_out,
    }
