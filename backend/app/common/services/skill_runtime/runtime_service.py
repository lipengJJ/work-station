"""
Skill Runtime 的唯一入口：analysis 模块只调 prepare_run，不自己拼 Loader/Context Resolver/
Prompt Builder/Permission Resolver（设计文档 4 节"所有业务模块统一调用 SkillRuntimeService，
不各自拼接 Skill"）。以后小红书/股票分析要接入 Skill 能力时，也走这一个函数。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.common.services.skill_runtime import loader, permission_resolver, prompt_builder
from app.common.services.skill_runtime.context_resolver import resolve_skill_context
from app.common.services.skill_runtime.loader import LoadedSkill, LoadedTemplate, SkillRuntimeError
from app.skills.services import registry_service


@dataclass
class PreparedRun:
    skill: LoadedSkill
    template: Optional[LoadedTemplate]
    system_instruction: str
    user_message: str
    tools: list[str]


def prepare_run(
    db: Session,
    skill_key: str,
    template_key: Optional[str],
    inputs: dict,
    question: Optional[str],
    enable_search: bool,
    business_context: Optional[str] = None,
) -> PreparedRun:
    loaded_skill = loader.load_skill(db, skill_key)

    loaded_template = None
    if template_key:
        skill_row = registry_service.get_skill(db, skill_key)
        if not skill_row:
            raise SkillRuntimeError(f"Skill 不存在：{skill_key}")
        loaded_template = loader.load_template(db, skill_row, template_key)

    skill_context = resolve_skill_context(loaded_skill, loaded_template)

    return PreparedRun(
        skill=loaded_skill,
        template=loaded_template,
        system_instruction=prompt_builder.build_system_instruction(skill_context),
        user_message=prompt_builder.build_user_message(inputs, question, business_context),
        tools=permission_resolver.resolve_tools(loaded_skill.tool_policy, enable_search),
    )
