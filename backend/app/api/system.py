from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import ApiConfig, ScheduleConfig, User
from app.schemas.system import ApiConfigIn, ApiConfigOut, ScheduleConfigIn, ScheduleConfigOut, UserOut

router = APIRouter(prefix="/api/system", tags=["system"])


# ---------------------------------------------------------------- 用户与权限 ----
# Phase 2 只读列表，起步阶段单管理员账号；细粒度权限管理留到真实需要时再加。

@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(User).all()


# -------------------------------------------------------------------- API 配置 ----

@router.get("/api-configs", response_model=list[ApiConfigOut])
def list_api_configs(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(ApiConfig).all()


@router.put("/api-configs", response_model=ApiConfigOut)
def upsert_api_config(body: ApiConfigIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    existing = db.query(ApiConfig).filter(ApiConfig.name == body.name).first()
    if existing:
        existing.value = body.value
        existing.description = body.description
    else:
        existing = ApiConfig(**body.model_dump())
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing


@router.delete("/api-configs/{config_id}")
def delete_api_config(config_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    obj = db.get(ApiConfig, config_id)
    if not obj:
        raise HTTPException(404, "配置不存在")
    db.delete(obj)
    db.commit()
    return {"success": True}


# -------------------------------------------------------------------- 定时任务 ----
# Phase 3 接入 stock/xhs 真实调度逻辑时，会读这张表决定要不要往 core/scheduler 里注册 job。

@router.get("/schedules", response_model=list[ScheduleConfigOut])
def list_schedules(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(ScheduleConfig).all()


@router.put("/schedules", response_model=ScheduleConfigOut)
def upsert_schedule(body: ScheduleConfigIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    existing = db.query(ScheduleConfig).filter(ScheduleConfig.module == body.module).first()
    if existing:
        for key, value in body.model_dump().items():
            setattr(existing, key, value)
    else:
        existing = ScheduleConfig(**body.model_dump())
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing
