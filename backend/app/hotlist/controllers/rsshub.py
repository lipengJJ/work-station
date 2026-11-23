"""RSSHub 路由目录：/api/hotlist/rsshub/*（需要登录）。

- GET /namespaces   站点（namespace）列表，关键词 + 分类筛选 + 分页
- GET /routes       路由列表；传 namespace 只看某个站点下的路由（前端点开站点详情用）

浏览本机 RSSHub 实例支持的站点路由，挑地址去「新建 RSS 源」用。只读、轻量代理 +
进程内缓存，不落库——目录本身就是 RSSHub 镜像自带的静态元数据。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import get_current_user
from app.hotlist.schemas.rsshub import RsshubNamespaceListOut, RsshubRouteListOut
from app.hotlist.services import rsshub_service

router = APIRouter(prefix="/api/hotlist/rsshub", tags=["hotlist"])


@router.get("/namespaces")
def list_rsshub_namespaces(
    keyword: str = Query(""),
    category: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    refresh: bool = Query(False, description="跳过缓存，强制重新拉取"),
    _=Depends(get_current_user),
) -> RsshubNamespaceListOut:
    try:
        result = rsshub_service.list_namespaces(
            keyword=keyword,
            category=category,
            page=page,
            page_size=page_size,
            force_refresh=refresh,
        )
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from exc
    return RsshubNamespaceListOut.model_validate(result)


@router.get("/routes")
def list_rsshub_routes(
    keyword: str = Query(""),
    category: str = Query(""),
    namespace: str = Query("", description="只看该站点下的路由"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    refresh: bool = Query(False, description="跳过缓存，强制重新拉取"),
    _=Depends(get_current_user),
) -> RsshubRouteListOut:
    try:
        result = rsshub_service.list_routes(
            keyword=keyword,
            category=category,
            namespace=namespace,
            page=page,
            page_size=page_size,
            force_refresh=refresh,
        )
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from exc
    return RsshubRouteListOut.model_validate(result)
