"""
解析 Skill 目录里的三份声明文件：SKILL.md（必需）、workbench.yaml（可选，工作台自己的
扩展清单）、agents/openai.yaml（可选，展示名称/简介/默认提示）。三者合并成一份规整的
manifest dict，后面 registry_service 落库、controller 序列化都基于这份 dict，不用再重复
解析 YAML/frontmatter。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import json

import yaml


class ManifestError(ValueError):
    """SKILL.md 缺失或格式不满足最低要求（没有 YAML frontmatter，或者缺 name/description）。"""


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """
    SKILL.md 的格式是 `---\nyaml...\n---\n正文`。没有以 `---` 开头就说明没有 frontmatter，
    直接判为不合法——name/description 是路由和列表页最基本的展示字段，不能没有。
    """
    stripped = text.lstrip("﻿")  # 允许文件带 BOM
    if not stripped.startswith("---"):
        raise ManifestError("SKILL.md 缺少 YAML frontmatter（应以 --- 开头）")
    remainder = stripped[3:]
    end_idx = remainder.find("\n---")
    if end_idx == -1:
        raise ManifestError("SKILL.md 的 YAML frontmatter 未正确闭合")
    front_raw = remainder[:end_idx]
    body = remainder[end_idx + 4 :].lstrip("\n")
    try:
        front = yaml.safe_load(front_raw) or {}
    except yaml.YAMLError as e:
        raise ManifestError(f"SKILL.md 的 YAML frontmatter 解析失败：{e}") from e
    if not isinstance(front, dict):
        raise ManifestError("SKILL.md 的 YAML frontmatter 必须是键值结构")
    return front, body


def parse_skill_md(skill_dir: Path) -> dict[str, Any]:
    path = skill_dir / "SKILL.md"
    if not path.is_file():
        raise ManifestError("缺少 SKILL.md")
    front, body = _split_frontmatter(path.read_text(encoding="utf-8"))

    name = front.get("name")
    description = front.get("description")
    if not name or not isinstance(name, str):
        raise ManifestError("SKILL.md frontmatter 缺少 name 字段")
    if not description or not isinstance(description, str):
        raise ManifestError("SKILL.md frontmatter 缺少 description 字段")

    return {"name": name.strip(), "description": description.strip(), "instruction": body}


def parse_workbench_yaml(skill_dir: Path) -> dict[str, Any] | None:
    """可选扩展清单：没有就返回 None，调用方按"通用 Skill"处理，不当错误。"""
    path = skill_dir / "workbench.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ManifestError(f"workbench.yaml 解析失败：{e}") from e
    if not isinstance(data, dict):
        raise ManifestError("workbench.yaml 必须是键值结构")
    return data


def parse_agent_openai_yaml(skill_dir: Path) -> dict[str, Any] | None:
    path = skill_dir / "agents" / "openai.yaml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        # 展示名称/默认提示是锦上添花的信息，这个文件解析失败不应该导致整个 Skill 加载失败
        return None
    return data if isinstance(data, dict) else None


def _parse_input_schema(skill_dir: Path, schema_path: str | None) -> dict[str, Any] | None:
    """
    workbench.yaml 的 inputs.schema 指向一份 JSON Schema 文件，供分析入口做表单渲染和输入
    校验。这里只在扫描阶段（内部可信路径，非用户请求）直接读取，解析失败只记为 None，
    不阻塞整个 Skill 的登记——分析创建时会再次校验 schema 是否可用。
    """
    if not schema_path:
        return None
    path = skill_dir / schema_path.removeprefix("./")
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def build_manifest(skill_dir: Path) -> dict[str, Any]:
    """
    合并出一份规整 manifest：
    - display_name / description 优先取 agents/openai.yaml 的展示文案，没有就退回 SKILL.md 的 name/description
    - templates 来自 workbench.yaml，字段缺失时给合理默认值，模板本身没有 workbench.yaml 时是空列表
    """
    skill_md = parse_skill_md(skill_dir)
    workbench = parse_workbench_yaml(skill_dir) or {}
    agent = parse_agent_openai_yaml(skill_dir) or {}
    interface = agent.get("interface") if isinstance(agent.get("interface"), dict) else {}

    templates = []
    for tpl in workbench.get("templates") or []:
        if not isinstance(tpl, dict) or not tpl.get("id"):
            continue
        templates.append(
            {
                "id": str(tpl["id"]),
                "name": tpl.get("name") or str(tpl["id"]),
                "description": tpl.get("description") or "",
                "prompt": tpl.get("prompt"),
                "output": tpl.get("output"),
            }
        )

    runtime = workbench.get("runtime") if isinstance(workbench.get("runtime"), dict) else {}
    tools = runtime.get("tools") if isinstance(runtime.get("tools"), dict) else {}
    input_schema_path = (
        (workbench.get("inputs") or {}).get("schema") if isinstance(workbench.get("inputs"), dict) else None
    )

    return {
        "skill_key": skill_dir.name,
        "name": skill_md["name"],
        "display_name": interface.get("display_name") or skill_md["name"],
        "description": interface.get("short_description") or skill_md["description"],
        "default_prompt": interface.get("default_prompt"),
        "instruction": skill_md["instruction"],
        "version": str(workbench.get("version") or "1.0.0"),
        "category": workbench.get("category"),
        "tags": workbench.get("tags") or [],
        "runtime": {
            "preferred_provider": runtime.get("preferred_provider"),
            "recommended_model": runtime.get("recommended_model"),
            "tools": {
                "google_search": bool(tools.get("google_search")),
                "url_context": bool(tools.get("url_context")),
            },
        },
        "input_schema_path": input_schema_path,
        "input_schema": _parse_input_schema(skill_dir, input_schema_path),
        "templates": templates,
        "has_workbench_manifest": bool(workbench),
    }
