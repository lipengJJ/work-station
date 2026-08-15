"""
Skill 登记中心：扫描内置 Skill 目录、把结果落库，并给 controller 提供列表/详情/文件树/
模板查询。第一阶段只读——启用/禁用/导入/删除留给第二阶段，这里刻意不做任何写操作
之外的入口（scan_builtin_skills 是唯一的写路径，且只在启动时跑）。
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.skills.models import Skill, SkillTemplate, SkillVersion
from app.skills.services import manifest_service, storage_service, validator_service
from app.skills.services.manifest_service import ManifestError
from app.skills.services.storage_service import SkillPathError

logger = logging.getLogger(__name__)


def _sync_skill(db: Session, skill: Skill, skill_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    单个 Skill 的"重解析 + 落库"：构建 manifest、校验、内容哈希没变就跳过（不新建版本行、
    不重复解析），变了才生成新的 SkillVersion + 重建模板行。扫描启动和页面保存后都会走到
    这里，保证两条写路径行为一致。manifest 解析失败时抛 ManifestError，由调用方决定怎么处理
    （启动扫描跳过该 Skill，页面保存则把错误透出给用户）。
    """
    manifest = manifest_service.build_manifest(skill_dir)
    validation = validator_service.validate_skill(skill_dir, manifest)
    content_hash = storage_service.compute_content_hash(skill_dir)

    skill.display_name = manifest["display_name"]
    skill.description = manifest["description"]
    skill.category = manifest.get("category")
    skill.risk_level = validation["risk_level"]
    # 新建 Skill 时在这里先 flush：确保主键已生成，下面 SkillVersion.skill_id 才能取到；
    # 对已有 Skill 只是一次 UPDATE，无害。（配合 scan_builtin_skills 不在 add 后提前 flush）
    db.flush()

    current_version = (
        db.get(SkillVersion, skill.current_version_id) if skill.current_version_id else None
    )
    if current_version is None or current_version.content_hash != content_hash:
        version = SkillVersion(
            skill_id=skill.id,
            version=manifest["version"],
            storage_path=skill_dir.name,
            content_hash=content_hash,
            manifest_json=json.dumps(manifest, ensure_ascii=False),
            validation_json=json.dumps(validation, ensure_ascii=False),
        )
        db.add(version)
        db.flush()
        skill.current_version_id = version.id

        input_schema = manifest.get("input_schema")
        input_schema_json = json.dumps(input_schema, ensure_ascii=False) if input_schema else None

        db.query(SkillTemplate).filter(SkillTemplate.skill_version_id == version.id).delete()
        for tpl in manifest["templates"]:
            db.add(
                SkillTemplate(
                    skill_version_id=version.id,
                    template_key=tpl["id"],
                    name=tpl["name"],
                    description=tpl.get("description"),
                    prompt_path=tpl.get("prompt"),
                    output_template_path=tpl.get("output"),
                    input_schema_json=input_schema_json,
                )
            )
    return manifest, validation


def scan_builtin_skills(db: Session) -> None:
    """
    扫描 workbench/skills/ 下的每个内置 Skill 目录。内容哈希没变就跳过（不新建版本行、
    不重复解析），变了才生成新的 SkillVersion + 重建模板行。单个 Skill 解析/校验失败
    不影响其余 Skill 的扫描——记日志，跳过它，不让一个坏 Skill 挡住整个启动流程。
    """
    for skill_dir in storage_service.list_builtin_skill_dirs():
        skill_key = skill_dir.name
        skill = db.query(Skill).filter(Skill.skill_key == skill_key).first()
        if skill is None:
            skill = Skill(skill_key=skill_key, source_type="builtin")
            db.add(skill)
        # 注意：这里不要提前 flush——新建 Skill 时 display_name 还是 None，
        # 提前 flush 会违反 NOT NULL 约束（全新数据库首次启动即报错）；
        # 让 _sync_skill 先赋值 display_name 等字段，再由其内部的 flush 落库。
        try:
            _sync_skill(db, skill, skill_dir)
            db.commit()
        except ManifestError as e:
            logger.warning("跳过内置 Skill %s：%s", skill_key, e)
            db.rollback()


def scan_on_startup() -> None:
    """main.py 的 lifespan 里调用一次，独立开关一个 db session，和 xhs 那边 requeue_pending_tasks 是同一个模式。"""
    db = SessionLocal()
    try:
        scan_builtin_skills(db)
    finally:
        db.close()


def _skill_summary(db: Session, skill: Skill) -> dict[str, Any]:
    template_count = 0
    if skill.current_version_id:
        template_count = (
            db.query(SkillTemplate)
            .filter(SkillTemplate.skill_version_id == skill.current_version_id)
            .count()
        )
    version = db.get(SkillVersion, skill.current_version_id) if skill.current_version_id else None
    return {
        "skill_key": skill.skill_key,
        "display_name": skill.display_name,
        "description": skill.description,
        "category": skill.category,
        "source_type": skill.source_type,
        "enabled": skill.enabled,
        "risk_level": skill.risk_level,
        "version": version.version if version else None,
        "template_count": template_count,
        "created_at": skill.created_at,
        "updated_at": skill.updated_at,
    }


def list_skills(
    db: Session,
    query: Optional[str] = None,
    category: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> list[dict[str, Any]]:
    q = db.query(Skill)
    if query:
        like = f"%{query.strip()}%"
        q = q.filter(Skill.display_name.ilike(like) | Skill.description.ilike(like))
    if category:
        q = q.filter(Skill.category == category)
    if enabled is not None:
        q = q.filter(Skill.enabled == enabled)
    skills = q.order_by(Skill.updated_at.desc()).all()
    return [_skill_summary(db, s) for s in skills]


def get_skill(db: Session, skill_key: str) -> Optional[Skill]:
    return db.query(Skill).filter(Skill.skill_key == skill_key).first()


def get_current_version(db: Session, skill: Skill) -> Optional[SkillVersion]:
    if not skill.current_version_id:
        return None
    return db.get(SkillVersion, skill.current_version_id)


def get_skill_detail(db: Session, skill_key: str) -> Optional[dict[str, Any]]:
    skill = get_skill(db, skill_key)
    if not skill:
        return None
    version = get_current_version(db, skill)
    if not version:
        return {**_skill_summary(db, skill), "manifest": None, "validation": None, "templates": []}

    manifest = json.loads(version.manifest_json)
    validation = json.loads(version.validation_json)
    templates = list_templates(db, skill_key) or []

    return {
        **_skill_summary(db, skill),
        "instruction": manifest.get("instruction"),
        "default_prompt": manifest.get("default_prompt"),
        "tags": manifest.get("tags", []),
        "runtime": manifest.get("runtime"),
        "validation": validation,
        "templates": templates,
    }


def list_versions(db: Session, skill_key: str) -> Optional[list[dict[str, Any]]]:
    skill = get_skill(db, skill_key)
    if not skill:
        return None
    versions = (
        db.query(SkillVersion)
        .filter(SkillVersion.skill_id == skill.id)
        .order_by(SkillVersion.created_at.desc())
        .all()
    )
    return [
        {
            "id": v.id,
            "version": v.version,
            "content_hash": v.content_hash,
            "is_current": v.id == skill.current_version_id,
            "created_at": v.created_at,
        }
        for v in versions
    ]


def list_templates(db: Session, skill_key: str) -> Optional[list[dict[str, Any]]]:
    skill = get_skill(db, skill_key)
    if not skill or not skill.current_version_id:
        return [] if skill else None
    templates = (
        db.query(SkillTemplate)
        .filter(SkillTemplate.skill_version_id == skill.current_version_id, SkillTemplate.enabled.is_(True))
        .all()
    )
    return [
        {
            "template_key": t.template_key,
            "name": t.name,
            "description": t.description,
            "prompt_path": t.prompt_path,
            "output_template_path": t.output_template_path,
            "input_schema": json.loads(t.input_schema_json) if t.input_schema_json else None,
        }
        for t in templates
    ]


def get_template_row(db: Session, skill: Skill, template_key: str) -> Optional[SkillTemplate]:
    """给 skill_runtime / analysis 用的原始 ORM 行（不是序列化 dict），需要 skill_version_id 等字段。"""
    if not skill.current_version_id:
        return None
    return (
        db.query(SkillTemplate)
        .filter(
            SkillTemplate.skill_version_id == skill.current_version_id,
            SkillTemplate.template_key == template_key,
            SkillTemplate.enabled.is_(True),
        )
        .first()
    )


def get_file_tree(db: Session, skill_key: str) -> Optional[list[dict[str, Any]]]:
    skill = get_skill(db, skill_key)
    version = get_current_version(db, skill) if skill else None
    if not skill or not version:
        return None
    root = storage_service.resolve_skill_root(skill.source_type, version.storage_path)
    return [asdict(node) for node in storage_service.build_file_tree(root)]


class FileContentError(Exception):
    pass


def get_file_content(db: Session, skill_key: str, relative_path: str) -> Optional[dict[str, Any]]:
    skill = get_skill(db, skill_key)
    version = get_current_version(db, skill) if skill else None
    if not skill or not version:
        return None
    root = storage_service.resolve_skill_root(skill.source_type, version.storage_path)
    try:
        content, truncated = storage_service.read_file_text(root, relative_path)
    except SkillPathError as e:
        raise FileContentError(str(e)) from e
    return {"path": relative_path, "content": content, "truncated": truncated}


def save_file_content(
    db: Session, skill_key: str, relative_path: str, content: str
) -> Optional[dict[str, Any]]:
    """
    页面编辑保存：把文本写回 Skill 目录，然后重新解析 manifest、校验并同步版本记录
    （内容哈希变了就生成新的 SkillVersion，与启动扫描行为一致）。
    返回 {"path", "saved", "manifest_error", "validation"}；skill 不存在/无版本返回 None。
    manifest 解析失败（比如用户改坏了 SKILL.md 的 frontmatter）时文件照常保存，
    但注册信息保持旧版本不动，通过 manifest_error 把原因透出给前端。
    """
    skill = get_skill(db, skill_key)
    version = get_current_version(db, skill) if skill else None
    if not skill or not version:
        return None
    root = storage_service.resolve_skill_root(skill.source_type, version.storage_path)
    try:
        storage_service.write_file_text(root, relative_path, content)
    except SkillPathError as e:
        raise FileContentError(str(e)) from e

    try:
        _, validation = _sync_skill(db, skill, root)
        db.commit()
    except ManifestError as e:
        db.rollback()
        logger.warning("保存 %s 后 manifest 解析失败：%s", skill_key, e)
        return {"path": relative_path, "saved": True, "manifest_error": str(e), "validation": None}

    return {
        "path": relative_path,
        "saved": True,
        "manifest_error": None,
        "validation": validation,
    }
