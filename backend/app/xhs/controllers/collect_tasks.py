from __future__ import annotations

import io
import zipfile

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_current_user_for_media
from app.core.database import get_db
from app.xhs.schemas.xhs import (
    BatchDeleteNotesIn,
    CollectTaskIn,
    IncrementalCollectIn,
    ManualTokenIn,
    PhoneSendIn,
    PhoneVerifyIn,
)
from app.xhs.services import login, media_proxy, tasks, token_store

router = APIRouter(prefix="/api/xhs", tags=["xhs"])

_VALID_SAVE_CHOICES = ("all", "excel", "media", "media-image", "media-video", "preview")


# --------------------------------------------------------------- token ----

@router.get("/token")
def get_token(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return token_store.get_status(db)


@router.get("/token/full")
def get_token_full(db: Session = Depends(get_db), _=Depends(get_current_user)):
    cookies_str = token_store.get_cookies_str(db)
    if not cookies_str:
        raise HTTPException(404, "尚未配置 token")
    return {"cookies": cookies_str}


@router.post("/token")
def set_token(body: ManualTokenIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    token_store.set_cookies_str(db, body.cookies.strip())
    return token_store.get_status(db)


@router.delete("/token")
def clear_token(db: Session = Depends(get_db), _=Depends(get_current_user)):
    token_store.clear(db)
    return token_store.get_status(db)


# --------------------------------------------------------- login: qrcode ----

@router.post("/login/qrcode/start")
def qrcode_start(_=Depends(get_current_user)):
    return login.start_qrcode_login()


@router.get("/login/qrcode/status")
def qrcode_status(qr_id: str = Query(...), db: Session = Depends(get_db), _=Depends(get_current_user)):
    return login.poll_qrcode_login(db, qr_id)


# ---------------------------------------------------------- login: phone ----

@router.post("/login/phone/send_code")
def phone_send(body: PhoneSendIn, _=Depends(get_current_user)):
    return login.send_phone_code(body.phone, body.zone)


@router.post("/login/phone/verify")
def phone_verify(body: PhoneVerifyIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return login.verify_phone_login(db, body.phone, body.code, body.zone)


# ------------------------------------------------------------------ tasks ----

@router.post("/collect-tasks")
def create_collect_task(body: CollectTaskIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    if not token_store.get_cookies_str(db):
        raise HTTPException(400, "尚未配置小红书 token/cookie，请先在上方获取")
    if body.save_choice not in _VALID_SAVE_CHOICES:
        raise HTTPException(400, "不支持的保存方式")

    params = {
        "keyword": body.keyword.strip(),
        "require_num": body.require_num,
        "sort_type_choice": body.sort_type_choice,
        "note_type": body.note_type,
        "note_time": body.note_time,
        "note_range": body.note_range,
        "save_choice": body.save_choice,
        "fetch_comments": body.fetch_comments,
        "max_comments_per_note": body.max_comments_per_note,
        "comment_interval_seconds": body.comment_interval_seconds,
    }
    task_id = tasks.create_task(db, params)
    return tasks.get_task(db, task_id)


@router.get("/collect-tasks")
def list_collect_tasks(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return tasks.list_tasks(db)


@router.get("/collect-tasks/{task_id}")
def get_collect_task(task_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    task = tasks.get_task(db, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.post("/collect-tasks/{task_id}/incremental")
def incremental_collect_task(
    task_id: int, body: IncrementalCollectIn, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    """
    在已有主题基础上增量采集：跳过已经采集过的笔记，只补齐 increment_count 篇新的。
    实际抓取跑在后台 worker 线程（和全新采集共用同一个串行队列），这里只负责校验
    + 排队，立刻返回。
    """
    ok, msg = tasks.start_incremental_task(db, task_id, body.increment_count)
    if not ok:
        status_code = 404 if msg == "任务不存在" else 400
        raise HTTPException(status_code, msg)
    return tasks.get_task(db, task_id)


@router.delete("/collect-tasks/{task_id}")
def delete_collect_task(task_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    ok, msg = tasks.delete_task(db, task_id)
    if not ok:
        status_code = 404 if msg == "任务不存在" else 409
        raise HTTPException(status_code, msg)
    return {"success": True}


@router.get("/collect-tasks/{task_id}/preview")
def get_collect_task_preview(task_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    task = tasks.get_task(db, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return tasks.get_preview(db, task_id) or {"notes": [], "comments": []}


@router.delete("/collect-tasks/{task_id}/notes/{note_id}")
def delete_collect_task_note(
    task_id: int, note_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    ok, code, msg = tasks.delete_note(db, task_id, note_id)
    if not ok:
        status_code = {"not_found": 404, "note_not_found": 404, "running": 409}.get(code, 400)
        raise HTTPException(status_code, msg)
    return tasks.get_task(db, task_id)


@router.delete("/collect-tasks/{task_id}/notes")
def delete_collect_task_notes(
    task_id: int, body: BatchDeleteNotesIn, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    ok, code, msg = tasks.delete_notes(db, task_id, body.note_ids)
    if not ok:
        status_code = {"not_found": 404, "note_not_found": 404, "running": 409}.get(code, 400)
        raise HTTPException(status_code, msg)
    return tasks.get_task(db, task_id)


@router.get("/collect-tasks/{task_id}/download/{kind}")
def download_collect_task(
    task_id: int, kind: str, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    task = tasks.get_task(db, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    t_dir = tasks.task_dir(task_id)

    if kind == "excel":
        path = tasks.find_excel_file(t_dir)
        if not path:
            raise HTTPException(404, "暂无笔记 Excel 文件")
        return FileResponse(path, filename=path.name)

    if kind == "comments":
        path = tasks.find_comments_file(t_dir)
        if not path:
            raise HTTPException(404, "暂无评论 Excel 文件")
        return FileResponse(path, filename=path.name)

    if kind == "archive":
        if not t_dir.exists():
            raise HTTPException(404, "暂无数据")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in t_dir.rglob("*"):
                if file_path.is_file():
                    zf.write(file_path, file_path.relative_to(t_dir))
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="xhs-task-{task_id}.zip"'},
        )

    raise HTTPException(400, "不支持的下载类型")


# ------------------------------------------------------------- media proxy ----

@router.get("/proxy/media")
def proxy_media(
    url: str = Query(...),
    note_id: Optional[str] = Query(default=None),
    kind: Optional[str] = Query(default=None, description="image | video | cover"),
    index: Optional[int] = Query(default=None, description="kind=image 时，第几张图集图"),
    range: Optional[str] = Header(default=None),
    _=Depends(get_current_user_for_media),
):
    if not media_proxy.is_allowed_url(url):
        raise HTTPException(400, "不支持的资源地址")

    # 小红书 CDN 的图片/视频 URL 实测会过期（采集完约一天后就 403），优先发本地已经
    # 下载好的文件，避免重新请求一个大概率已经失效的远程地址。note_id/kind 是可选的
    # ——老代码/还没升级的调用方不传这两个参数，直接走原来"请求远程 URL"的行为。
    if note_id and kind:
        local_path = media_proxy.find_local_media_file(note_id, kind, index)
        if local_path:
            return FileResponse(local_path)

    try:
        resp = media_proxy.fetch(url, range_header=range)
    except Exception as e:
        raise HTTPException(502, f"获取资源失败: {e}")

    headers = {}
    for h in ("Content-Range", "Accept-Ranges", "Content-Length"):
        if h in resp.headers:
            headers[h] = resp.headers[h]
    status_code = 206 if resp.status_code == 206 else 200
    return StreamingResponse(
        resp.iter_content(chunk_size=65536),
        media_type=resp.headers.get("Content-Type", "application/octet-stream"),
        status_code=status_code,
        headers=headers,
    )
