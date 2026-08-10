from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CookieStatus(BaseModel):
    has_token: bool
    preview: str | None
    updated_at: str | None


class CookieIn(BaseModel):
    cookies: str = Field(..., min_length=10, description="夸克网盘网页版登录态 Cookie（浏览器 F12 复制）")


class QuarkAccount(BaseModel):
    nickname: str = ""
    vip_member: bool = False
    capacity: int = 0
    used: int = 0


class SourceInfo(BaseModel):
    source_id: str
    source_name: str
    supports_search: bool
    supports_save: bool
    search_providers: list[str] = []


class ResourceItem(BaseModel):
    """跨资源源统一的搜索结果条目。"""

    source: str
    title: str
    url: str
    share_id: str
    share_pwd: str = ""
    category: str = ""
    snippet: str = ""


class SearchResult(BaseModel):
    source: str
    provider: str = ""
    items: list[ResourceItem]
    total: int
    page: int
    page_size: int
    message: str = ""


class SaveIn(BaseModel):
    source: str = "quark"
    share_url: str = Field(..., min_length=1, description="网盘分享链接，如 https://pan.quark.cn/s/xxxx")
    share_pwd: str = ""
    target_dir: str = ""  # 空 = 转存到根目录


class LinkCheckItem(BaseModel):
    """单条待校验链接（url 与 share_id 二选一即可）。"""

    url: str = ""
    share_id: str = ""
    pwd: str = ""


class LinkCheckIn(BaseModel):
    links: list[LinkCheckItem] = Field(..., max_length=20, description="单次最多校验 20 个链接")


class LinkCheckOut(BaseModel):
    """链接有效性校验结果。

    status 取值：
      valid      - 链接有效（含文件）
      needs_pwd  - 链接有效但需要提取码
      invalid    - 链接已失效/不存在/无可转存文件
      unknown    - 无法校验（未配置夸克 Cookie 或接口异常）
    """

    url: str = ""
    share_id: str
    status: str
    message: str = ""
    file_count: int = 0


class SaveTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    resource_title: str
    share_url: str
    share_id: str
    share_pwd: str
    target_dir: str
    status: str
    message: str
    created_at: datetime


class SaveTaskPage(BaseModel):
    items: list[SaveTaskOut]
    total: int
    page: int
    page_size: int
