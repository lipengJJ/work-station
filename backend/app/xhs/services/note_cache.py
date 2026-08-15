"""
小红书笔记全局去重缓存（TODO.md "小红书笔记数据全局去重缓存"）。

背景：采集任务（tasks.py::_run_task）和追踪任务（tracking.py::run_scan）之前各自
独立调用 spider_note() 抓笔记详情，同一篇笔记被不同任务命中会重复抓取、重复存储，
浪费接口调用次数（且增加触发小红书风控的概率）。这里加一张全局表 XhsNote（note_id
唯一键），命中且未过期就直接复用缓存，不再调用 spider_note()；只有 search_some_note
（发现候选笔记）仍然每次都要调，这个省不掉。

TTL：默认 3 天允许过期重抓——点赞/评论数等互动数据会随时间变化，不能永久冻结旧数据。
超过 TTL 或调用方传 force_refresh=True 时会重新抓一次并覆盖缓存行。

素材（图片/视频）不在这张表的职责范围内：媒体文件继续走 download_note 存本地
storage/xhs_tasks/{id}/media/，media proxy 也一直是直接实时转发 note 里的 CDN
原始 URL（不读本地文件），这张缓存表只是让"文本/互动数据"少发重复的详情请求，
不改变素材下载/展示的现有行为（CDN URL 是否长期有效仍是 TODO 里标注的待验证项，
和这次的改动无关）。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.xhs.models import XhsNote

DEFAULT_TTL_DAYS = 3

# 和 handle_note_info() 的返回字段一一对应，见 app/xhs/services/utils/data_util.py
_LIST_FIELDS = ("image_list", "tags")
_SCALAR_FIELDS = (
    "note_url",
    "note_type",
    "user_id",
    "home_url",
    "nickname",
    "avatar",
    "title",
    "desc",
    "liked_count",
    "collected_count",
    "comment_count",
    "share_count",
    "video_cover",
    "video_addr",
    "upload_time",
    "ip_location",
)


def _row_to_dict(row: XhsNote) -> dict:
    data = {"note_id": row.note_id}
    for field in _SCALAR_FIELDS:
        data[field] = getattr(row, field)
    data["image_list"] = json.loads(row.image_list_json or "[]")
    data["tags"] = json.loads(row.tags_json or "[]")
    return data


def is_fresh(row: XhsNote, max_age_days: float = DEFAULT_TTL_DAYS) -> bool:
    last_fetched = row.last_fetched_at
    if last_fetched.tzinfo is None:
        last_fetched = last_fetched.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last_fetched < timedelta(days=max_age_days)


def get_cached_note(db: Session, note_id: str) -> Optional[dict]:
    row = db.get(XhsNote, note_id)
    return _row_to_dict(row) if row else None


def get_cached_notes_map(db: Session, note_ids: list[str]) -> dict[str, dict]:
    """批量查，避免 list_project_notes 这类按笔记列表读取的场景逐条查询。"""
    if not note_ids:
        return {}
    rows = db.query(XhsNote).filter(XhsNote.note_id.in_(note_ids)).all()
    return {row.note_id: _row_to_dict(row) for row in rows}


def upsert_note(db: Session, note: dict) -> None:
    """
    note 是 handle_note_info() 形状的 dict（19 个字段，含 note_id）。字符串字段用
    str() 兜底转换——interact_info 里的点赞/评论数理论上应该都是字符串，但防止
    小红书接口哪天悄悄改成数字类型时，SQLite 的字符串列插入非字符串值报错。
    """
    note_id = note.get("note_id")
    if not note_id:
        return

    row = db.get(XhsNote, note_id)
    if row is None:
        row = XhsNote(note_id=note_id)
        db.add(row)

    for field in _SCALAR_FIELDS:
        value = note.get(field)
        setattr(row, field, str(value) if value is not None else None)
    row.image_list_json = json.dumps(note.get("image_list") or [], ensure_ascii=False)
    row.tags_json = json.dumps(note.get("tags") or [], ensure_ascii=False)
    row.last_fetched_at = datetime.now(timezone.utc)
    db.commit()


def get_or_fetch_note(
    db: Session,
    note_url: str,
    note_id: str,
    cookies_str: str,
    data_spider,
    max_age_days: float = DEFAULT_TTL_DAYS,
    force_refresh: bool = False,
) -> tuple[bool, str, Optional[dict]]:
    """
    采集任务/追踪任务抓笔记详情时的统一入口，替代直接调用 data_spider.spider_note()。
    返回值形状和 spider_note() 保持一致：(success, message, note_info | None)。

    命中且未过期、且不是强制刷新 → 直接返回缓存，不发请求。
    否则调 spider_note()：成功就覆盖缓存并返回新数据；失败但缓存里有旧数据（哪怕过期）
    就退回旧数据（好过完全拿不到，能对付一次接口抖动/限流），缓存完全没有才真正失败。
    """
    row = db.get(XhsNote, note_id)
    if row and not force_refresh and is_fresh(row, max_age_days):
        return True, "命中全局缓存", _row_to_dict(row)

    try:
        ok, msg, note_info = data_spider.spider_note(note_url, cookies_str)
    except Exception as e:
        from app.xhs.services.xhs_errors import XhsError
        # 分类异常（风控/登录失效/网络重试耗尽）向上传播，由任务层熔断决策；
        # 只有普通异常才降级为"标记失败/退回缓存"
        if isinstance(e, XhsError):
            raise
        ok, msg, note_info = False, str(e), None

    if ok and note_info:
        upsert_note(db, note_info)
        return True, msg, note_info

    if row:
        logger.warning(f"笔记 {note_id} 刷新失败（{msg}），退回缓存里的旧数据")
        return True, f"刷新失败，使用缓存：{msg}", _row_to_dict(row)

    return False, msg, None
