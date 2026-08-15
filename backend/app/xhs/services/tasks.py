"""
关键词搜索采集任务：排队 + 单线程串行执行，进度/结果记在 Task + XhsTaskExtra 两张表里。

抓取逻辑完全复用 services/spider.py 里 Data_Spider 已有的方法（search_some_note /
spider_note / spider_note_comments）以及 services/utils/data_util.py 的 download_note /
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
import random
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import openpyxl
from loguru import logger
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.common.models import Task
from app.xhs.models import XhsCollectStats, XhsTaskExtra, XhsTaskPendingOp
from app.xhs.services import note_cache, note_preprocess, note_structurer, token_store
from app.xhs.services.spider import Data_Spider
from app.xhs.services.utils.data_util import download_note, save_to_xlsx
from app.xhs.services.xhs_errors import XhsAuthError, XhsError, XhsNotFoundError, XhsRateLimitError

STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage" / "xhs_tasks"

# 队列里放 (kind, id, payload) 而不是单纯的 task_id——追踪任务（app/xhs/tracking.py）的
# 定时扫描、增量采集都要走这同一个单线程 worker（小红书对并发请求风控敏感，所有抓取
# 必须串行），worker 按 kind 分发。payload 目前只有 incremental 会用（带 increment_count），
# 其余 kind 传 None。
_queue: "queue.Queue[tuple[str, int, Optional[dict]]]" = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()


def start_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
        threading.Thread(target=_worker_loop, daemon=True).start()


def enqueue_collect_task(task_id: int) -> None:
    _queue.put(("collect", task_id, None))


def enqueue_incremental_task(task_id: int, increment_count: int) -> None:
    _queue.put(("incremental", task_id, {"increment_count": increment_count}))


def enqueue_tracking_scan(tracking_task_id: int) -> None:
    _queue.put(("tracking", tracking_task_id, None))


def requeue_pending_tasks() -> None:
    """
    进程重启后，把上次遗留的 pending/running xhs 任务重新排队。在 app 启动时调用一次。

    按 XhsTaskPendingOp 里记的操作类型分发——增量采集中途重启，绝不能被当成全新采集
    重跑（那会用 task.params 里的原始关键词从头搜索，把已经积累的笔记数据整个覆盖掉）。
    找不到记录（比如这个功能上线前就已经卡住的老任务）按原来的行为走全新采集。
    """
    db = SessionLocal()
    try:
        rows = db.query(Task).filter(Task.module == "xhs", Task.status.in_(("pending", "running"))).all()
        for row in rows:
            pending_op = db.get(XhsTaskPendingOp, row.id)
            if pending_op and pending_op.op_type == "incremental":
                payload = json.loads(pending_op.payload_json or "{}")
                enqueue_incremental_task(row.id, payload.get("increment_count", 50))
            else:
                enqueue_collect_task(row.id)
    finally:
        db.close()


def task_dir(task_id: int) -> Path:
    return STORAGE_DIR / str(task_id)


def create_task(db: Session, params: dict) -> int:
    task = Task(module="xhs", task_type="xhs_search", status="pending", params=params)
    db.add(task)
    db.flush()  # 拿到自增的 task.id
    db.add(XhsTaskExtra(task_id=task.id, phase="queued"))
    db.add(XhsTaskPendingOp(task_id=task.id, op_type="collect"))
    db.commit()
    task_id = task.id
    enqueue_collect_task(task_id)
    return task_id


def start_incremental_task(db: Session, task_id: int, increment_count: int, download_video: bool | None = None, fetch_comments: bool | None = None) -> tuple[bool, str]:
    """
    供 controller 调用：校验 + 把任务标成排队中 + 记下这是一次增量采集 + 入队。
    实际抓取逻辑在 _run_incremental_task，跑在 worker 线程里。
    """
    task = db.get(Task, task_id)
    if not task or task.module != "xhs":
        return False, "任务不存在"
    if task.status in ("pending", "running"):
        return False, "该任务正在采集中，请稍后再试"
    if not token_store.get_cookies_str(db):
        return False, "尚未配置小红书 token/cookie，请先在上方获取"

    task.status = "pending"
    pending_op = db.get(XhsTaskPendingOp, task_id)
    if pending_op is None:
        pending_op = XhsTaskPendingOp(task_id=task_id)
        db.add(pending_op)
    pending_op.op_type = "incremental"
    pending_op.payload_json = json.dumps({"increment_count": increment_count}, ensure_ascii=False)
    # 增量采集的覆盖开关（下载视频/抓取评论）：显式传了（非 None）就覆盖任务的持久化参数，
    # _run_incremental_task 读 params 时即生效；不传沿用原设置。
    # 注意必须 dict(...) 复制一份再赋值——直接原地改再赋回同一对象，SQLAlchemy
    # 认为属性值未变化，不会生成 UPDATE，参数就静默丢掉了。
    if download_video is not None or fetch_comments is not None:
        params = dict(json.loads(task.params)) if isinstance(task.params, str) else dict(task.params or {})
        if download_video is not None:
            params["download_video"] = download_video
        if fetch_comments is not None:
            params["fetch_comments"] = fetch_comments
        task.params = json.dumps(params, ensure_ascii=False) if isinstance(task.params, str) else params
    db.commit()

    enqueue_incremental_task(task_id, increment_count)
    return True, ""


def _clear_pending_op(db: Session, task_id: int) -> None:
    db.query(XhsTaskPendingOp).filter(XhsTaskPendingOp.task_id == task_id).delete()
    db.commit()


# ------------------------------------------------------------------ 补抓评论 ----
# "更新评论"按钮：对任务里还没有评论的笔记尝试补抓（Playwright 页面级爬取）。
# 用独立后台线程跑（与采集 worker 串行队列互不干扰），重复触发用 set 保护。

_missing_comments_lock = threading.Lock()
_missing_comments_running: set[int] = set()


def _notes_with_existing_comments(db: Session, note_ids: list[str], task_id: int) -> set[str]:
    """返回已有评论的 note_id 集合：评论表 + 任务 comments_json 里出现过的都算。"""
    have = set()
    if not note_ids:
        return have
    # 1) 评论写穿层（新链路）
    from app.xhs.models.xhs_note_comment import XhsNoteComment
    rows = (
        db.query(XhsNoteComment.note_id)
        .filter(XhsNoteComment.note_id.in_(note_ids))
        .distinct()
        .all()
    )
    have.update(r[0] for r in rows)
    # 2) 任务 comments_json（旧链路）
    extra = db.get(XhsTaskExtra, task_id)
    if extra and extra.comments_json:
        try:
            comments = json.loads(extra.comments_json) or []
            have.update(c.get("note_id") for c in comments if c.get("note_id"))
        except (TypeError, ValueError):
            pass
    return have


def _run_missing_comments_backfill(task_id: int) -> None:
    """后台线程：对任务里没有评论的笔记逐篇补抓评论（流式落库 + 合并 comments_json）。"""
    from app.xhs.services.client.xhs_crawler_client import COMMENT_PAGE_INTERVAL_SECONDS
    from app.xhs.services.comment_store import save_comment_batch
    from app.xhs.services.spider import Data_Spider
    from app.xhs.services.xhs_errors import XhsAuthError, XhsRateLimitError

    db = SessionLocal()
    try:
        task = db.get(Task, task_id)
        extra = db.get(XhsTaskExtra, task_id)
        if not task or not extra:
            return
        cookies_str = token_store.get_cookies_str(db)
        if not cookies_str:
            logger.warning(f"任务 {task_id} 补抓评论跳过：未配置 token/cookie")
            return

        notes = json.loads(extra.result_json) if extra.result_json else []
        note_ids = [n.get("note_id") for n in notes if n.get("note_id")]
        already = _notes_with_existing_comments(db, note_ids, task_id)
        missing = [n for n in notes if n.get("note_id") not in already]
        logger.info(f"任务 {task_id} 补抓评论：共 {len(note_ids)} 篇，已有评论 {len(already)} 篇，待补 {len(missing)} 篇")

        if not missing:
            extra.phase = "comments_backfill_done"
            db.commit()
            return

        extra.phase = "fetching_missing_comments"
        extra.progress_current = 0
        extra.progress_total = len(missing)
        db.commit()

        spider = Data_Spider()
        new_comments: list[dict] = []
        seen_ids = {c.get("comment_id") for c in (json.loads(extra.comments_json) if extra.comments_json else []) if c.get("comment_id")}
        rate_hits = 0
        for i, note_info in enumerate(missing):
            try:
                def _on_batch(note_id: str, batch: list) -> None:
                    try:
                        save_comment_batch(db, batch)
                    except Exception as e:
                        logger.warning(f"补抓评论落库失败（note={note_id}）: {e}")
                    fresh = [c for c in batch if c.get("comment_id") not in seen_ids]
                    new_comments.extend(fresh)
                    seen_ids.update(c.get("comment_id") for c in fresh)

                _, _, comment_list = spider.spider_note_comments(
                    note_info, cookies_str,
                    interval_seconds=COMMENT_PAGE_INTERVAL_SECONDS,
                    on_batch=_on_batch,
                )
                rate_hits = 0
            except XhsAuthError as e:
                logger.error(f"任务 {task_id} 补抓评论因登录态失效终止: {e}")
                break
            except XhsRateLimitError as e:
                rate_hits += 1
                if rate_hits >= 3:
                    logger.error(f"任务 {task_id} 补抓评论连续触发风控，停止: {e}")
                    break
                logger.warning(f"补抓评论触发风控（{e}），冷却 90s")
                time.sleep(90)
            except Exception as e:
                logger.warning(f"任务 {task_id} 笔记 {note_info.get('note_id')} 补抓评论失败，跳过: {e}")
            extra.progress_current = i + 1
            db.commit()
            time.sleep(0.8 + random.uniform(0, 0.6))

        # 合并进 comments_json（按 comment_id 去重），保持 Excel/预览一致
        if new_comments:
            existing = json.loads(extra.comments_json) if extra.comments_json else []
            existing_ids = {c.get("comment_id") for c in existing if c.get("comment_id")}
            merged = existing + [c for c in new_comments if c.get("comment_id") not in existing_ids]
            extra.comments_json = json.dumps(merged, ensure_ascii=False)
        extra.phase = "comments_backfill_done"
        extra.progress_current = len(missing)
        db.commit()
        logger.info(f"任务 {task_id} 补抓评论完成：新增 {len(new_comments)} 条，涉及 {len(missing)} 篇笔记")
    except Exception as e:
        logger.exception(f"任务 {task_id} 补抓评论异常")
        try:
            extra = db.get(XhsTaskExtra, task_id)
            if extra:
                extra.phase = "comments_backfill_failed"
                db.commit()
        except Exception:
            pass
    finally:
        with _missing_comments_lock:
            _missing_comments_running.discard(task_id)
        db.close()


def start_missing_comments_backfill(db: Session, task_id: int) -> tuple[bool, str, dict]:
    """
    "更新评论"入口：校验 + 统计待补数量 + 起后台线程补抓，立刻返回。
    返回 (ok, msg, stats)，stats 含 total / already_have / to_fetch。
    """
    task = db.get(Task, task_id)
    if not task or task.module != "xhs":
        return False, "任务不存在", {}
    if task.status == "running":
        return False, "任务正在采集中，请等待完成后再操作", {}
    with _missing_comments_lock:
        if task_id in _missing_comments_running:
            return False, "该任务正在补抓评论中，请稍候", {}
        _missing_comments_running.add(task_id)

    extra = db.get(XhsTaskExtra, task_id)
    notes = json.loads(extra.result_json) if extra and extra.result_json else []
    note_ids = [n.get("note_id") for n in notes if n.get("note_id")]
    already = _notes_with_existing_comments(db, note_ids, task_id)
    to_fetch = len(note_ids) - len(already)
    stats = {"total": len(note_ids), "already_have": len(already), "to_fetch": to_fetch}

    threading.Thread(target=_run_missing_comments_backfill, args=(task_id,), daemon=True).start()
    return True, "已开始为没有评论的笔记补抓评论", stats


def _list_files(task_id: int) -> dict:
    d = task_dir(task_id)
    excel_dir = d / "excel"
    media_dir = d / "media"
    excel_files = sorted(p.name for p in excel_dir.glob("*.xlsx")) if excel_dir.exists() else []
    media_file_count = sum(1 for p in media_dir.rglob("*") if p.is_file()) if media_dir.exists() else 0
    return {"excel_files": excel_files, "media_file_count": media_file_count}


def _serialize(task: Task, extra: Optional[XhsTaskExtra], stats: Optional[XhsCollectStats] = None) -> dict:
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
        "collect_stats": {
            "candidate_count": stats.candidate_count,
            "fetch_failed_count": stats.fetch_failed_count,
            "low_content_count": stats.low_content_count,
            "collected_count": stats.collected_count,
            "structured_ok_count": stats.structured_ok_count,
            "structured_failed_count": stats.structured_failed_count,
        }
        if stats
        else None,
    }


def get_task(db: Session, task_id: int) -> Optional[dict]:
    task = db.get(Task, task_id)
    if not task or task.module != "xhs":
        return None
    extra = db.get(XhsTaskExtra, task_id)
    stats = db.get(XhsCollectStats, task_id)
    return _serialize(task, extra, stats)


def list_tasks(db: Session) -> list:
    tasks = db.query(Task).filter(Task.module == "xhs").order_by(Task.created_at.desc()).all()
    results = []
    for task in tasks:
        extra = db.get(XhsTaskExtra, task.id)
        stats = db.get(XhsCollectStats, task.id)
        results.append(_serialize(task, extra, stats))
    return results


def list_note_tasks_page(
    db: Session,
    query: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    笔记管理首页：只列出有笔记数据的采集任务（note_count > 0），支持关键词/状态过滤和分页。
    排序按 created_at desc——Task 表目前没有 updated_at 字段，这里用创建时间顶替"最近更新"，
    前端需要在文案上标注这一点，不能假装它是真的更新时间。
    """
    items = [t for t in list_tasks(db) if t["note_count"] > 0]
    if query:
        q = query.strip().lower()
        items = [t for t in items if q in t["keyword"].lower()]
    if status:
        items = [t for t in items if t["status"] == status]
    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _parse_upload_time(value: str) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


_DATE_RANGE_DAYS = {"7d": 7, "30d": 30, "180d": 180}


def get_task_notes_page(
    db: Session,
    task_id: int,
    query: Optional[str] = None,
    note_type: Optional[str] = None,
    date_range: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> Optional[dict]:
    """
    任务详情二级视图：笔记列表按发布时间倒序，支持标题/正文/作者搜索、内容类型和时间范围过滤、分页。
    note_type 是笔记详情里真实存的中文值（"图集"/"视频"，见 data_util.py::download_note），
    不是采集任务表单里那个 0/1/2 的枚举——两者语义不同，不能混用。
    """
    preview = get_preview(db, task_id)
    if preview is None:
        return None

    notes = list(preview["notes"])
    if query:
        q = query.strip().lower()
        notes = [
            n
            for n in notes
            if q in (n.get("title") or "").lower()
            or q in (n.get("desc") or "").lower()
            or q in (n.get("nickname") or "").lower()
        ]
    if note_type:
        notes = [n for n in notes if n.get("note_type") == note_type]
    if date_range and date_range in _DATE_RANGE_DAYS:
        cutoff = datetime.now() - timedelta(days=_DATE_RANGE_DAYS[date_range])
        notes = [n for n in notes if (_parse_upload_time(n.get("upload_time")) or datetime.min) >= cutoff]

    def _sort_key(n: dict):
        parsed = _parse_upload_time(n.get("upload_time"))
        return parsed or datetime.min

    notes.sort(key=_sort_key, reverse=True)

    total = len(notes)
    start = (page - 1) * page_size
    return {
        "items": notes[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


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

    # 评论写穿层联动：同步删除这些笔记在 xhs_note_comments 表里的评论行
    try:
        from app.xhs.services.comment_store import delete_comments_for_notes
        delete_comments_for_notes(db, list(note_id_set))
    except Exception as e:
        logger.warning(f"删除笔记时清理评论表失败（任务 {task_id}）: {e}")

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


def _fetch_notes_from_candidates(
    db: Session,
    extra: XhsTaskExtra,
    task_id: int,
    data_spider,
    cookies_str: str,
    raw_notes: list[dict],
    exclude_ids: set[str],
    limit: Optional[int] = None,
) -> tuple[list[dict], int, int]:
    """
    从候选笔记（search_some_note 返回、已过滤 model_type == "note"）逐条抓详情、
    过滤低质内容，返回 (新笔记列表, 抓取失败数, 低质过滤数)。

    exclude_ids 是"已经算在内、不用再要一遍"的 note_id 集合——全新采集传空集合；
    增量采集传"这个主题已经采集过的 note_id"，命中的候选直接跳过，不占用配额。
    这个集合在函数内部会被就地更新（加入新采集到的 note_id），调用方如果需要多轮
    搜索去重，直接复用同一个 set 对象即可。

    limit 给了的话，攒够这么多篇新笔记就提前结束，不用把候选列表全部跑完
    （增量采集只需要"够用"的新笔记，不需要额外浪费详情请求）。
    """
    new_notes: list[dict] = []
    fetch_failed_count = 0
    low_content_count = 0
    total = len(raw_notes)
    _set_progress(db, extra, "fetching_notes", 0, total)

    # 抓详情：并发 2 + 主线程按序收集（每篇之间随机间隔）。并发 2 是防封控与速度的
    # 中间档——并发 >2 实测会提高风控触发概率，1 又偏慢。
    # 每个 worker 用独立的 SessionLocal（SQLAlchemy session 非线程安全）。
    import concurrent.futures
    from app.core.database import SessionLocal as _SessionLocal

    candidates: list[tuple[int, str, str]] = []  # (idx, note_id, note_url)
    for i, n in enumerate(raw_notes):
        note_id = n["id"]
        if note_id not in exclude_ids:
            note_url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={n['xsec_token']}"
            candidates.append((i, note_id, note_url))

    def _fetch_one(args: tuple[int, str, str]) -> tuple[int, bool, str, Optional[dict]]:
        idx, note_id, note_url = args
        session = _SessionLocal()
        try:
            # 全局缓存命中且未过期就直接复用，不重复调用 spider_note()（TODO.md
            # "小红书笔记数据全局去重缓存"）；未命中抓取，主线程按序收集
            ok, note_msg, note_info = note_cache.get_or_fetch_note(
                session, note_url, note_id, cookies_str, data_spider
            )
            return idx, ok, note_msg, note_info
        finally:
            session.close()

    results: dict[int, tuple[bool, str, Optional[dict]]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(_fetch_one, c): c[0]
            for c in candidates
        }
        for future in concurrent.futures.as_completed(futures):
            idx, ok, note_msg, note_info = future.result()
            # 收集节奏限速（带随机抖动），控制整体请求密度
            time.sleep(0.3 + random.uniform(0, 0.4))
            results[idx] = (ok, note_msg, note_info)

    for i, n in enumerate(raw_notes):
        note_id = n["id"]
        if note_id in exclude_ids:
            continue
        ok, note_msg, note_info = results.get(i, (False, "未进入并发队列", None))
        try:
            if ok and note_info:
                # 求攻略/求推荐类没有实质内容的笔记，采集阶段直接过滤掉，不进
                # 结果列表——不消耗后面的媒体下载、结构化提炼、AI 分析 token
                # （《小红书笔记结构化预处理-技术方案.md》，用户明确要求"不用采集了"）
                if note_preprocess.is_low_content(note_info.get("title", ""), note_info.get("desc", "")):
                    note_structurer.mark_skipped_low_content(db, note_info)
                    low_content_count += 1
                else:
                    new_notes.append(note_info)
                    exclude_ids.add(note_id)
            else:
                fetch_failed_count += 1
        except Exception as e:
            fetch_failed_count += 1
            logger.warning(f"任务 {task_id} 笔记详情抓取失败，跳过: {e}")
        _set_progress(db, extra, "fetching_notes", i + 1, total)
        if limit is not None and len(new_notes) >= limit:
            break
    return new_notes, fetch_failed_count, low_content_count


def _structure_and_record_stats(
    db: Session, task_id: int, new_notes: list[dict], extra: XhsTaskExtra,
    candidate_count: int, fetch_failed_count: int, low_content_count: int,
) -> None:
    """
    结构化预处理（只处理这一轮新增的笔记）+ 落一份 XhsCollectStats。全新采集和增量
    采集共用这一段——两边关心的都是"这一轮"的数字，不是历史累计。
    """
    _set_progress(db, extra, "structuring", 0, len(new_notes))
    structure_counts = {"ok": 0, "failed": 0, "skipped": 0}
    try:
        # 并发结构化可能持续一两分钟（每篇要调一次智谱 GLM），不传 progress_callback 的话
        # 进度会一直停在 0%，任务中心看起来像"数据处理卡住不动"——逐篇回调实时刷新进度。
        structure_counts = note_structurer.structure_notes_concurrently(
            db,
            new_notes,
            progress_callback=lambda index, total, _counts: _set_progress(
                db, extra, "structuring", index, total
            ),
        )
    except Exception as e:
        logger.warning(f"任务 {task_id} 笔记结构化预处理失败，不影响采集结果: {e}")
    _set_progress(db, extra, "structuring", len(new_notes), len(new_notes))

    stats = db.get(XhsCollectStats, task_id)
    if stats is None:
        stats = XhsCollectStats(task_id=task_id)
        db.add(stats)
    stats.candidate_count = candidate_count
    stats.fetch_failed_count = fetch_failed_count
    stats.low_content_count = low_content_count
    stats.collected_count = len(new_notes)
    stats.structured_ok_count = structure_counts.get("ok", 0)
    stats.structured_failed_count = structure_counts.get("failed", 0)
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
            _clear_pending_op(db, task_id)
            return

        # 登录态心跳探测：cookie 失效时任务直接失败，提示重新登录，而不是跑到一半才发现
        valid, valid_msg = token_store.validate(db)
        if not valid:
            task.status = "failed"
            task.result_summary = valid_msg
            task.finished_at = datetime.now(timezone.utc)
            extra.phase = "failed"
            db.commit()
            _clear_pending_op(db, task_id)
            return

        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        db.commit()

        # 从这里开始直到抓取结束，任何异常都要落到下面的 except 里把任务标记成 failed——
        # 之前 params 解析/_set_progress 这几行是在 try 外面的，一旦它们本身抛出异常
        # （比如 params 里没有 keyword），_run_task 就没有兜底，任务会永远卡在 "running"，
        # 下次进程重启还会被 requeue_pending_tasks() 反复捞出来再卡一次。
        try:
            params = task.params or {}
            _set_progress(db, extra, "searching", 0, 0)

            save_choice = params.get("save_choice", "excel")
            fetch_comments = params.get("fetch_comments", False)
            comment_interval = params.get("comment_interval_seconds")
            max_comments = params.get("max_comments_per_note")
            keyword = params["keyword"]

            t_dir = task_dir(task_id)
            media_dir = t_dir / "media"
            excel_dir = t_dir / "excel"

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

            parsed_notes, fetch_failed_count, low_content_count = _fetch_notes_from_candidates(
                db, extra, task_id, data_spider, cookies_str, raw_notes, exclude_ids=set()
            )

            # 笔记结构化预处理：并发调用智谱 GLM 把标题+正文提炼成 summary/key_points，
            # AI 分析时用这份精简结果代替原始全文，单篇 token 能降 80% 左右。跑在媒体
            # 下载/导出之前，互不依赖，失败也不影响采集任务本身。
            _structure_and_record_stats(
                db, task_id, parsed_notes, extra, total_notes, fetch_failed_count, low_content_count
            )

            if save_choice == "all" or "media" in save_choice:
                media_dir.mkdir(parents=True, exist_ok=True)
                _set_progress(db, extra, "downloading_media", 0, len(parsed_notes))
                # 视频下载开关：任务参数 download_video=False（默认）时视频只保留地址不下载文件
                download_video = bool(params.get("download_video", False))
                for i, note_info in enumerate(parsed_notes):
                    try:
                        download_note(note_info, str(media_dir), save_choice, download_video=download_video)
                    except Exception as e:
                        logger.error(f"笔记 {note_info.get('note_id')} 素材下载失败，跳过: {e}")
                    _set_progress(db, extra, "downloading_media", i + 1, len(parsed_notes))

            all_comments = []
            if fetch_comments:
                _set_progress(db, extra, "fetching_comments", 0, len(parsed_notes))
                # 风控熔断（保护账号/cookie 不被风控打上标记）：
                # 连续 2 次风控信号 → 冷却 90s 再继续；连续 3 次 → 任务失败，让用户
                # 歇一会儿再试，而不是继续请求把账号/登录态彻底搞坏。
                rate_hits = 0
                for i, note_info in enumerate(parsed_notes):
                    try:
                        # 评论边爬边批量落库（写穿层），崩溃续采不丢已爬评论；
                        # all_comments 继续累积，保证 comments_json / Excel 行为不变
                        def _on_comment_batch(note_id: str, batch: list) -> None:
                            from app.xhs.services.comment_store import save_comment_batch
                            try:
                                save_comment_batch(db, batch)
                            except Exception as e:
                                logger.warning(f"评论落库失败（note={note_id}）: {e}")

                        _, _, comment_list = data_spider.spider_note_comments(
                            note_info, cookies_str, interval_seconds=comment_interval,
                            max_comments=max_comments, on_batch=_on_comment_batch,
                        )
                        all_comments.extend(comment_list)
                        rate_hits = 0  # 成功一篇就清零风控计数
                    except XhsNotFoundError as e:
                        logger.warning(f"笔记 {note_info.get('note_id')} 评论不存在，跳过: {e}")
                    except XhsRateLimitError as e:
                        rate_hits += 1
                        if rate_hits >= 3:
                            raise
                        logger.warning(
                            f"笔记 {note_info.get('note_id')} 触发风控（{e}），"
                            f"连续第 {rate_hits} 次，冷却 90s 后继续"
                        )
                        time.sleep(90)
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
            _clear_pending_op(db, task_id)
        except XhsAuthError as e:
            # 登录态失效是"确定性的"失败：重试没有意义，给出明确提示让用户重新登录
            logger.error(f"任务 {task_id} 因登录态失效终止: {e}")
            task.status = "failed"
            task.result_summary = f"登录态失效，请重新登录后再试（{e}）"
            task.finished_at = datetime.now(timezone.utc)
            extra.phase = "failed"
            db.commit()
            _clear_pending_op(db, task_id)
        except XhsRateLimitError as e:
            # 风控熔断触发：任务失败保护账号/cookie，提示用户稍后再试
            logger.error(f"任务 {task_id} 因连续触发风控终止: {e}")
            task.status = "failed"
            task.result_summary = "触发平台风控（连续多次），已自动停止以保护账号。建议等待一段时间（如 1-2 小时）后再试"
            task.finished_at = datetime.now(timezone.utc)
            extra.phase = "failed"
            db.commit()
            _clear_pending_op(db, task_id)
        except Exception as e:
            logger.exception(f"任务 {task_id} 执行失败")
            task.status = "failed"
            task.result_summary = str(e)
            task.finished_at = datetime.now(timezone.utc)
            extra.phase = "failed"
            db.commit()
            _clear_pending_op(db, task_id)
    finally:
        db.close()


def _run_incremental_task(task_id: int, increment_count: int) -> None:
    """
    在已有主题基础上追加采集 increment_count 篇"新"笔记（跳过已经采集过的），只对
    新笔记跑媒体下载/结构化预处理/评论抓取，最后把新旧笔记合并写回。

    小红书搜索接口没有"翻页续搜"的游标，每次调用都是从第一名重新搜（见
    XHS_Apis.search_some_note 实现），没法直接要"第 51-100 名"。这里的策略是
    "多要一些、本地按 note_id 去重"：第一轮按 已有数量+目标增量+缓冲 去请求，
    不够再按 已有数量+目标增量*3（封顶 1000，接口上限）加大请求一次；两轮都不够
    就返回实际采到的数量，不无限重试（该关键词下可能确实没有更多新内容了）。
    """
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
            _clear_pending_op(db, task_id)
            return

        # 登录态心跳探测：cookie 失效时任务直接失败，提示重新登录，而不是跑到一半才发现
        valid, valid_msg = token_store.validate(db)
        if not valid:
            task.status = "failed"
            task.result_summary = valid_msg
            task.finished_at = datetime.now(timezone.utc)
            extra.phase = "failed"
            db.commit()
            _clear_pending_op(db, task_id)
            return

        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        db.commit()

        try:
            params = task.params or {}
            keyword = params["keyword"]
            save_choice = params.get("save_choice", "excel")
            fetch_comments = params.get("fetch_comments", False)
            comment_interval = params.get("comment_interval_seconds")
            max_comments = params.get("max_comments_per_note")

            t_dir = task_dir(task_id)
            media_dir = t_dir / "media"
            excel_dir = t_dir / "excel"

            existing_notes = json.loads(extra.result_json) if extra.result_json else []
            existing_ids = {n.get("note_id") for n in existing_notes if n.get("note_id")}

            data_spider = Data_Spider()
            _set_progress(db, extra, "searching", 0, 0)

            new_notes: list[dict] = []
            fetch_failed_count = 0
            low_content_count = 0
            candidate_count = 0
            seen_ids = set(existing_ids)  # 就地累加，两轮搜索之间也不会把同一篇候选算两次

            attempt_targets = [
                len(existing_notes) + increment_count + max(10, increment_count // 2),
                len(existing_notes) + increment_count * 3,
            ]
            for attempt, require_num in enumerate(attempt_targets, start=1):
                # 增量采集固定按"最新发布"排序（sort_type_choice=1, time_descending）：
                # 增量的语义就是补齐新发布的笔记，只有按最新排序才能把候选池里的新增内容
                # 排到前面；沿用任务原排序（可能是综合/点赞）会漏掉新笔记甚至反复拿到旧的。
                success, msg, raw_notes = data_spider.xhs_apis.search_some_note(
                    keyword,
                    min(require_num, 1000),
                    cookies_str,
                    1,
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
                candidate_count = len(raw_notes)

                still_needed = increment_count - len(new_notes)
                batch_notes, batch_failed, batch_low_content = _fetch_notes_from_candidates(
                    db, extra, task_id, data_spider, cookies_str, raw_notes, exclude_ids=seen_ids,
                    limit=still_needed,
                )
                new_notes.extend(batch_notes)
                fetch_failed_count += batch_failed
                low_content_count += batch_low_content

                if len(new_notes) >= increment_count:
                    break
                logger.info(
                    f"任务 {task_id} 增量采集第 {attempt} 轮只凑到 {len(new_notes)}/{increment_count} "
                    f"篇新笔记，{'尝试放大请求量再搜一轮' if attempt < len(attempt_targets) else '该关键词候选已接近用尽，不再重试'}"
                )

            _structure_and_record_stats(
                db, task_id, new_notes, extra, candidate_count, fetch_failed_count, low_content_count
            )

            if new_notes and (save_choice == "all" or "media" in save_choice):
                media_dir.mkdir(parents=True, exist_ok=True)
                _set_progress(db, extra, "downloading_media", 0, len(new_notes))
                # 视频下载开关（增量采集与全新采集一致）：默认不下载视频文件
                download_video = bool(params.get("download_video", False))
                for i, note_info in enumerate(new_notes):
                    try:
                        download_note(note_info, str(media_dir), save_choice, download_video=download_video)
                    except Exception as e:
                        logger.error(f"笔记 {note_info.get('note_id')} 素材下载失败，跳过: {e}")
                    _set_progress(db, extra, "downloading_media", i + 1, len(new_notes))

            all_comments = json.loads(extra.comments_json) if extra.comments_json else []
            if new_notes and fetch_comments:
                _set_progress(db, extra, "fetching_comments", 0, len(new_notes))
                # 风控熔断（与全新采集一致）：连续 2 次冷却 90s，连续 3 次任务失败保护账号
                rate_hits = 0
                for i, note_info in enumerate(new_notes):
                    try:
                        _, _, comment_list = data_spider.spider_note_comments(
                            note_info, cookies_str, interval_seconds=comment_interval, max_comments=max_comments,
                        )
                        all_comments.extend(comment_list)
                        rate_hits = 0
                    except XhsRateLimitError as e:
                        rate_hits += 1
                        if rate_hits >= 3:
                            raise
                        logger.warning(
                            f"笔记 {note_info.get('note_id')} 触发风控（{e}），"
                            f"连续第 {rate_hits} 次，冷却 90s 后继续"
                        )
                        time.sleep(90)
                    except Exception as e:
                        logger.error(f"笔记 {note_info.get('note_id')} 评论抓取失败，跳过: {e}")
                    _set_progress(db, extra, "fetching_comments", i + 1, len(new_notes))
                    time.sleep(comment_interval if comment_interval is not None else 1.0)

            merged_notes = existing_notes + new_notes
            if new_notes and (save_choice == "all" or save_choice == "excel"):
                _set_progress(db, extra, "exporting", 0, 0)
                excel_dir.mkdir(parents=True, exist_ok=True)
                save_to_xlsx(merged_notes, str(excel_dir / f"{keyword}.xlsx"))
                if fetch_comments and all_comments:
                    save_to_xlsx(all_comments, str(excel_dir / f"{keyword}_comments.xlsx"), "comment")

            extra.result_json = json.dumps(merged_notes, ensure_ascii=False)
            extra.comments_json = json.dumps(all_comments, ensure_ascii=False) if all_comments else extra.comments_json
            extra.note_count = len(merged_notes)
            extra.phase = "done"
            extra.progress_current = len(merged_notes)
            extra.progress_total = len(merged_notes)
            task.status = "success"
            task.result_summary = (
                f"增量采集完成，新增 {len(new_notes)}/{increment_count} 篇，共 {len(merged_notes)} 篇笔记"
                if len(new_notes) < increment_count
                else f"增量采集完成，新增 {len(new_notes)} 篇，共 {len(merged_notes)} 篇笔记"
            )
            task.finished_at = datetime.now(timezone.utc)
            db.commit()
            _clear_pending_op(db, task_id)
        except XhsAuthError as e:
            logger.error(f"任务 {task_id} 因登录态失效终止: {e}")
            task.status = "failed"
            task.result_summary = f"登录态失效，请重新登录后再试（{e}）"
            task.finished_at = datetime.now(timezone.utc)
            extra.phase = "failed"
            db.commit()
            _clear_pending_op(db, task_id)
        except XhsRateLimitError as e:
            # 风控熔断触发：任务失败保护账号/cookie，提示用户稍后再试
            logger.error(f"任务 {task_id} 因连续触发风控终止: {e}")
            task.status = "failed"
            task.result_summary = "触发平台风控（连续多次），已自动停止以保护账号。建议等待一段时间（如 1-2 小时）后再试"
            task.finished_at = datetime.now(timezone.utc)
            extra.phase = "failed"
            db.commit()
            _clear_pending_op(db, task_id)
        except Exception as e:
            logger.exception(f"任务 {task_id} 增量采集失败")
            task.status = "failed"
            task.result_summary = str(e)
            task.finished_at = datetime.now(timezone.utc)
            extra.phase = "failed"
            db.commit()
            _clear_pending_op(db, task_id)
    finally:
        db.close()


def _worker_loop() -> None:
    while True:
        kind, item_id, payload = _queue.get()
        try:
            if kind == "collect":
                _run_task(item_id)
            elif kind == "incremental":
                _run_incremental_task(item_id, payload["increment_count"])
            elif kind == "tracking":
                # 函数内 import：tracking.py 会 import 本模块的 enqueue_tracking_scan，
                # 模块顶层互相 import 会循环引用
                from app.xhs.services import tracking

                tracking.run_scan(item_id)
        except Exception:
            logger.exception(f"{kind} 任务 {item_id} worker 异常")
        finally:
            _queue.task_done()
