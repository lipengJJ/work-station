"""
追踪任务 AI 智能筛选（阶段 3）：用任务自定义 Prompt 调「数据处理模型」（智谱 GLM）
判断笔记是否符合需求。复用 glm_structured.generate_structured 的 JSON 模式调用。

- Prompt 渲染：{{变量}} 替换；空值替换为「无」；note_content 超 2000 字符截断
- 响应解析：直接 JSON.parse → 剥离 ```json 围栏重试 → 失败标记 failed 保留原始输出
- is_match 缺失/类型不对按 false（保守，宁可不推送）
- token 消耗记入日志（由 GLM 调用方日志体现）
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.common.services.ai_gateway.glm_structured import GlmStructuredError, generate_structured
from app.common.services.zhipu_config import get_zhipu_config
from app.xhs.models import XhsTrackingHit

# 系统追加的输出格式（强制，用户不可编辑）——展示用 + 调用时追加
SYSTEM_APPEND = """请严格以 JSON 格式返回，不要包含任何其他内容：
{
  "is_match": true 或 false,
  "match_reason": "一句话说明判断理由，20 字以内",
  "confidence": 0 到 1 之间的小数
}"""

# 可插入变量清单（前端插入菜单 + 校验提示共用）
VARIABLES = [
    ("keyword", "任务的搜索关键词"),
    ("task_name", "任务名称"),
    ("note_title", "笔记标题"),
    ("note_content", "笔记正文"),
    ("note_structured", "AI 预处理提取的结构化字段（JSON）"),
    ("note_publish_time", "笔记发布时间"),
    ("note_author", "作者昵称"),
    ("note_likes", "点赞数"),
    ("note_collects", "收藏数"),
    ("note_comments", "评论数"),
    ("note_url", "笔记链接"),
]

_CONTENT_MAX = 2000


def render_prompt(prompt: str, ctx: dict[str, Any]) -> str:
    """{{变量}} 替换为实际值；空值替换为「无」。"""
    def _replace(m: re.Match) -> str:
        name = m.group(1)
        val = ctx.get(name)
        if val is None:
            return "无"
        s = str(val)
        if name == "note_content" and len(s) > _CONTENT_MAX:
            s = s[:_CONTENT_MAX] + "...(已截断)"
        return s

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", _replace, prompt)


def parse_ai_response(raw: str) -> Optional[dict]:
    """解析模型返回：直接 JSON.parse → 剥离 ```json 围栏 → None。"""
    text = (raw or "").strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        pass
    # 剥离代码围栏
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        try:
            data = json.loads(fenced.group(1).strip())
            return data if isinstance(data, dict) else None
        except (ValueError, TypeError):
            return None
    return None


def build_note_context(hit: XhsTrackingHit, structured: dict | None) -> dict:
    """从命中记录构造变量上下文。"""
    note = {}
    try:
        note = json.loads(hit.note_json or "{}")
    except (ValueError, TypeError):
        pass
    note_structured = structured or {}
    return {
        "keyword": note.get("keyword") or note.get("search_keyword") or "",
        "task_name": "",
        "note_title": note.get("title") or "",
        "note_content": note.get("desc") or "",
        "note_structured": json.dumps(note_structured, ensure_ascii=False),
        "note_publish_time": note.get("time") or note.get("publish_time") or "",
        "note_author": note.get("author") or note.get("nickname") or "",
        "note_likes": note.get("liked_count") or note.get("likes") or 0,
        "note_collects": note.get("collected_count") or note.get("collects") or 0,
        "note_comments": note.get("comment_count") or note.get("comments") or 0,
        "note_url": note.get("note_url") or f"https://www.xiaohongshu.com/explore/{hit.note_id}",
    }


def filter_one(
    db: Session, hit: XhsTrackingHit, prompt: str, api_key: str, model: str,
    task_name: str = "", keyword: str = "", structured: dict | None = None,
) -> dict:
    """对单条命中执行 AI 筛选，结果写回 hit 并 commit。"""
    ctx = build_note_context(hit, structured)
    ctx["task_name"] = task_name
    ctx["keyword"] = keyword or ctx["keyword"]
    user_prompt = render_prompt(prompt, ctx) + "\n\n" + SYSTEM_APPEND

    started = time.monotonic()
    try:
        data = generate_structured(
            "你是一个严谨的内容筛选助手。请严格按照要求判断并输出 JSON。",
            user_prompt, api_key, model, temperature=0.1,
        )
    except GlmStructuredError as e:
        elapsed = time.monotonic() - started
        logger.warning(f"AI 筛选调用失败（笔记 {hit.note_id}，耗时 {elapsed:.1f}s）：{e}")
        hit.ai_process_status = "failed"
        hit.ai_raw_response = f"[调用失败] {e}"
        db.commit()
        return {"note_id": hit.note_id, "ok": False, "error": str(e), "elapsed": elapsed}

    # generate_structured 已返回解析后的 dict（GLM JSON 模式 + json.loads 兜底）；
    # 若其内部解析失败会抛 GlmStructuredError（上面已捕获标记 failed）。
    parsed = data
    elapsed = time.monotonic() - started

    is_match = parsed.get("is_match")
    if not isinstance(is_match, bool):
        is_match = False  # 保守策略
    try:
        confidence = float(parsed.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0

    hit.ai_process_status = "success"
    hit.ai_is_match = is_match
    hit.ai_match_reason = str(parsed.get("match_reason") or "")[:200]
    hit.ai_confidence = confidence
    hit.ai_raw_response = json.dumps(parsed, ensure_ascii=False)
    db.commit()
    logger.info(
        f"AI 筛选（笔记 {hit.note_id}，耗时 {elapsed:.1f}s）：is_match={is_match} "
        f"confidence={confidence} reason={hit.ai_match_reason!r}"
    )
    return {
        "note_id": hit.note_id,
        "ok": True,
        "is_match": is_match,
        "confidence": confidence,
        "match_reason": hit.ai_match_reason,
        "elapsed": elapsed,
    }


def filter_hits(db: Session, task, hits: list[XhsTrackingHit], structured_map: dict) -> dict:
    """对一批命中执行 AI 筛选（顺序执行，单次任务调用量受搜索数量天然限制）。
    返回 {matched: [...], total: n, failed: n, partial_failed: bool}。"""
    api_key, model = get_zhipu_config(db)
    if not api_key:
        for h in hits:
            h.ai_process_status = "failed"
            h.ai_raw_response = "[未配置数据处理模型]"
        db.commit()
        return {"matched": [], "total": 0, "failed": len(hits), "partial_failed": False}

    matched = []
    failed = 0
    for hit in hits:
        res = filter_one(
            db, hit, task.ai_filter_prompt or "", api_key, model,
            task_name=task.name, keyword=task.keyword,
            structured=structured_map.get(hit.note_id),
        )
        if not res["ok"]:
            failed += 1
            continue
        if res["is_match"] and res["confidence"] >= (task.ai_filter_min_confidence or 0.6):
            matched.append(hit)
    total = len(hits)
    partial_failed = total > 0 and failed / total > 0.5
    return {"matched": matched, "total": total, "failed": failed, "partial_failed": partial_failed}
