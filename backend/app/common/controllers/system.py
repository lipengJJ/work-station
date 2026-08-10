from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.database import get_db
from app.core.logging import LOG_FILE
from app.common.models import ApiConfig, ScheduleConfig, User
from app.common.schemas.system import ApiConfigIn, ApiConfigOut, ScheduleConfigIn, ScheduleConfigOut, UserOut

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
        if body.value:
            existing.value = body.value
        existing.description = body.description
    else:
        if not body.value:
            raise HTTPException(400, "首次新增配置需要填写值")
        existing = ApiConfig(name=body.name, value=body.value, description=body.description)
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


# ---------------------------------------------------------------------- 日志 ----
# 排查"AI 分析超时""采集任务失败"这类问题用：读 app/core/logging.py 配的落盘文件尾部，
# 不用去 docker logs / ssh 到服务器上看。全量读文件再切尾部，文件本身按大小轮转封顶在
# 20MB，作为一个偶尔才用的排查工具接口，没必要为这个再引入更复杂的读取方式。

@router.get("/logs")
def get_logs(lines: int = 500, _=Depends(get_current_user)):
    lines = max(1, min(lines, 5000))
    if not LOG_FILE.exists():
        return {"lines": [], "file": str(LOG_FILE), "total_lines": 0}
    with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()
    tail = all_lines[-lines:]
    return {
        "lines": [line.rstrip("\n") for line in tail],
        "file": str(LOG_FILE),
        "total_lines": len(all_lines),
    }


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
