"""RSSHub 路由目录：展示本机 RSSHub 实例支持哪些站点/路由，方便挑选地址去新建 RSS 源。"""
from __future__ import annotations

from pydantic import BaseModel


class RsshubRouteOut(BaseModel):
    namespace: str
    namespace_name: str
    path: str
    full_path: str
    name: str
    example: str
    categories: list[str]
    maintainers: list[str]
    # 该路由要跑起来还需要配置哪些环境变量（如 TWITTER_AUTH_TOKEN）；空 = 无需额外配置
    require_config: list[str]


class RsshubRouteListOut(BaseModel):
    items: list[RsshubRouteOut]
    total: int
    page: int
    page_size: int
    # 全量分类（不受当前筛选影响），前端拿来渲染分类下拉
    categories: list[str]
    # 目录缓存的抓取时间（epoch 秒）
    fetched_at: float


class RsshubNamespaceOut(BaseModel):
    namespace: str
    namespace_name: str
    url: str
    route_count: int
    # 该站点下所有路由的分类并集
    categories: list[str]


class RsshubNamespaceListOut(BaseModel):
    items: list[RsshubNamespaceOut]
    total: int
    page: int
    page_size: int
    categories: list[str]
    fetched_at: float
