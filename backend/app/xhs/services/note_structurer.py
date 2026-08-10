"""
笔记结构化提炼：调用智谱 GLM-4-Flash 结构化输出把一篇笔记的标题+正文压成
category/summary/key_points/ext 这样的精简结构（《小红书笔记结构化预处理-技术方案.md》
3.3/3.4/3.5 节）。content_hash 幂等——原文没变就跳过，不重复调用 LLM。

这一步原本调的是 Gemini，改成智谱 GLM-4-Flash：这个抽取任务不需要很强的推理能力，
GLM-4-Flash 官方长期免费、中文/社交媒体文本理解也更贴合小红书内容，且和聊天/xhs
AI 分析用的 Gemini 是完全独立的另一份配置（zhipu_api_key），互不影响、互不共享配额。

并发用 ThreadPoolExecutor 而不是方案文档示例代码里的 asyncio：这个项目的采集流程
（tasks.py::_run_task）本身是同步代码、跑在独立 worker 线程里，媒体下载并发也是用
ThreadPoolExecutor（utils/data_util.py::_MEDIA_DOWNLOAD_WORKERS），跟着这个既有
惯例走，不在一个全同步的代码库里额外引入 asyncio 事件循环。
"""
from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from loguru import logger
from sqlalchemy.orm import Session

from app.common.services.ai_gateway.glm_structured import GlmStructuredError, generate_structured
from app.common.services.zhipu_config import get_zhipu_config
from app.core.database import SessionLocal
from app.xhs.models import XhsNoteStructured
from app.xhs.services import note_preprocess

# 之前这里是 import logging + logging.getLogger(__name__)——stdlib logging 和项目
# 实际用的 loguru 是两套独立系统，app/core/logging.py 的 setup_logging() 只配置了
# loguru 的 sink（stderr + logs/app.log），没有桥接 stdlib logging，所以这里原来的
# warning 日志实际上不会落进 logs/app.log。统一换成 loguru，和 tasks.py/tracking.py
# 保持一致，日志才能真正落盘、在系统设置的日志页面里看到。

_WORKERS = 8  # 方案文档建议并发数从 5-8 起步，观察是否触发限流再调整

# GLM 的 json_object 模式只保证输出是合法 JSON，不像 Gemini 的 responseSchema 能强制
# 字段结构——所以把字段形状明确写进 prompt 里，输出后仍然要走下面的 _validate() 校验。
_SYSTEM_PROMPT = """你是笔记信息提取器。将小红书笔记提炼为结构化 JSON。

只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释，字段如下：
{
  "category": "place|food|shopping|stay|guide|other 六选一",
  "city": "城市，不确定留空字符串",
  "area": "城区/地段，不确定留空字符串",
  "summary": "一句话概括，不超过30字",
  "key_points": ["3-5条最具决策价值的信息，比如价格/排队/预约/营业时间/避坑提醒，每条不超过20字"],
  "tags": ["笔记相关的简短标签"],
  "ext": {}
}

规则：
1. 只提取笔记中明确写到的信息，不推测、不补充常识
2. 无法确定的字段留空字符串或空数组，不要编造
3. category 无法明确归类时选 other，不要强行归类
4. 必须是合法 JSON，不要输出 JSON 之外的任何文字"""


def content_hash(title: str, desc: str) -> str:
    return hashlib.md5(f"{title}|{desc}".encode("utf-8")).hexdigest()[:16]


def _row_to_dict(row: XhsNoteStructured) -> dict[str, Any]:
    return {
        "note_id": row.note_id,
        "category": row.category,
        "city": row.city,
        "area": row.area,
        "summary": row.summary,
        "key_points": json.loads(row.key_points_json or "[]"),
        "topic_tags": json.loads(row.topic_tags_json or "[]"),
        "ext": json.loads(row.ext_json or "{}"),
        "status": row.status,
        "issues": json.loads(row.issues_json or "[]"),
    }


def get_structured_map(db: Session, note_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not note_ids:
        return {}
    rows = db.query(XhsNoteStructured).filter(XhsNoteStructured.note_id.in_(note_ids)).all()
    return {row.note_id: _row_to_dict(row) for row in rows}


def notes_needing_processing(db: Session, notes: list[dict]) -> list[dict]:
    """筛出缺失、失败或正文已变化的笔记，供存量补处理入口预估工作量。"""
    result = []
    for note in notes:
        note_id = note.get("note_id")
        if not note_id:
            continue
        chash = content_hash(note.get("title") or "", note.get("desc") or "")
        if _needs_processing(db, note_id, chash):
            result.append(note)
    return result


def _validate(item: dict) -> list[str]:
    """方案 3.5 节的校验规则：不算硬错误，只是标记出来供后续抽查，不阻塞主流程。"""
    issues = []
    if not item.get("summary"):
        issues.append("empty_summary")
    if len(item.get("key_points") or []) < 2:
        issues.append("too_few_key_points")
    if item.get("category") == "other":
        issues.append("uncategorized")
    return issues


def _needs_processing(db: Session, note_id: str, chash: str) -> bool:
    row = db.get(XhsNoteStructured, note_id)
    if not row:
        return True
    if row.status != "ok":
        return True
    return row.content_hash != chash


def _get_or_create_row(db: Session, note_id: str) -> XhsNoteStructured:
    row = db.get(XhsNoteStructured, note_id)
    if row is None:
        row = XhsNoteStructured(note_id=note_id)
        db.add(row)
    return row


def _structure_one(note: dict, api_key: str, model: str) -> str:
    """
    独立开一个 db session——跑在线程池的 worker 线程里，不能和主线程共享 session。
    返回 "ok" | "failed" | "skipped"（幂等命中，没有实际调用 LLM），供调用方汇总统计。
    """
    note_id = note.get("note_id")
    title = note.get("title") or ""
    desc = note.get("desc") or ""
    chash = content_hash(title, desc)

    db = SessionLocal()
    try:
        if not _needs_processing(db, note_id, chash):
            logger.debug(f"笔记 {note_id} 内容未变化且已成功处理过，跳过结构化（幂等命中）")
            return "skipped"  # 内容没变且上次成功过，跳过（幂等，避免重复付费调用 LLM）

        cleaned_desc, extracted_tags = note_preprocess.clean(desc)
        user_content = f"标题：{title}\n正文：{cleaned_desc}\n话题标签：{extracted_tags}"

        started = time.monotonic()
        try:
            data = generate_structured(_SYSTEM_PROMPT, user_content, api_key, model)
        except GlmStructuredError as e:
            elapsed = time.monotonic() - started
            logger.warning(f"笔记 {note_id} 结构化提炼失败（耗时 {elapsed:.1f}s，模型 {model}）：{e}")
            row = _get_or_create_row(db, note_id)
            row.content_hash = chash
            row.status = "failed"
            row.raw_ref = note.get("note_url")
            row.issues_json = json.dumps([str(e)], ensure_ascii=False)
            db.commit()
            return "failed"
        elapsed = time.monotonic() - started

        issues = _validate(data)
        row = _get_or_create_row(db, note_id)
        row.content_hash = chash
        row.category = data.get("category")
        row.city = data.get("city") or None
        row.area = data.get("area") or None
        row.summary = data.get("summary")
        row.key_points_json = json.dumps(data.get("key_points") or [], ensure_ascii=False)
        row.topic_tags_json = json.dumps(data.get("tags") or [], ensure_ascii=False)
        row.ext_json = json.dumps(data.get("ext") or {}, ensure_ascii=False)
        row.raw_ref = note.get("note_url")
        row.status = "ok"
        row.issues_json = json.dumps(issues, ensure_ascii=False)
        db.commit()
        logger.info(
            f"笔记 {note_id} 结构化成功（耗时 {elapsed:.1f}s）：category={data.get('category')}, "
            f"summary={data.get('summary')!r}" + (f"，校验提示：{issues}" if issues else "")
        )
        return "ok"
    finally:
        db.close()


def mark_skipped_low_content(db: Session, note: dict) -> None:
    """
    规则过滤掉的低质笔记也留一行 status='skipped_low_content'——不是不处理就完全没
    记录，而是明确记下"看过，判定为低质，没有调 LLM"，避免以后又对同一篇笔记重复
    跑一遍规则判断（虽然规则本身很便宜，但记一行更清楚，也方便后续抽查过滤准确率）。
    """
    note_id = note.get("note_id")
    if not note_id:
        return
    chash = content_hash(note.get("title") or "", note.get("desc") or "")
    row = _get_or_create_row(db, note_id)
    row.content_hash = chash
    row.status = "skipped_low_content"
    row.raw_ref = note.get("note_url")
    row.summary = None
    row.key_points_json = "[]"
    row.topic_tags_json = "[]"
    row.ext_json = "{}"
    row.issues_json = "[]"
    db.commit()


def structure_notes_concurrently(
    db: Session,
    notes: list[dict],
    progress_callback: Callable[[int, int, dict[str, int]], None] | None = None,
) -> dict[str, int]:
    """
    采集任务拿到（已经过 note_preprocess.is_low_content 过滤的）parsed_notes 后调用。
    db 参数只用来取一次智谱 GLM 配置，实际每篇笔记的写库操作在各自的线程里开独立 session。
    没配置 API Key 时直接跳过——结构化预处理是可选的性能优化，不应该因为没配置 Key
    就让整个采集任务失败。

    返回 {"ok": n, "failed": n, "skipped": n} 汇总计数，供采集任务落一份统计
    （XhsCollectStats）用于向用户展示"多少篇成功结构化/失败"。
    """
    counts = {"ok": 0, "failed": 0, "skipped": 0}
    if not notes:
        return counts
    api_key, model = get_zhipu_config(db)
    if not api_key:
        logger.warning("未配置智谱 GLM API Key（zhipu_api_key），跳过笔记结构化预处理")
        return counts

    workers = min(_WORKERS, len(notes))
    logger.info(f"开始笔记结构化预处理：共 {len(notes)} 篇，模型 {model}，并发 {workers}")
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for index, result in enumerate(executor.map(lambda n: _structure_one(n, api_key, model), notes), start=1):
            counts[result] = counts.get(result, 0) + 1
            if progress_callback:
                progress_callback(index, len(notes), counts.copy())
    elapsed = time.monotonic() - started
    logger.info(
        f"笔记结构化预处理完成，耗时 {elapsed:.1f}s：成功 {counts['ok']} 篇，"
        f"失败 {counts['failed']} 篇，跳过（幂等命中）{counts['skipped']} 篇"
    )
    return counts
