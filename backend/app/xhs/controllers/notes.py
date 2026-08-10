from __future__ import annotations

import threading
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.common.models import Task
from app.common.services.zhipu_config import get_zhipu_config
from app.core.database import SessionLocal, get_db
from app.xhs.models import XhsTaskExtra
from app.xhs.services import note_cache, note_structurer, tasks, token_store
from app.xhs.services.spider import Data_Spider

router = APIRouter(prefix="/api/xhs", tags=["xhs-notes"])

_backfill_lock = threading.Lock()
_backfill_running: set[int] = set()


def _run_structured_backfill(task_id: int, notes: list[dict]) -> None:
    db = SessionLocal()
    try:
        def update_progress(current: int, total: int, _counts: dict[str, int]) -> None:
            progress_db = SessionLocal()
            try:
                extra = progress_db.get(XhsTaskExtra, task_id)
                if extra:
                    extra.phase = "ai_processing"
                    extra.progress_current = current
                    extra.progress_total = total
                    progress_db.commit()
            finally:
                progress_db.close()

        counts = note_structurer.structure_notes_concurrently(db, notes, update_progress)
        extra = db.get(XhsTaskExtra, task_id)
        if extra:
            extra.phase = "ai_processing_done" if not counts["failed"] else "ai_processing_partial"
            extra.progress_current = len(notes)
            extra.progress_total = len(notes)
            db.commit()
    except Exception:
        db.rollback()
        extra = db.get(XhsTaskExtra, task_id)
        if extra:
            extra.phase = "ai_processing_failed"
            db.commit()
    finally:
        db.close()
        with _backfill_lock:
            _backfill_running.discard(task_id)


@router.get("/notes")
def list_note_tasks(
    query: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """笔记管理首页：只列出已经有笔记数据的采集任务，支持关键词搜索/状态筛选/分页。"""
    return tasks.list_note_tasks_page(db, query=query, status=status, page=page, page_size=page_size)


@router.get("/notes/{task_id}")
def get_note_task_notes(
    task_id: int,
    query: Optional[str] = None,
    note_type: Optional[str] = None,
    date_range: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    task = tasks.get_task(db, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    result = tasks.get_task_notes_page(
        db, task_id, query=query, note_type=note_type, date_range=date_range, page=page, page_size=page_size,
    )
    return result or {"items": [], "total": 0, "page": page, "page_size": page_size}


@router.post("/notes/tasks/{task_id}/ai-process")
def process_existing_task_notes(task_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """使用智谱补处理该主题中缺失、失败或内容已变化的存量结构化数据。"""
    task = db.get(Task, task_id)
    if not task or task.module != "xhs":
        raise HTTPException(404, "任务不存在")
    if task.status in ("pending", "running"):
        raise HTTPException(409, "该主题正在采集中，请等待采集完成后再处理")
    api_key, _model = get_zhipu_config(db)
    if not api_key:
        raise HTTPException(400, "尚未配置智谱 API Key，请先在系统设置中配置")

    preview = tasks.get_preview(db, task_id) or {"notes": []}
    pending_notes = note_structurer.notes_needing_processing(db, preview.get("notes") or [])
    if not pending_notes:
        return {"started": False, "pending_count": 0, "message": "该主题的 AI 结构化数据已完整，无需处理"}

    with _backfill_lock:
        if task_id in _backfill_running:
            raise HTTPException(409, "该主题正在进行 AI 数据处理")
        _backfill_running.add(task_id)

    extra = db.get(XhsTaskExtra, task_id)
    if extra:
        extra.phase = "ai_processing"
        extra.progress_current = 0
        extra.progress_total = len(pending_notes)
        db.commit()

    threading.Thread(target=_run_structured_backfill, args=(task_id, pending_notes), daemon=True).start()
    return {"started": True, "pending_count": len(pending_notes), "message": f"已开始处理 {len(pending_notes)} 篇缺失或失败的笔记"}


@router.get("/notes/{note_id}/structured")
def get_note_structured_data(note_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """
    查看智谱 GLM 结构化预处理产出的数据（《小红书笔记结构化预处理-技术方案.md》）。
    XhsNoteStructured 按 note_id 全局存一份，跟具体属于哪个采集任务无关，这里直接
    单主键查询，不需要 task_id。
    """
    data = note_structurer.get_structured_map(db, [note_id]).get(note_id)
    if not data:
        raise HTTPException(404, "该笔记暂无 AI 结构化数据")
    return data


@router.post("/notes/{note_id}/refresh")
def refresh_note(note_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """
    手动刷新一篇笔记的全局缓存（TODO.md 里提到的"UI 上提供刷新入口"）。只能刷新已经
    进过全局缓存的笔记——note_url 从缓存行里取，不需要调用方再传一遍任务/笔记来源。
    还没进过缓存的笔记（比如全局表刚上线、这篇笔记还没被任何页面读取过）无法在这里
    刷新，先打开笔记详情或 AI 分析选中它一次，会自动回填进缓存。
    """
    cached = note_cache.get_cached_note(db, note_id)
    if not cached:
        raise HTTPException(404, "该笔记还没有进入全局缓存，暂时无法刷新")

    cookies_str = token_store.get_cookies_str(db)
    if not cookies_str:
        raise HTTPException(400, "尚未配置小红书 token/cookie")

    ok, msg, note_info = note_cache.get_or_fetch_note(
        db, cached["note_url"], note_id, cookies_str, Data_Spider(), force_refresh=True
    )
    if not ok or not note_info:
        raise HTTPException(400, f"刷新失败：{msg}")
    return note_info
