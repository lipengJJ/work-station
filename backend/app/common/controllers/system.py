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
# 不用去 docker logs / ssh 到服务器上看。前端日志页支持 tail 跟随 + 5 秒自动刷新，
# 接口用 seek 只读文件尾部（按行数估算读取字节），避免每次全量读 20MB 轮转文件。


def _read_tail_lines(path, lines: int) -> tuple[list[str], int]:
    """高效读取文件尾部 N 行，返回 (行列表, 文件总行数)。文件行数用换行符计数近似。"""
    with open(path, "rb") as f:
        f.seek(0, 2)
        file_size = f.tell()
        # 每行按 ~180 字节估算读取窗口，最少 64KB，最多整个文件
        read_bytes = min(file_size, max(64 * 1024, int(lines * 180 * 1.2)))
        f.seek(max(0, file_size - read_bytes))
        chunk = f.read().decode("utf-8", errors="replace")
    total = chunk.count("\n")
    part = chunk.splitlines()
    return part[-lines:], total


@router.get("/logs")
def get_logs(lines: int = 500, _=Depends(get_current_user)):
    lines = max(1, min(lines, 5000))
    if not LOG_FILE.exists():
        return {"lines": [], "file": str(LOG_FILE), "total_lines": 0}
    tail, total_lines = _read_tail_lines(LOG_FILE, lines)
    return {
        "lines": tail,
        "file": str(LOG_FILE),
        "total_lines": total_lines,
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
