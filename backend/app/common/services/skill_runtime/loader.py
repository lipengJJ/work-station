"""
按数据库登记的受控路径加载 Skill 内容：只经过 registry_service/storage_service 已经校验
过的路径，不接受调用方传入的任意路径。返回值是运行时需要的原始内容（指令正文、
references 全文、选中模板的 prompt/output 片段），Prompt Builder 在这基础上拼最终请求。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from app.skills.models import Skill
from app.skills.services import registry_service, storage_service
from app.skills.services.storage_service import SkillPathError


class SkillRuntimeError(Exception):
    """Skill 不存在、被禁用、没有可用版本，或模板不存在——controller 转成对应的 4xx。"""


@dataclass
class LoadedTemplate:
    template_key: str
    name: str
    prompt_text: Optional[str]
    output_template_text: Optional[str]
    input_schema: Optional[dict]


@dataclass
class LoadedSkill:
    skill_id: int
    skill_key: str
    skill_version_id: int
    version: str
    display_name: str
    instruction: str
    references: list[tuple[str, str]] = field(default_factory=list)  # (相对路径, 文本内容)
    tool_policy: dict = field(default_factory=dict)


def load_skill(db: Session, skill_key: str) -> LoadedSkill:
    skill = registry_service.get_skill(db, skill_key)
    if not skill:
        raise SkillRuntimeError(f"Skill 不存在：{skill_key}")
    if not skill.enabled:
        raise SkillRuntimeError(f"Skill 已禁用：{skill_key}")
    version = registry_service.get_current_version(db, skill)
    if not version:
        raise SkillRuntimeError(f"Skill 尚无可用版本：{skill_key}")

    manifest = json.loads(version.manifest_json)
    root = storage_service.resolve_skill_root(skill.source_type, version.storage_path)

    return LoadedSkill(
        skill_id=skill.id,
        skill_key=skill.skill_key,
        skill_version_id=version.id,
        version=version.version,
        display_name=manifest.get("display_name") or skill.display_name,
        instruction=manifest.get("instruction") or "",
        references=_load_references(root),
        tool_policy=(manifest.get("runtime") or {}).get("tools") or {},
    )


def _load_references(root) -> list[tuple[str, str]]:
    """
    第一阶段 Context Resolver 的简化策略："references/ 下的文件全部加载"，没有做"按模板
    声明挑选子集"这种更精细的按需加载（设计文档里提到的可选优化项，留给后续阶段）。
    """
    result: list[tuple[str, str]] = []
    for node in storage_service.build_file_tree(root):
        if node.type == "dir" and node.name == "references":
            for child in node.children:
                if child.type != "file":
                    continue
                try:
                    text, _truncated = storage_service.read_file_text(root, child.path)
                except SkillPathError:
                    continue
                result.append((child.path, text))
    return result


def load_template(db: Session, skill: Skill, template_key: str) -> LoadedTemplate:
    row = registry_service.get_template_row(db, skill, template_key)
    if not row:
        raise SkillRuntimeError(f"模板不存在或未启用：{template_key}")
    version = registry_service.get_current_version(db, skill)
    if not version:
        raise SkillRuntimeError(f"Skill 尚无可用版本：{skill.skill_key}")
    root = storage_service.resolve_skill_root(skill.source_type, version.storage_path)

    return LoadedTemplate(
        template_key=row.template_key,
        name=row.name,
        prompt_text=_read_optional(root, row.prompt_path),
        output_template_text=_read_optional(root, row.output_template_path),
        input_schema=json.loads(row.input_schema_json) if row.input_schema_json else None,
    )


def _read_optional(root, relative_path: Optional[str]) -> Optional[str]:
    if not relative_path:
        return None
    try:
        text, _truncated = storage_service.read_file_text(root, relative_path.removeprefix("./"))
    except SkillPathError:
        return None
    return text
