from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.skills.schemas.skill import (
    FileContentOut,
    FileContentUpdateIn,
    FileNodeOut,
    FileSaveOut,
    SkillDetailOut,
    SkillSummaryOut,
    SkillTemplateOut,
    SkillVersionOut,
)
from app.skills.services import registry_service
from app.skills.services.registry_service import FileContentError
from app.skills.services.storage_service import SkillPathError

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("", response_model=list[SkillSummaryOut])
def list_skills(
    query: Optional[str] = None,
    category: Optional[str] = None,
    enabled: Optional[bool] = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    return registry_service.list_skills(db, query=query, category=category, enabled=enabled)


@router.get("/{skill_key}", response_model=SkillDetailOut)
def get_skill_detail(skill_key: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    detail = registry_service.get_skill_detail(db, skill_key)
    if not detail:
        raise HTTPException(404, "Skill 不存在")
    return detail


@router.get("/{skill_key}/versions", response_model=list[SkillVersionOut])
def list_skill_versions(skill_key: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    versions = registry_service.list_versions(db, skill_key)
    if versions is None:
        raise HTTPException(404, "Skill 不存在")
    return versions


@router.get("/{skill_key}/templates", response_model=list[SkillTemplateOut])
def list_skill_templates(skill_key: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    templates = registry_service.list_templates(db, skill_key)
    if templates is None:
        raise HTTPException(404, "Skill 不存在")
    return templates


@router.get("/{skill_key}/files", response_model=list[FileNodeOut])
def list_skill_files(skill_key: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    tree = registry_service.get_file_tree(db, skill_key)
    if tree is None:
        raise HTTPException(404, "Skill 不存在或尚无可用版本")
    return tree


@router.get("/{skill_key}/files/content", response_model=FileContentOut)
def get_skill_file_content(
    skill_key: str,
    path: str = Query(..., description="相对 Skill 根目录的文件路径"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    try:
        result = registry_service.get_file_content(db, skill_key, path)
    except (FileContentError, SkillPathError) as e:
        raise HTTPException(400, str(e))
    if result is None:
        raise HTTPException(404, "Skill 不存在或尚无可用版本")
    return result


@router.put("/{skill_key}/files/content", response_model=FileSaveOut)
def update_skill_file_content(
    skill_key: str,
    body: FileContentUpdateIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """页面编辑保存：写入文件后重新校验并生成新版本，返回最新校验结果。"""
    try:
        result = registry_service.save_file_content(db, skill_key, body.path, body.content)
    except (FileContentError, SkillPathError) as e:
        raise HTTPException(400, str(e))
    if result is None:
        raise HTTPException(404, "Skill 不存在或尚无可用版本")
    return result
