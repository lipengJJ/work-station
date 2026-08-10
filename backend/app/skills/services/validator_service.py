"""
Skill 目录的结构与安全校验：第一阶段只在扫描内置 Skill 时跑一遍、把结果存进
SkillVersion.validation_json 供详情页展示风险；第二阶段导入向导会复用同一份校验
逻辑挡掉不合法的上传（对应设计文档 5.1 节"必需校验"）。
"""
from __future__ import annotations

import re
from pathlib import Path

from app.skills.services.storage_service import FileNode, build_file_tree

_NAME_PATTERN = re.compile(r"^[a-z0-9-]{1,64}$")

# 第一阶段拒绝的可执行/二进制文件扩展名（本身不执行任何脚本，这里只是在展示前标红风险）
_EXECUTABLE_EXTENSIONS = {".exe", ".sh", ".bash", ".bat", ".cmd", ".ps1", ".so", ".dll", ".dylib", ".bin"}

MAX_TOTAL_BYTES = 20 * 1024 * 1024  # Skill 目录总体积上限 20MB
MAX_SINGLE_FILE_BYTES = 5 * 1024 * 1024  # 单文件上限 5MB


def _flatten(nodes: list[FileNode]) -> list[FileNode]:
    flat: list[FileNode] = []
    for node in nodes:
        if node.type == "file":
            flat.append(node)
        else:
            flat.extend(_flatten(node.children))
    return flat


def validate_skill(skill_dir: Path, manifest: dict) -> dict:
    """返回 {valid, errors, warnings, risk_level}。errors 非空时该 Skill 不应该被启用。"""
    errors: list[str] = []
    warnings: list[str] = []

    skill_key = skill_dir.name
    if not _NAME_PATTERN.match(skill_key):
        errors.append(f"目录名 {skill_key!r} 不满足命名规则（小写字母/数字/短横线，1-64 位）")
    if manifest.get("name") != skill_key:
        errors.append(f"SKILL.md 的 name（{manifest.get('name')!r}）与目录名（{skill_key!r}）不一致")

    files = _flatten(build_file_tree(skill_dir))
    total_size = sum(f.size or 0 for f in files)
    if total_size > MAX_TOTAL_BYTES:
        errors.append(f"Skill 目录总体积超限：{total_size} 字节 > {MAX_TOTAL_BYTES} 字节")

    has_scripts = False
    has_executable = False
    for f in files:
        if (f.size or 0) > MAX_SINGLE_FILE_BYTES:
            warnings.append(f"文件过大，预览时会被截断：{f.path}")
        if f.path.startswith("scripts/"):
            has_scripts = True
        ext = Path(f.name).suffix.lower()
        if ext in _EXECUTABLE_EXTENSIONS:
            has_executable = True
            warnings.append(f"检测到可执行/二进制文件（仅展示，不会被执行）：{f.path}")

    if has_scripts:
        warnings.append("包含 scripts/ 目录：当前阶段只允许查看，禁止执行其中的任何脚本")

    if errors:
        risk_level = "blocked"
    elif has_executable:
        risk_level = "high"
    elif has_scripts:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "risk_level": risk_level,
        "total_size": total_size,
        "file_count": len(files),
    }
