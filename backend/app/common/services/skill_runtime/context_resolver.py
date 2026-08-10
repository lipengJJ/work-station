"""
决定"这次执行"实际发给 Gemini 的上下文有多大：固定顺序拼 Skill 指令 + references +
模板补充 + 输出格式模板，设一个总字符数上限——超限直接拒绝（报错），不做静默截断，
避免关键规则（比如安全约束）被悄悄砍掉（设计文档 5.4 节 Context Resolver）。
"""
from __future__ import annotations

from typing import Optional

from app.common.services.skill_runtime.loader import LoadedSkill, LoadedTemplate

MAX_CONTEXT_CHARS = 60_000


class ContextTooLargeError(Exception):
    pass


def resolve_skill_context(skill: LoadedSkill, template: Optional[LoadedTemplate]) -> str:
    parts = [skill.instruction]
    for path, text in skill.references:
        parts.append(f"## 参考规则：{path}\n\n{text}")
    if template and template.prompt_text:
        parts.append(f"## 模板补充：{template.name}\n\n{template.prompt_text}")
    if template and template.output_template_text:
        parts.append(f"## 输出格式模板\n\n{template.output_template_text}")

    combined = "\n\n".join(p for p in parts if p)
    if len(combined) > MAX_CONTEXT_CHARS:
        raise ContextTooLargeError(
            f"Skill 内容总长度 {len(combined)} 字符超过上限 {MAX_CONTEXT_CHARS}，请精简 references 或模板内容"
        )
    return combined
