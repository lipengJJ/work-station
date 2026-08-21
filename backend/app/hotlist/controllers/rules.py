"""频率词规则（收敛到主题下）：
/api/hotlist/topics/{id}/rules + /api/hotlist/rules
+ /api/hotlist/global-filters。

- GET/POST /topics/{topic_id}/rules           主题的词组规则列表 / 新建
- PUT/DELETE /rules/{rule_id}                 词组规则更新 / 删除（rule_id 全局唯一）
- POST /topics/{topic_id}/rules/import        粘贴 TrendRadar 文本批量导入到该主题
- POST /topics/{topic_id}/rules/preview       试跑：用该主题的源 + 规则，拿当天已抓数据跑匹配
- GET/POST /global-filters                    全局过滤词列表 / 新建（对所有主题生效）
- DELETE /global-filters/{rule_id}            删除全局过滤词
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.hotlist.models import HotItem, HotKeywordRule, HotTopicSource
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
from app.hotlist.services import keyword_rules, topic_service
from app.hotlist.services.keyword_rules import (
    InvalidRegexError,
    _load_word_list,
    matches_word_groups,
    parse_frequency_text,
    validate_words_for_storage,
)

router = APIRouter(prefix="/api/hotlist", tags=["hotlist-rules"])


def _words_json(words: list[WordIn]) -> str:
    return json.dumps([w.model_dump() for w in words], ensure_ascii=False)


def _validate_or_400(*word_lists: list[WordIn]) -> None:
    try:
        for words in word_lists:
            validate_words_for_storage([w.model_dump() for w in words])
    except InvalidRegexError as exc:
        raise HTTPException(400, str(exc)) from exc


def _ensure_topic(db: Session, topic_id: int) -> None:
    if topic_service.get_topic(db, topic_id) is None:
        raise HTTPException(404, "主题不存在")


def _check_topic_id_consistency(
    payload_topic_id: int | None, topic_id: int
) -> None:
    """创建/更新时校验 payload 里的 topic_id 与归属一致（不允许改归属）。"""
    if payload_topic_id is not None and payload_topic_id != topic_id:
        raise HTTPException(400, "规则归属主题与目标主题不一致，不允许修改归属")


# ------------------------------------------------------------ 主题词组规则 ----

@router.get("/topics/{topic_id}/rules")
def list_rules(
    topic_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> list[RuleOut]:
    _ensure_topic(db, topic_id)
    rows = (
        db.query(HotKeywordRule)
        .filter(
            HotKeywordRule.rule_type == "group",
            HotKeywordRule.topic_id == topic_id,
        )
        .order_by(HotKeywordRule.sort_order.asc(), HotKeywordRule.id.asc())
        .all()
    )
    return [RuleOut.model_validate(row) for row in rows]


@router.post("/topics/{topic_id}/rules")
def create_rule(
    topic_id: int,
    payload: RuleIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> RuleOut:
    _ensure_topic(db, topic_id)
    _check_topic_id_consistency(payload.topic_id, topic_id)
    _validate_or_400(
        payload.normal_words, payload.required_words, payload.exclude_words
    )
    now = datetime.now(timezone.utc)
    row = HotKeywordRule(
        rule_type="group",
        topic_id=topic_id,
        display_name=payload.display_name,
        normal_words=_words_json(payload.normal_words),
        required_words=_words_json(payload.required_words),
        exclude_words=_words_json(payload.exclude_words),
        max_count=payload.max_count,
        enabled=payload.enabled,
        sort_order=payload.sort_order,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return RuleOut.model_validate(row)


@router.put("/rules/{rule_id}")
def update_rule(
    rule_id: int,
    payload: RuleIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> RuleOut:
    row = db.get(HotKeywordRule, rule_id)
    if row is None:
        raise HTTPException(404, "规则不存在")
    if row.rule_type != "group":
        raise HTTPException(400, "全局过滤词请走 /global-filters 接口")
    if payload.topic_id is not None and payload.topic_id != row.topic_id:
        raise HTTPException(400, "规则归属主题与目标主题不一致，不允许修改归属")
    _validate_or_400(
        payload.normal_words, payload.required_words, payload.exclude_words
    )

    row.display_name = payload.display_name
    row.normal_words = _words_json(payload.normal_words)
    row.required_words = _words_json(payload.required_words)
    row.exclude_words = _words_json(payload.exclude_words)
    row.max_count = payload.max_count
    row.enabled = payload.enabled
    row.sort_order = payload.sort_order
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return RuleOut.model_validate(row)


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> dict:
    row = db.get(HotKeywordRule, rule_id)
    if row is not None:
        db.delete(row)
        db.commit()
    return {"ok": True}


# ------------------------------------------------------------ 批量导入 ----

@router.post("/topics/{topic_id}/rules/import")
def import_rules(
    topic_id: int,
    payload: RuleImportIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> RuleImportOut:
    _ensure_topic(db, topic_id)
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
                topic_id=topic_id,
                display_name=group["display_name"],
                normal_words=json.dumps(
                    group["normal_words"], ensure_ascii=False
                ),
                required_words=json.dumps(
                    group["required_words"], ensure_ascii=False
                ),
                exclude_words=json.dumps(
                    group["exclude_words"], ensure_ascii=False
                ),
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
                    [{"word": word, "is_regex": False, "display_name": None}],
                    ensure_ascii=False,
                ),
                enabled=True,
                sort_order=base_sort + len(groups) + idx,
                created_at=now,
                updated_at=now,
            )
        )

    db.commit()
    return RuleImportOut(
        created_groups=len(groups), created_global_filters=len(global_filters)
    )


# ------------------------------------------------------------ 试跑 ----

@router.post("/topics/{topic_id}/rules/preview")
def preview_rule(
    topic_id: int,
    payload: RulePreviewIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> RulePreviewOut:
    """试跑：不落库。拿当天（stat_date=今天）已抓数据跑一遍匹配，
    源范围 = 该主题启用的源，全局过滤词照常生效。"""
    _ensure_topic(db, topic_id)
    _validate_or_400(
        payload.normal_words, payload.required_words, payload.exclude_words
    )

    group = {
        "required": _load_word_list(_words_json(payload.required_words)),
        "normal": _load_word_list(_words_json(payload.normal_words)),
        "exclude": _load_word_list(_words_json(payload.exclude_words)),
        "group_key": "preview",
        "display_name": "预览",
        "max_count": 0,
    }

    source_ids = [
        row[0]
        for row in db.query(HotTopicSource.source_id)
        .filter(
            HotTopicSource.topic_id == topic_id,
            HotTopicSource.enabled.is_(True),
        )
        .all()
    ]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    q = db.query(HotItem).filter(HotItem.stat_date == today)
    if source_ids:
        q = q.filter(HotItem.source_id.in_(source_ids))

    _word_groups, _filter_words, global_filters = keyword_rules.load_rules(
        db, topic_id=topic_id
    )
    matched = [
        item
        for item in q.order_by(HotItem.weight.desc()).all()
        if matches_word_groups(
            f"{item.title} {item.summary}", [group], [], global_filters
        )
    ]

    return RulePreviewOut(
        matched_count=len(matched),
        samples=[
            ItemOut.model_validate(item).model_dump(mode="json")
            for item in matched[: payload.sample_limit]
        ],
    )


# ------------------------------------------------------------ 全局过滤词 ----

@router.get("/global-filters")
def list_global_filters(
    db: Session = Depends(get_db), _=Depends(get_current_user)
) -> list[RuleOut]:
    rows = (
        db.query(HotKeywordRule)
        .filter(HotKeywordRule.rule_type == "global_filter")
        .order_by(HotKeywordRule.sort_order.asc(), HotKeywordRule.id.asc())
        .all()
    )
    return [RuleOut.model_validate(row) for row in rows]


@router.post("/global-filters")
def create_global_filter(
    payload: GlobalFilterIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
) -> RuleOut:
    now = datetime.now(timezone.utc)
    row = HotKeywordRule(
        rule_type="global_filter",
        display_name=payload.word,
        normal_words=json.dumps(
            [{"word": payload.word, "is_regex": False, "display_name": None}],
            ensure_ascii=False,
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


@router.delete("/global-filters/{rule_id}")
def delete_global_filter(
    rule_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
) -> dict:
    row = db.get(HotKeywordRule, rule_id)
    if row is None:
        return {"ok": True}
    if row.rule_type != "global_filter":
        raise HTTPException(400, "该规则不是全局过滤词")
    db.delete(row)
    db.commit()
    return {"ok": True}
