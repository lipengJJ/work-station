"""拉取并缓存本机 RSSHub 实例的路由目录（GET /api/namespace），供前端浏览/挑选路由用。

RSSHub 全量路由接近 4000 条、跨 1979 个站点（namespace），原始 payload 几 MB（大头是每条
路由的 markdown 说明文档）——既不适合每次请求都现拉现传，说明文档本身列表页也用不上。
这里只保留浏览页需要的轻字段，按站点分组缓存在进程内一段时间，减少对本机 RSSHub 实例的
请求压力；前端先浏览站点列表，选中站点后再展开该站点下的具体路由。
"""
from __future__ import annotations

import time

import requests

from app.core.config import get_settings

_CACHE_TTL_SECONDS = 1800  # 路由目录只跟着 rsshub 镜像版本变，没必要更频繁地重拉
_HTTP_TIMEOUT = 10

_cache: dict | None = None  # {"routes": [...], "namespaces": [...], "categories": [...], "fetched_at": float}


def _fetch_namespace_json() -> dict:
    settings = get_settings()
    url = f"{settings.rsshub_base_url.rstrip('/')}/api/namespace"
    try:
        resp = requests.get(url, timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError(f"连接 RSSHub（{settings.rsshub_base_url}）失败：{exc}") from exc
    try:
        return resp.json()
    except ValueError as exc:
        raise ValueError("RSSHub 返回内容不是合法 JSON") from exc


def _build(namespace_json: dict) -> dict:
    routes: list[dict] = []
    namespaces: list[dict] = []
    for ns_key, ns_info in namespace_json.items():
        if not isinstance(ns_info, dict):
            continue
        ns_name = ns_info.get("name") or ns_key
        ns_categories: set[str] = set()
        route_count = 0
        for path, route in (ns_info.get("routes") or {}).items():
            if not isinstance(route, dict):
                continue
            route_count += 1
            categories = route.get("categories") or []
            ns_categories.update(categories)
            require_config_raw = (route.get("features") or {}).get("requireConfig")
            require_config = (
                [c.get("name", "") for c in require_config_raw if isinstance(c, dict)]
                if isinstance(require_config_raw, list)
                else []
            )
            routes.append(
                {
                    "namespace": ns_key,
                    "namespace_name": ns_name,
                    "path": path,
                    "full_path": f"/{ns_key}{path}",
                    "name": route.get("name") or path,
                    "example": route.get("example") or f"/{ns_key}{path}",
                    "categories": categories,
                    "maintainers": route.get("maintainers") or [],
                    "require_config": [c for c in require_config if c],
                }
            )
        if route_count == 0:
            # 有些命名空间只有说明文档没有实际路由（比如已下线站点的占位条目），跳过
            continue
        namespaces.append(
            {
                "namespace": ns_key,
                "namespace_name": ns_name,
                "url": ns_info.get("url") or "",
                "route_count": route_count,
                "categories": sorted(ns_categories),
            }
        )

    routes.sort(key=lambda r: (r["namespace_name"], r["full_path"]))
    namespaces.sort(key=lambda n: n["namespace_name"])
    categories = sorted({c for r in routes for c in r["categories"]})
    return {"routes": routes, "namespaces": namespaces, "categories": categories}


def _load_cache(force: bool = False) -> dict:
    global _cache
    if not force and _cache is not None and time.time() - _cache["fetched_at"] < _CACHE_TTL_SECONDS:
        return _cache
    built = _build(_fetch_namespace_json())
    _cache = {**built, "fetched_at": time.time()}
    return _cache


def list_namespaces(
    keyword: str = "",
    category: str = "",
    page: int = 1,
    page_size: int = 20,
    force_refresh: bool = False,
) -> dict:
    """浏览/搜索站点（namespace）列表。失败（RSSHub 连不上等）抛 ValueError，message 可直接展示。"""
    cache = _load_cache(force=force_refresh)
    items = cache["namespaces"]

    kw = keyword.strip().lower()
    if kw:
        items = [
            n for n in items if kw in n["namespace"].lower() or kw in n["namespace_name"].lower()
        ]
    if category:
        items = [n for n in items if category in n["categories"]]

    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "categories": cache["categories"],
        "fetched_at": cache["fetched_at"],
    }


def list_routes(
    keyword: str = "",
    category: str = "",
    namespace: str = "",
    page: int = 1,
    page_size: int = 20,
    force_refresh: bool = False,
) -> dict:
    """浏览/搜索路由列表；传 namespace 只看某个站点下的路由（该场景下站点路由数最多不到 50，
    不必分页，前端会传较大的 page_size 一次拿全）。失败抛 ValueError，message 可直接展示。
    """
    cache = _load_cache(force=force_refresh)
    routes = cache["routes"]

    if namespace:
        routes = [r for r in routes if r["namespace"] == namespace]

    kw = keyword.strip().lower()
    if kw:
        routes = [
            r
            for r in routes
            if kw in r["namespace"].lower()
            or kw in r["namespace_name"].lower()
            or kw in r["name"].lower()
            or kw in r["full_path"].lower()
        ]
    if category:
        routes = [r for r in routes if category in r["categories"]]

    total = len(routes)
    start = (page - 1) * page_size
    return {
        "items": routes[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "categories": cache["categories"],
        "fetched_at": cache["fetched_at"],
    }
