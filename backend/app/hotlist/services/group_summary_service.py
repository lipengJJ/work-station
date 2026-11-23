"""数据源分组 AI 总结：点一下，总结这个分组当前（未脱榜）条目里值得关注的内容。

参考 topic_report_service 的 simple 策略「标题+摘要直接拼文本」的数据组织方式，
但去掉了语义检索（分组是纯组织方式，不是语义主题，没有 interest_query 可用）和
funnel 策略的并发抓正文（延迟/复杂度跟"点一下很快出结果"的目标不匹配）——
分组本身就是最终粒度，不需要再筛/再分组，一次性把标题+摘要喂给 AI 就行。

非对话：固定指令，不支持追问（不需要就不做，见 HotGroupSummary 的说明）。
"""
from __future__ import annotations

import time
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.common.services.ai_config import get_ai_credentials
from app.common.services.ai_gateway.base import (
    EVENT_COMPLETED,
    EVENT_DELTA,
    EVENT_ERROR,
    AIRequest,
)
from app.common.services.ai_gateway.service import stream as ai_stream
from app.common.utils.text import strip_html, truncate
from app.hotlist.models import HotGroupSummary, HotItem, HotSource
from app.hotlist.services import source_service

SUMMARY_TRUNCATE = 300  # 每条摘要截断长度：这类源本来就是标题党型，摘要通常不长
MAX_ITEMS = 200  # 保护性上限，正常一个分组（清理后几十条）远用不到

SYSTEM_INSTRUCTION = """你是一个热点信息助手。下面是某个数据源分组当前（未脱榜）的热点条目列表，
已按热度从高到低排好序，每条前面的 "#数字" 是它的编号。请从中挑出 5~10 条真正值得关注的内容，
说明关注理由，帮用户从一堆标题里快速定位有价值的信息。

要求：
1. 用 Markdown 无序列表（"- " 开头）输出，一条结论一行。
2. 每条结论**最后**必须单独附上引用条目的编号，写成 "#数字"（比如 "#891"），且不能写进
   加粗文字或标题里面；编号必须是上面条目列表里出现过的，严禁编造不存在的编号。
3. 只基于给出的条目信息判断，不要编造没有的内容；信息不足就如实说明。
4. 不需要分节标题、不需要"数据来源"附录——这不是正式报告，越短越好。"""


class GroupSummaryError(Exception):
    """用户可见的错误（没有可总结条目 / 未配置 AI Key / AI 调用失败）。"""


def _format_items(items: list[HotItem], source_names: dict[str, str]) -> str:
    lines = []
    for item in items:
        summary = truncate(strip_html(item.summary or ""), SUMMARY_TRUNCATE)
        source_name = source_names.get(item.source_id, item.source_id)
        line = f"#{item.id} | {item.title} ｜来源: {source_name}"
        if summary:
            line += f"\n摘要: {summary}"
        lines.append(line)
    return "\n\n".join(lines)


def _stream_text(request: AIRequest, api_key: str) -> str:
    """消费 ai_gateway 的 SSE 事件，同步收集成完整文本。失败抛 GroupSummaryError。"""
    text_parts: list[str] = []
    error: Optional[str] = None
    completed = False
    for event in ai_stream(request, api_key):
        etype = event.get("type")
        if etype == EVENT_DELTA:
            text_parts.append(event.get("text") or "")
        elif etype == EVENT_ERROR:
            error = event.get("message") or "AI 调用失败"
        elif etype == EVENT_COMPLETED:
            completed = True
    if error or not completed:
        raise GroupSummaryError(error or "AI 调用未完成（无响应）")
    return "".join(text_parts).strip()


def _fetch_items(db: Session, group: str) -> tuple[list[HotItem], dict[str, str]]:
    """跟榜单页 GET /items?group= 用同一个 resolve_group_source_ids，保证范围一致。
    排除已脱榜（rank=0）的条目——那些是跌出榜单的旧话题，不是"现在"值得关注的。"""
    try:
        source_ids = source_service.resolve_group_source_ids(db, group)
    except ValueError as exc:
        raise GroupSummaryError(str(exc)) from exc

    query = db.query(HotItem).filter(HotItem.rank > 0)
    if source_ids is not None:
        if not source_ids:
            return [], {}
        query = query.filter(HotItem.source_id.in_(source_ids))
    items = (
        query.order_by(HotItem.weight.desc(), HotItem.id.desc())
        .limit(MAX_ITEMS)
        .all()
    )
    if not items:
        return [], {}

    used_source_ids = {it.source_id for it in items}
    source_names = {
        s.id: s.name
        for s in db.query(HotSource).filter(HotSource.id.in_(used_source_ids)).all()
    }
    return items, source_names


def generate_summary(db: Session, group: str) -> HotGroupSummary:
    """同步生成（非流式，点一下等几秒直接出结果）。失败也落一条 status=failed 的记录，
    方便在历史里看到"这次为什么没成"，而不是静默报错。"""
    items, source_names = _fetch_items(db, group)
    if not items:
        raise GroupSummaryError("该分组当前没有可总结的条目")

    provider, api_key, model, _ = get_ai_credentials(db)
    if not api_key:
        raise GroupSummaryError(
            "尚未配置 AI 模型 API Key，请先在系统设置 → API 配置里配置"
        )

    business_context = _format_items(items, source_names)
    request = AIRequest(
        provider=provider,
        model=model,
        system_instruction=SYSTEM_INSTRUCTION,
        messages=[{"role": "user", "content": business_context}],
        tools=[],
        thinking_enabled=False,
    )
    logger.info(f"分组总结开始：group={group!r}，{len(items)} 条条目，model={model}")
    started = time.monotonic()
    try:
        content = _stream_text(request, api_key)
    except GroupSummaryError as exc:
        summary = HotGroupSummary(
            group_filter=group,
            status="failed",
            error=str(exc),
            item_count=len(items),
            model=model,
        )
        db.add(summary)
        db.commit()
        db.refresh(summary)
        raise

    logger.info(
        f"分组总结完成：group={group!r}，耗时 {time.monotonic() - started:.1f}s，"
        f"输出 {len(content)} 字符"
    )
    summary = HotGroupSummary(
        group_filter=group,
        status="success",
        content=content,
        item_count=len(items),
        model=model,
    )
    db.add(summary)
    db.commit()
    db.refresh(summary)
    return summary


def get_latest_summary(db: Session, group: str) -> Optional[HotGroupSummary]:
    return (
        db.query(HotGroupSummary)
        .filter(HotGroupSummary.group_filter == group, HotGroupSummary.status == "success")
        .order_by(HotGroupSummary.created_at.desc(), HotGroupSummary.id.desc())
        .first()
    )
