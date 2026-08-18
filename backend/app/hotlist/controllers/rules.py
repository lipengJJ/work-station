"""频率词规则：/api/hotlist/rules/*（全部需要登录）。

- GET/POST/PUT/DELETE /api/hotlist/rules            词组规则 CRUD
- POST   /api/hotlist/rules/global-filters          新建全局过滤词
- POST   /api/hotlist/rules/import                  粘贴 TrendRadar 文本批量导入
- POST   /api/hotlist/rules/preview                  试跑：拿当天已抓数据跑一遍匹配，返回命中样例
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.hotlist.models import HotItem, HotKeywordRule
from app.hotlist.schemas.item import ItemOut
from app.hotlist.schemas.rule import (
    GlobalFilterIn,
    RuleImportIn,
    RuleImportOut,
    RuleIn,
    RuleOut,
    RulePreviewIn,
    RulePreviewOut,
    WordIn,
)
from app.hotlist.services.keyword_rules import (
    InvalidRegexError,
    _load_word_list,
    matches_word_groups,
    parse_frequency_text,
    validate_words_for_storage,
)

router = APIRouter(prefix="/api/hotlist/rules", tags=["hotlist"])


def _words_json(words: list[WordIn]) -> str:
    return json.dumps([w.model_dump() for w in words], ensure_ascii=False)


def _validate_or_400(*word_lists: list[WordIn]) -> None:
    try:
        for words in word_lists:
            validate_words_for_storage([w.model_dump() for w in words])
    except InvalidRegexError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("")
def list_rules(db: Session = Depends(get_db), _=Depends(get_current_user)) -> list[RuleOut]:
    rows = (
        db.query(HotKeywordRule)
        .order_by(HotKeywordRule.sort_order.asc(), HotKeywordRule.id.asc())
        .all()
    )
    return [RuleOut.model_validate(row) for row in rows]


@router.post("")
def create_rule(
    payload: RuleIn, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> RuleOut:
    _validate_or_400(payload.normal_words, payload.required_words, payload.exclude_words)
    now = datetime.now(timezone.utc)
    row = HotKeywordRule(
        rule_type="group",
        display_name=payload.display_name,
        normal_words=_words_json(payload.normal_words),
        required_words=_words_json(payload.required_words),
        exclude_words=_words_json(payload.exclude_words),
        source_ids=json.dumps(payload.source_ids, ensure_ascii=False),
        max_count=payload.max_count,
        enabled=payload.enabled,
        sort_order=payload.sort_order,
        notify_enabled=payload.notify_enabled,
        notify_channel_ids=json.dumps(payload.notify_channel_ids, ensure_ascii=False),
        notify_time_start=payload.notify_time_start,
        notify_time_end=payload.notify_time_end,
        notify_frequency=payload.notify_frequency,
        notify_only_on_hit=payload.notify_only_on_hit,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return RuleOut.model_validate(row)


@router.put("/{rule_id}")
def update_rule(
    rule_id: int,
    payload: RuleIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> RuleOut:
    row = db.get(HotKeywordRule, rule_id)
    if row is None:
        raise HTTPException(404, "规则不存在")
    _validate_or_400(payload.normal_words, payload.required_words, payload.exclude_words)

    row.display_name = payload.display_name
    row.normal_words = _words_json(payload.normal_words)
    row.required_words = _words_json(payload.required_words)
    row.exclude_words = _words_json(payload.exclude_words)
    row.source_ids = json.dumps(payload.source_ids, ensure_ascii=False)
    row.max_count = payload.max_count
    row.enabled = payload.enabled
    row.sort_order = payload.sort_order
    row.notify_enabled = payload.notify_enabled
    row.notify_channel_ids = json.dumps(payload.notify_channel_ids, ensure_ascii=False)
    row.notify_time_start = payload.notify_time_start
    row.notify_time_end = payload.notify_time_end
    row.notify_frequency = payload.notify_frequency
    row.notify_only_on_hit = payload.notify_only_on_hit
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return RuleOut.model_validate(row)


@router.delete("/{rule_id}")
def delete_rule(
    rule_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> dict:
    row = db.get(HotKeywordRule, rule_id)
    if row is not None:
        db.delete(row)
        db.commit()
    return {"ok": True}


@router.post("/global-filters")
def create_global_filter(
    payload: GlobalFilterIn, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> RuleOut:
    now = datetime.now(timezone.utc)
    row = HotKeywordRule(
        rule_type="global_filter",
        display_name=payload.word,
        normal_words=json.dumps(
            [{"word": payload.word, "is_regex": False, "display_name": None}], ensure_ascii=False
        ),
        enabled=payload.enabled,
        sort_order=payload.sort_order,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return RuleOut.model_validate(row)


@router.post("/import")
def import_rules(
    payload: RuleImportIn, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> RuleImportOut:
    try:
        groups, global_filters = parse_frequency_text(payload.text)
    except InvalidRegexError as exc:
        raise HTTPException(400, str(exc)) from exc

    now = datetime.now(timezone.utc)
    base_sort = db.query(HotKeywordRule).count()

    for idx, group in enumerate(groups):
        db.add(
            HotKeywordRule(
                rule_type="group",
                display_name=group["display_name"],
                normal_words=json.dumps(group["normal_words"], ensure_ascii=False),
                required_words=json.dumps(group["required_words"], ensure_ascii=False),
                exclude_words=json.dumps(group["exclude_words"], ensure_ascii=False),
                max_count=group["max_count"],
                enabled=True,
                sort_order=base_sort + idx,
                created_at=now,
                updated_at=now,
            )
        )

    for idx, word in enumerate(global_filters):
        db.add(
            HotKeywordRule(
                rule_type="global_filter",
                display_name=word,
                normal_words=json.dumps(
                    [{"word": word, "is_regex": False, "display_name": None}], ensure_ascii=False
                ),
                enabled=True,
                sort_order=base_sort + len(groups) + idx,
                created_at=now,
                updated_at=now,
            )
        )

    db.commit()
    return RuleImportOut(created_groups=len(groups), created_global_filters=len(global_filters))


@router.post("/preview")
def preview_rule(
    payload: RulePreviewIn, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> RulePreviewOut:
    """试跑：不落库。拿当天（stat_date=今天）已抓数据跑一遍匹配，按 source_ids 限定源。"""
    _validate_or_400(payload.normal_words, payload.required_words, payload.exclude_words)

    group = {
        "required": _load_word_list(_words_json(payload.required_words)),
        "normal": _load_word_list(_words_json(payload.normal_words)),
        "exclude": _load_word_list(_words_json(payload.exclude_words)),
        "group_key": "preview",
        "display_name": "预览",
        "max_count": 0,
    }

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    q = db.query(HotItem).filter(HotItem.stat_date == today)
    if payload.source_ids:
        q = q.filter(HotItem.source_id.in_(payload.source_ids))

    matched = [
        item
        for item in q.order_by(HotItem.weight.desc()).all()
        if matches_word_groups(f"{item.title} {item.summary}", [group], [], [])
    ]

    return RulePreviewOut(
        matched_count=len(matched),
        samples=[ItemOut.model_validate(item).model_dump(mode="json") for item in matched[: payload.sample_limit]],
    )
