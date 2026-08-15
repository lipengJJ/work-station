"""
评论"写穿层"：采集任务边爬评论边批量 upsert 到 xhs_note_comments 表。

设计（参考 MediaCrawler 的回调式评论存储）：crawler 每翻一页 → spider 结构化 →
on_batch 回调 → 这里落库。同时保留 XhsTaskExtra.comments_json（现有 Excel/预览逻辑
继续用 JSON），本表是增量收益：崩溃续采不丢已爬评论、可按 note_id 查询、
删除笔记时联动删除评论。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.xhs.models.xhs_note_comment import XhsNoteComment


def save_comment_batch(db: Session, comments: list[dict]) -> int:
    """
    批量 upsert 评论（按 comment_id 去重，重复爬取时覆盖为最新值）。
    comments 为 handle_comment_info 格式化后的列表（13 字段 + 可选 parent_comment_id）。
    返回本次实际落库条数。
    """
    if not comments:
        return 0
    ids = [c.get("comment_id") for c in comments if c.get("comment_id")]
    if not ids:
        return 0

    existing = {
        row.comment_id: row
        for row in db.query(XhsNoteComment)
        .filter(XhsNoteComment.comment_id.in_(ids))
        .all()
    }
    now = datetime.now(timezone.utc)
    count = 0
    for c in comments:
        cid = c.get("comment_id")
        if not cid:
            continue
        row = existing.get(cid)
        if row is None:
            row = XhsNoteComment(comment_id=cid)
            db.add(row)
        row.note_id = c.get("note_id") or ""
        row.content = str(c.get("content") or "")[:4000]
        row.like_count = c.get("like_count") or 0
        row.nickname = c.get("nickname") or ""
        row.user_id = c.get("user_id") or ""
        row.home_url = c.get("home_url") or ""
        row.parent_comment_id = c.get("parent_comment_id") or ""
        row.create_time = c.get("upload_time") or ""
        row.last_fetched_at = now
        count += 1
    db.commit()
    return count


def delete_comments_for_notes(db: Session, note_ids: list[str]) -> int:
    """删除笔记时联动删除其评论行，返回删除条数"""
    if not note_ids:
        return 0
    deleted = (
        db.query(XhsNoteComment)
        .filter(XhsNoteComment.note_id.in_(note_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def list_comments_for_note(
    db: Session, note_id: str, page: int = 1, page_size: int = 50,
) -> tuple[list[dict], int, str]:
    """
    按笔记查评论（笔记详情"查看评论"入口）。

    数据来源两级：
    1. xhs_note_comments 表（重构后的写穿层，新采集任务的评论实时落库）
    2. 表里没有 → fallback 扫 XhsTaskExtra.comments_json（旧版任务评论只存 JSON，
       按评论里的 note_id 字段过滤）

    返回 (items, total, source)：source 为 "table" / "task_json" / "none"。
    """
    from app.xhs.models import XhsTaskExtra

    def _row_to_item(row: XhsNoteComment) -> dict:
        return {
            "comment_id": row.comment_id,
            "note_id": row.note_id,
            "content": row.content,
            "like_count": row.like_count,
            "nickname": row.nickname,
            "user_id": row.user_id,
            "home_url": row.home_url,
            "parent_comment_id": row.parent_comment_id,
            "create_time": row.create_time,
        }

    total = db.query(XhsNoteComment).filter(XhsNoteComment.note_id == note_id).count()
    if total:
        rows = (
            db.query(XhsNoteComment)
            .filter(XhsNoteComment.note_id == note_id)
            .order_by(XhsNoteComment.create_time.asc(), XhsNoteComment.comment_id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return [_row_to_item(r) for r in rows], total, "table"

    # fallback：旧版任务 comments_json（评论条目里带 note_id 字段）
    import json as _json

    extras = (
        db.query(XhsTaskExtra)
        .filter(XhsTaskExtra.comments_json.isnot(None), XhsTaskExtra.comments_json != "")
        .all()
    )
    for extra in extras:
        try:
            comments = _json.loads(extra.comments_json) or []
        except (TypeError, ValueError):
            continue
        matched = [c for c in comments if c.get("note_id") == note_id]
        if matched:
            total = len(matched)
            start = (page - 1) * page_size
            items = matched[start : start + page_size]
            return items, total, "task_json"

    return [], 0, "none"
