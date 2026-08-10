"""
针对某个 AI 分析项目当前选中笔记的分析：语料现读 XhsTaskExtra.result_json（复用
analysis_project.list_project_notes），分析记录（问题+结论）落一条 XhsNoteAnalysis。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.xhs.models import XhsNoteAnalysis
from app.xhs.services import note_structurer

# 语料过大既拖慢响应也浪费 token：笔记数量不再硬编码截断（之前固定 200 篇，用户要求
# "选中多少分析多少"），改为按估算 token 做保护性上限——超过就明确报错让用户减少选中
# 数量，而不是悄悄截断一部分笔记导致分析结论不完整。每篇正文长度仍做截断（见
# _MAX_DESC_LENGTH）。
# 上限 150k token 约等于 60 万字符，能装下大几百篇结构化笔记；默认 gemini 上下文
# 1M，deepseek 64k——超限时报错信息里会说明，用户可减少数量或切换模型。
_MAX_CONTEXT_TOKENS = 150_000
_MAX_DESC_LENGTH = 500

# 笔记数量超过这个量时抛错提示（保护性上限，正常项目基本不会触发）
class NotesContextTooLarge(Exception):
    pass

_DEFAULT_TEMPLATE = "general"

# 分析模板：instruction 拼进第一轮 prompt 里，quick_prompts 给前端渲染成快捷追问按钮。
# 只是预置的指令片段，不是必须精确遵守的协议——Gemini 不完全照办也不影响基本功能。
TEMPLATES: dict[str, dict] = {
    "general": {
        "label": "通用分析",
        "instruction": "请从内容主题、互动数据、受众反馈等角度做通用性分析。",
        "quick_prompts": ["总结这些笔记的共同点", "哪几篇笔记数据表现最好，为什么", "有没有值得警惕的负面反馈"],
    },
    "travel": {
        "label": "旅行攻略（行程+住宿+美食+避坑）",
        "instruction": "请按行程安排、住宿推荐、美食清单、避坑提示这几个维度整理成一份可执行的旅行攻略。",
        "quick_prompts": ["推荐亲子餐厅", "下雨天备选方案", "预算人均 2000 元够吗？", "必买伴手礼清单"],
    },
    "ideas": {
        "label": "选题灵感",
        "instruction": "请从这些笔记里提炼可以借鉴的选题方向和标题风格，给出具体的选题建议。",
        "quick_prompts": ["帮我列 5 个可以模仿的选题", "这些笔记的标题有什么规律"],
    },
}


def list_templates() -> list[dict]:
    return [{"id": tid, "label": t["label"], "quick_prompts": t["quick_prompts"]} for tid, t in TEMPLATES.items()]


def _format_raw_entry(i: int, note: dict) -> str:
    desc = (note.get("desc") or "")[:_MAX_DESC_LENGTH]
    tags = "、".join(note.get("tags") or [])
    return (
        f"{i}. 标题：{note.get('title') or '(无标题)'}\n"
        f"   作者：{note.get('nickname') or ''}\n"
        f"   正文：{desc}\n"
        f"   标签：{tags}\n"
        f"   点赞 {note.get('liked_count') or 0} / 收藏 {note.get('collected_count') or 0} "
        f"/ 评论 {note.get('comment_count') or 0}\n"
        f"   发布时间：{note.get('upload_time') or ''}"
    )


def _format_structured_entry(i: int, note: dict, structured: dict) -> str:
    """
    用结构化预处理产出的精简版代替原始全文（《小红书笔记结构化预处理-技术方案.md》），
    单篇能省下 80% 左右 token。只在 status == 'ok' 时才会被调用，调用方负责判断。
    """
    key_points = "；".join(structured.get("key_points") or [])
    tags = "、".join(structured.get("topic_tags") or note.get("tags") or [])
    location = "".join(filter(None, [structured.get("city"), structured.get("area")]))
    category_line = f"   分类：{structured.get('category') or ''}"
    if location:
        category_line += f"（{location}）"
    return (
        f"{i}. 标题：{note.get('title') or '(无标题)'}\n"
        f"{category_line}\n"
        f"   摘要：{structured.get('summary') or ''}\n"
        f"   要点：{key_points}\n"
        f"   标签：{tags}\n"
        f"   点赞 {note.get('liked_count') or 0} / 收藏 {note.get('collected_count') or 0} "
        f"/ 评论 {note.get('comment_count') or 0}\n"
        f"   发布时间：{note.get('upload_time') or ''}"
    )


def _estimate_context_tokens(notes: list[dict], structured_map: dict) -> int:
    """
    粗略估算笔记语料占用的 token（中文约 1 token/1.5~2 字，按 len/2 保守估计），
    只用来做"是否超保护上限"的判断，不需要精确。
    """
    total = 0
    for note in notes:
        structured = structured_map.get(note.get("note_id"))
        if structured and structured.get("status") == "ok":
            text = (
                f"{structured.get('summary') or ''}"
                f"{''.join(structured.get('key_points') or [])}"
            )
        else:
            text = f"{note.get('title') or ''}{note.get('desc') or ''}"
        total += len(text) // 2
        total += 60  # 每条固定开销：编号/作者/互动数据/换行等
    return total


def format_notes_for_context(
    db: Session, notes: list[dict], max_notes: Optional[int] = None
) -> str:
    """
    把笔记列表整理成文本块。默认使用传入的全部笔记（用户在前端选中了多少就用多少，
    不再固定截断）；max_notes 传入时仍可限制数量（留给将来"项目级最多笔记数"配置用）。
    编号规则是笔记在传入列表里的顺序（从 1 开始），和前端 noteIndexOf/onThreadClick
    按项目笔记顺序编号、点击引用徽标定位笔记的逻辑对得上。
    build_prompt（写死模板路径）和 Skill Runtime 路径（业务上下文）共用这份格式，避免
    两边格式各写一份、后续改动只改了一边。

    每篇笔记优先用结构化预处理的精简结果（note_structurer，status == 'ok'）；还没
    处理过、处理失败、或者被规则判定为低质内容跳过处理的笔记，退回原始全文格式——
    保证没结构化过的笔记依然能正常参与分析，不会因为这次改动漏掉内容。
    """
    limited = notes if not max_notes or max_notes <= 0 else notes[:max_notes]
    structured_map = note_structurer.get_structured_map(db, [n.get("note_id") for n in limited])

    estimated = _estimate_context_tokens(limited, structured_map)
    if estimated > _MAX_CONTEXT_TOKENS:
        raise NotesContextTooLarge(
            f"选中的 {len(limited)} 篇笔记内容过多（估算约 {estimated:,} tokens，"
            f"上限 {_MAX_CONTEXT_TOKENS:,}），请减少选中的笔记数量后重试"
        )

    lines = [f"笔记数据（共 {len(limited)} 篇）："]
    for i, note in enumerate(limited, start=1):
        structured = structured_map.get(note.get("note_id"))
        if structured and structured.get("status") == "ok":
            lines.append(_format_structured_entry(i, note, structured))
        else:
            lines.append(_format_raw_entry(i, note))
    return "\n".join(lines)


def build_prompt(
    db: Session,
    notes: list[dict],
    question: str,
    template: Optional[str] = None,
    max_notes: Optional[int] = None,
) -> str:
    template_info = TEMPLATES.get(template or _DEFAULT_TEMPLATE, TEMPLATES[_DEFAULT_TEMPLATE])
    lines = [
        "你是一个小红书内容分析助手。下面是一批小红书笔记的数据（JSON 数组的简化文本形式），"
        "请基于这些笔记的标题、正文、标签和互动数据，回答用户的问题，给出有依据的结论。",
        template_info["instruction"],
        "每条结论后面另起一行，写「引用笔记：[序号]」标注支撑这条结论的笔记编号"
        "（编号就是下面笔记列表里的序号，多篇就写多个，比如 [2][8]）。",
        "",
        format_notes_for_context(db, notes, max_notes),
        "",
        f"用户的问题：{question}",
    ]
    return "\n".join(lines)


def list_analyses(db: Session, project_id: int) -> list[XhsNoteAnalysis]:
    return (
        db.query(XhsNoteAnalysis)
        .filter(XhsNoteAnalysis.project_id == project_id)
        .order_by(XhsNoteAnalysis.created_at.desc(), XhsNoteAnalysis.id.desc())
        .all()
    )


def build_conversation(
    db: Session,
    project_id: int,
    notes: list[dict],
    question: str,
    template: Optional[str] = None,
    max_notes: Optional[int] = None,
) -> list[dict]:
    """
    支持多轮追问：把这个项目里之前问成功的每一轮都还原成 user/assistant 一问一答，
    追加到本轮问题前面一起发给 Gemini，保留对话连续性。

    笔记语料每一轮都会重新嵌入本轮问题里（而不是只在第一轮嵌入一次）——右侧笔记面板
    每次都可能选中不同的子集，如果只在第一轮塞语料，之后换了选择 Gemini 根本看不到，
    等于白选。历史问答本身只回放原始问题/回答文本（不重复带语料），所以不会随着轮次
    增多而无限重复旧语料，只有"当前这一轮"的语料会被发送。
    """
    prior = [a for a in reversed(list_analyses(db, project_id)) if a.status == "success" and a.result]
    messages = []
    for a in prior:
        messages.append({"role": "user", "content": a.question})
        messages.append({"role": "assistant", "content": a.result})

    messages.append({"role": "user", "content": build_prompt(db, notes, question, template, max_notes)})
    return messages


def save_analysis(
    db: Session,
    project_id: int,
    question: str,
    model: str,
    status: str,
    result: Optional[str] = None,
    error: Optional[str] = None,
    template: Optional[str] = None,
) -> XhsNoteAnalysis:
    analysis = XhsNoteAnalysis(
        project_id=project_id,
        question=question,
        model=model,
        status=status,
        result=result,
        error=error,
        template=template,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def get_analysis(db: Session, project_id: int, analysis_id: int) -> Optional[XhsNoteAnalysis]:
    analysis = db.get(XhsNoteAnalysis, analysis_id)
    if not analysis or analysis.project_id != project_id:
        return None
    return analysis


def delete_analysis(db: Session, project_id: int, analysis_id: int) -> bool:
    analysis = db.get(XhsNoteAnalysis, analysis_id)
    if not analysis or analysis.project_id != project_id:
        return False
    db.delete(analysis)
    db.commit()
    return True


def set_feedback(db: Session, project_id: int, analysis_id: int, feedback: Optional[str]) -> Optional[XhsNoteAnalysis]:
    analysis = db.get(XhsNoteAnalysis, analysis_id)
    if not analysis or analysis.project_id != project_id:
        return None
    analysis.feedback = feedback
    db.commit()
    db.refresh(analysis)
    return analysis
