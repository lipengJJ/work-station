"""热点摘要三模式（daily / incremental / current）组装。

拆成四个纯函数，不照抄旧 ai_trending 参考的 TrendRadar analyzer.py::count_word_frequency
（400 行、17 个参数，是 CLI 里为避免全局状态一路传参的产物）：

    select_scope(db, mode, stat_date, source_ids) -> list[HotItem]
    match_groups(items, word_groups, global_filters)
    -> dict[rule_id, list[HotItem]]
    rank_within_group(items, max_count)           -> list[HotItem]
    build_digest(db, mode, stat_date, source_ids) -> dict
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.hotlist.models import HotItem
from app.hotlist.services import diff_service, keyword_rules


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


def match_groups(
    items: list[HotItem], word_groups: list[dict], global_filters: list[str]
) -> dict[int, list[HotItem]]:
    """按频率词规则把条目分到各自的词组下；一个条目命中多个词组时，每个词组都记一份。
    标题 + 摘要一起匹配，理由见 crawl_service.match_rules_and_record_hits 里的注释。"""
    grouped: dict[int, list[HotItem]] = {}
    for item in items:
        match_text = f"{item.title} {item.summary}"
        for rule_id in keyword_rules.match_groups(
            match_text, word_groups, global_filters
        ):
            grouped.setdefault(rule_id, []).append(item)
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
    """摘要组装主入口。没有配置任何词组规则时退化成「全部条目」一组，
    保证摘要页在用户还没配规则时也有内容可看，不是一片空白。"""
    items = select_scope(db, mode, stat_date, source_ids)
    word_groups, _filter_words, global_filters = keyword_rules.load_rules(db)

    if not word_groups:
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

    grouped = match_groups(items, word_groups, global_filters)
    meta_by_rule_id = {g["rule_id"]: g for g in word_groups}

    groups_out = []
    for rule_id, group_items in grouped.items():
        meta = meta_by_rule_id.get(rule_id, {})
        ranked = rank_within_group(group_items, meta.get("max_count", 0))
        groups_out.append(
            {
                "rule_id": rule_id,
                "display_name": meta.get("display_name") or "未命名规则",
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
