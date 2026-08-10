from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.resource.models import ResourceSaveTask
from app.resource.schemas.resource import CookieIn, LinkCheckIn, SaveIn
from app.resource.services import cookie_store, link_checker, quark_source
from app.resource.services.base import ResourceSourceError
from app.resource.services.quark_client import QuarkClient
from app.resource.services.registry import registry

router = APIRouter(prefix="/api/resource", tags=["resource"])


# ------------------------------------------------------------------ 源列表 ----
@router.get("/sources")
def list_sources(_=Depends(get_current_user)):
    """可用资源源列表：新增网盘源注册后这里自动出现，前端据此渲染可选项。"""
    return [
        {
            "source_id": s.source_id,
            "source_name": s.source_name,
            "supports_search": s.supports_search,
            "supports_save": s.supports_save,
            "search_providers": s.search_providers,
        }
        for s in registry.list()
    ]


# -------------------------------------------------------------------- 搜索 ----
@router.get("/search")
def search(
    keyword: str = Query(..., min_length=1, max_length=100),
    source: str = Query("quark"),
    category: str = Query("", max_length=20),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    _=Depends(get_current_user),
):
    src = registry.get(source)
    if not src.supports_search:
        raise HTTPException(400, f"资源源 {source} 不支持搜索")
    try:
        return src.search(keyword, category, page, page_size)
    except ResourceSourceError as exc:
        raise HTTPException(502, str(exc))


# -------------------------------------------------------------------- 转存 ----
@router.post("/links/check")
def check_links(body: LinkCheckIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """批量校验夸克分享链接是否有效（最多 20 条）。"""
    return link_checker.check_links(db, [item.model_dump() for item in body.links])


@router.post("/save")
def save_resource(body: SaveIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    src = registry.get(body.source)
    if not src.supports_save:
        raise HTTPException(400, f"资源源 {body.source} 不支持转存")
    try:
        return src.save(
            share_url=body.share_url.strip(),
            share_pwd=body.share_pwd.strip(),
            target_dir=body.target_dir.strip(),
            db=db,
        )
    except ResourceSourceError as exc:
        raise HTTPException(400, str(exc))


@router.get("/save-tasks")
def list_save_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(ResourceSaveTask).order_by(ResourceSaveTask.id.desc())
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.delete("/save-tasks/{task_id}")
def delete_save_task(task_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    task = db.get(ResourceSaveTask, task_id)
    if not task:
        raise HTTPException(404, "转存记录不存在")
    db.delete(task)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------- 夸克 Cookie ----
@router.get("/quark/cookie")
def get_quark_cookie(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return cookie_store.get_status(db)


@router.post("/quark/cookie")
def set_quark_cookie(body: CookieIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    cookie_store.set_cookies_str(db, body.cookies.strip())
    return cookie_store.get_status(db)


@router.delete("/quark/cookie")
def clear_quark_cookie(db: Session = Depends(get_db), _=Depends(get_current_user)):
    cookie_store.clear(db)
    return cookie_store.get_status(db)


@router.get("/quark/me")
def quark_me(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """校验夸克 Cookie 有效性，返回账号信息（昵称/会员/容量）。"""
    cookies_str = cookie_store.get_cookies_str(db)
    if not cookies_str:
        raise HTTPException(400, "尚未配置夸克 Cookie")
    try:
        info = QuarkClient(cookies_str).get_account_info()
    except ResourceSourceError as exc:
        raise HTTPException(401, str(exc))
    return {
        "nickname": info.get("nickname") or "",
        "vip_member": bool(info.get("vip_member")),
        "capacity": info.get("capacity") or 0,
        "used": info.get("used") or 0,
    }


# 模块初始化：注册夸克资源源（后续新增源在此追加 register 一行）
registry.register(quark_source.QuarkSource())
