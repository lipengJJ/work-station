"""
关键词搜索采集任务：排队 + 单线程串行执行，进度/结果记在 Task + XhsTaskExtra 两张表里。

抓取逻辑完全复用 spider/spider.py 里 Data_Spider 已有的方法（search_some_note /
spider_note / spider_note_comments）以及 xhs_utils/data_util.py 的 download_note /
save_to_xlsx，但没有直接调用 Data_Spider.spider_some_search_note —— 那个方法是
"一把梭"的黑盒调用，拿不到中间进度，也拿不到解析后的笔记详情用于网页预览。这里按同样的
顺序手动编排一遍，换来：
  1) 逐条更新进度（阶段 + 当前/总数），前端可以画进度条；
  2) 把解析后的笔记/评论落一份 JSON 到 XhsTaskExtra 里，"预览"功能直接读这份数据；
  3) save_choice == 'preview' 时完全不落盘（不下载素材、不导出 excel），
     只用于网页在线预览，不在服务器本地留文件。
串行执行是刻意的：小红书对并发请求风控敏感，多任务同时跑容易触发限流。

除了 create_task/get_task/list_tasks/delete_task/delete_note/get_preview 这几个
接口层会用到的函数以 db: Session 作为参数（和项目里其它 api/*.py 一致），后台 worker
线程本身在请求作用域之外运行，只能自己开关 SessionLocal()。
"""
import ast
import json
import queue
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import openpyxl
from loguru import logger
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Task, XhsTaskExtra
from app.xhs import token_store
from spider.spider import Data_Spider
from xhs_utils.data_util import download_note, save_to_xlsx

STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage" / "xhs_tasks"

_queue: "queue.Queue[int]" = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()


def start_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
        threading.Thread(target=_worker_loop, daemon=True).start()


def requeue_pending_tasks() -> None:
    """进程重启后，把上次遗留的 pending/running xhs 任务重新排队。在 app 启动时调用一次。"""
    db = SessionLocal()
    try:
        rows = db.query(Task).filter(Task.module == "xhs", Task.status.in_(("pending", "running"))).all()
        for row in rows:
            _queue.put(row.id)
    finally:
        db.close()


def task_dir(task_id: int) -> Path:
    return STORAGE_DIR / str(task_id)


def create_task(db: Session, params: dict) -> int:
    task = Task(module="xhs", task_type="xhs_search", status="pending", params=params)
    db.add(task)
    db.flush()  # 拿到自增的 task.id
    db.add(XhsTaskExtra(task_id=task.id, phase="queued"))
    db.commit()
    task_id = task.id
    _queue.put(task_id)
    return task_id


def _list_files(task_id: int) -> dict:
    d = task_dir(task_id)
    excel_dir = d / "excel"
    media_dir = d / "media"
    excel_files = sorted(p.name for p in excel_dir.glob("*.xlsx")) if excel_dir.exists() else []
    media_file_count = sum(1 for p in media_dir.rglob("*") if p.is_file()) if media_dir.exists() else 0
    return {"excel_files": excel_files, "media_file_count": media_file_count}


def _serialize(task: Task, extra: Optional[XhsTaskExtra]) -> dict:
    files = _list_files(task.id)
    has_result_json = bool(extra and extra.result_json)
    return {
        "id": task.id,
        "keyword": (task.params or {}).get("keyword", ""),
        "params": task.params or {},
        "status": task.status,
        "message": task.result_summary,
        "note_count": extra.note_count if extra else 0,
        "phase": extra.phase if extra else "",
        "progress_current": extra.progress_current if extra else 0,
        "progress_total": extra.progress_total if extra else 0,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "files": files,
        "has_preview": has_result_json or bool(files["excel_files"]) or files["media_file_count"] > 0,
        "has_comments": bool(extra and extra.comments_json),
    }


def get_task(db: Session, task_id: int) -> Optional[dict]:
    task = db.get(Task, task_id)
    if not task or task.module != "xhs":
        return None
    extra = db.get(XhsTaskExtra, task_id)
    return _serialize(task, extra)


def list_tasks(db: Session) -> list:
    tasks = db.query(Task).filter(Task.module == "xhs").order_by(Task.created_at.desc()).all()
    results = []
    for task in tasks:
        extra = db.get(XhsTaskExtra, task.id)
        results.append(_serialize(task, extra))
    return results


# 老任务（或者进程重启前刚好没跑完的任务）可能没有 result_json，但素材/Excel 已经实实在在
# 存在磁盘上——素材目录里每篇笔记旁边都有 download_note 写的 info.json（完整笔记详情），
# 没有素材的话就退回去解析 Excel（save_to_xlsx 把所有字段都转成了字符串，image_list/tags
# 这类列表字段是 Python list 的 repr，用 ast.literal_eval 读回来）。

def _cell_to_str(value) -> str:
    if value is None:
        return ""
    s = str(value)
    return "" if s == "None" else s


def _cell_to_list(value) -> list:
    s = _cell_to_str(value)
    if not s:
        return []
    try:
        parsed = ast.literal_eval(s)
    except (ValueError, SyntaxError):
        return []
    return parsed if isinstance(parsed, list) else []


_NOTE_EXCEL_KEYS = [
    "note_id", "note_url", "note_type", "user_id", "home_url", "nickname", "avatar",
    "title", "desc", "liked_count", "collected_count", "comment_count", "share_count",
    "video_cover", "video_addr", "image_list", "tags", "upload_time", "ip_location",
]
_NOTE_LIST_FIELDS = {"image_list", "tags"}
_COMMENT_EXCEL_KEYS = [
    "note_id", "note_url", "comment_id", "user_id", "home_url", "nickname", "avatar",
    "content", "show_tags", "like_count", "upload_time", "ip_location", "pictures",
]
_COMMENT_LIST_FIELDS = {"show_tags", "pictures"}


def _load_rows_from_xlsx(path: Path, keys: list, list_fields: set) -> list:
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        rows = list(wb.active.iter_rows(min_row=2, values_only=True))
    finally:
        wb.close()
    results = []
    for row in rows:
        d = {}
        for key, value in zip(keys, row):
            d[key] = _cell_to_list(value) if key in list_fields else _cell_to_str(value)
        results.append(d)
    return results


def _load_notes_from_media(t_dir: Path) -> list:
    media_dir = t_dir / "media"
    if not media_dir.exists():
        return []
    notes = []
    for info_path in sorted(media_dir.rglob("info.json")):
        try:
            notes.append(json.loads(info_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return notes


def find_excel_file(t_dir: Path) -> Optional[Path]:
    excel_dir = t_dir / "excel"
    if not excel_dir.exists():
        return None
    candidates = [p for p in excel_dir.glob("*.xlsx") if not p.name.endswith("_comments.xlsx")]
    return candidates[0] if candidates else None


def find_comments_file(t_dir: Path) -> Optional[Path]:
    excel_dir = t_dir / "excel"
    if not excel_dir.exists():
        return None
    candidates = list(excel_dir.glob("*_comments.xlsx"))
    return candidates[0] if candidates else None


def get_preview(db: Session, task_id: int) -> Optional[dict]:
    extra = db.get(XhsTaskExtra, task_id)
    if not extra:
        return None
    if extra.result_json:
        notes = json.loads(extra.result_json)
        comments = json.loads(extra.comments_json) if extra.comments_json else []
        return {"notes": notes, "comments": comments}

    t_dir = task_dir(task_id)
    notes = _load_notes_from_media(t_dir)
    if not notes:
        excel_path = find_excel_file(t_dir)
        if excel_path:
            notes = _load_rows_from_xlsx(excel_path, _NOTE_EXCEL_KEYS, _NOTE_LIST_FIELDS)
    comments = []
    comments_path = find_comments_file(t_dir)
    if comments_path:
        comments = _load_rows_from_xlsx(comments_path, _COMMENT_EXCEL_KEYS, _COMMENT_LIST_FIELDS)
    return {"notes": notes, "comments": comments}


def _media_note_dir_map(t_dir: Path) -> dict:
    """note_id -> 它在 media/ 下的目录，扫一遍 info.json 建好映射，批量删除时不用每个笔记都扫一遍。"""
    media_dir = t_dir / "media"
    mapping: dict = {}
    if not media_dir.exists():
        return mapping
    for info_path in media_dir.rglob("info.json"):
        try:
            data = json.loads(info_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        note_id = data.get("note_id")
        if note_id:
            mapping[note_id] = info_path.parent
    return mapping


def delete_notes(db: Session, task_id: int, note_ids: list):
    """
    从预览里删掉一批笔记（单篇删除也是走这个，note_ids 长度为 1）：同步清理它们的素材目录、
    重新导出 Excel（如果原来存了的话），并把裁剪后的结果写回 XhsTaskExtra——这样无论笔记数据
    原本是"仅预览"、从磁盘素材重建、还是从 Excel 重建的，删除之后都固定持久化在数据库里了。
    """
    task = db.get(Task, task_id)
    if not task or task.module != "xhs":
        return False, "not_found", "任务不存在"
    if task.status == "running":
        return False, "running", "任务正在运行中，请等待完成后再操作"

    note_id_set = set(note_ids)
    preview = get_preview(db, task_id) or {"notes": [], "comments": []}
    remaining_notes = [n for n in preview["notes"] if n.get("note_id") not in note_id_set]
    if len(remaining_notes) == len(preview["notes"]):
        return False, "note_not_found", "未找到匹配的笔记"
    remaining_comments = [c for c in preview["comments"] if c.get("note_id") not in note_id_set]

    t_dir = task_dir(task_id)
    note_dir_map = _media_note_dir_map(t_dir)
    for note_id in note_id_set:
        note_dir = note_dir_map.get(note_id)
        if note_dir and note_dir.exists():
            shutil.rmtree(note_dir, ignore_errors=True)

    excel_path = find_excel_file(t_dir)
    if excel_path:
        save_to_xlsx(remaining_notes, str(excel_path))
    comments_path = find_comments_file(t_dir)
    if comments_path:
        if remaining_comments:
            save_to_xlsx(remaining_comments, str(comments_path), "comment")
        else:
            comments_path.unlink(missing_ok=True)

    extra = db.get(XhsTaskExtra, task_id)
    extra.result_json = json.dumps(remaining_notes, ensure_ascii=False)
    extra.comments_json = json.dumps(remaining_comments, ensure_ascii=False) if remaining_comments else None
    extra.note_count = len(remaining_notes)
    task.result_summary = f"完成，{len(remaining_notes)} 篇笔记"
    db.commit()
    return True, "ok", ""


def delete_note(db: Session, task_id: int, note_id: str):
    return delete_notes(db, task_id, [note_id])


def delete_task(db: Session, task_id: int):
    task = db.get(Task, task_id)
    if not task or task.module != "xhs":
        return False, "任务不存在"
    if task.status == "running":
        return False, "任务正在运行中，请等待完成后再删除"
    d = task_dir(task_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    extra = db.get(XhsTaskExtra, task_id)
    if extra:
        db.delete(extra)
    db.delete(task)
    db.commit()
    return True, ""


def _set_progress(db: Session, extra: XhsTaskExtra, phase: str, current: int, total: int) -> None:
    extra.phase = phase
    extra.progress_current = current
    extra.progress_total = total
    db.commit()


def _run_task(task_id: int) -> None:
    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        extra = db.get(XhsTaskExtra, task_id)
        if not task or not extra:
            return

        cookies_str = token_store.get_cookies_str(db)
        if not cookies_str:
            task.status = "failed"
            task.result_summary = "未配置 token/cookie"
            task.finished_at = datetime.now(timezone.utc)
            extra.phase = "failed"
            db.commit()
            return

        params = task.params or {}
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        db.commit()
        _set_progress(db, extra, "searching", 0, 0)

        save_choice = params.get("save_choice", "excel")
        fetch_comments = params.get("fetch_comments", False)
        comment_interval = params.get("comment_interval_seconds")
        max_comments = params.get("max_comments_per_note")
        keyword = params["keyword"]

        t_dir = task_dir(task_id)
        media_dir = t_dir / "media"
        excel_dir = t_dir / "excel"

        try:
            data_spider = Data_Spider()

            success, msg, raw_notes = data_spider.xhs_apis.search_some_note(
                keyword,
                params.get("require_num", 50),
                cookies_str,
                params.get("sort_type_choice", 0),
                params.get("note_type", 0),
                params.get("note_time", 0),
                params.get("note_range", 0),
                0,
                None,
                None,
            )
            if not success:
                raise Exception(msg)

            raw_notes = [n for n in raw_notes if n.get("model_type") == "note"]
            total_notes = len(raw_notes)
            _set_progress(db, extra, "fetching_notes", 0, total_notes)

            parsed_notes = []
            for i, n in enumerate(raw_notes):
                note_url = f"https://www.xiaohongshu.com/explore/{n['id']}?xsec_token={n['xsec_token']}"
                try:
                    ok, note_msg, note_info = data_spider.spider_note(note_url, cookies_str)
                    if ok and note_info:
                        parsed_notes.append(note_info)
                except Exception as e:
                    logger.warning(f"任务 {task_id} 笔记详情抓取失败，跳过: {e}")
                _set_progress(db, extra, "fetching_notes", i + 1, total_notes)

            if save_choice == "all" or "media" in save_choice:
                media_dir.mkdir(parents=True, exist_ok=True)
                _set_progress(db, extra, "downloading_media", 0, len(parsed_notes))
                for i, note_info in enumerate(parsed_notes):
                    try:
                        download_note(note_info, str(media_dir), save_choice)
                    except Exception as e:
                        logger.error(f"笔记 {note_info.get('note_id')} 素材下载失败，跳过: {e}")
                    _set_progress(db, extra, "downloading_media", i + 1, len(parsed_notes))

            all_comments = []
            if fetch_comments:
                _set_progress(db, extra, "fetching_comments", 0, len(parsed_notes))
                for i, note_info in enumerate(parsed_notes):
                    try:
                        _, _, comment_list = data_spider.spider_note_comments(
                            note_info, cookies_str, interval_seconds=comment_interval, max_comments=max_comments,
                        )
                        all_comments.extend(comment_list)
                    except Exception as e:
                        logger.error(f"笔记 {note_info.get('note_id')} 评论抓取失败，跳过: {e}")
                    _set_progress(db, extra, "fetching_comments", i + 1, len(parsed_notes))
                    time.sleep(comment_interval if comment_interval is not None else 1.0)

            if save_choice == "all" or save_choice == "excel":
                _set_progress(db, extra, "exporting", 0, 0)
                excel_dir.mkdir(parents=True, exist_ok=True)
                save_to_xlsx(parsed_notes, str(excel_dir / f"{keyword}.xlsx"))
                if fetch_comments:
                    save_to_xlsx(all_comments, str(excel_dir / f"{keyword}_comments.xlsx"), "comment")

            extra.result_json = json.dumps(parsed_notes, ensure_ascii=False)
            extra.comments_json = json.dumps(all_comments, ensure_ascii=False) if all_comments else None
            extra.note_count = len(parsed_notes)
            extra.phase = "done"
            extra.progress_current = len(parsed_notes)
            extra.progress_total = len(parsed_notes)
            task.status = "success"
            task.result_summary = f"完成，{len(parsed_notes)} 篇笔记"
            task.finished_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as e:
            logger.exception(f"任务 {task_id} 执行失败")
            task.status = "failed"
            task.result_summary = str(e)
            task.finished_at = datetime.now(timezone.utc)
            extra.phase = "failed"
            db.commit()
    finally:
        db.close()


def _worker_loop() -> None:
    while True:
        task_id = _queue.get()
        try:
            _run_task(task_id)
        except Exception:
            logger.exception(f"任务 {task_id} worker 异常")
        finally:
            _queue.task_done()
