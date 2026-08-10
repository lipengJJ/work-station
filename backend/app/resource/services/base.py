"""
资源源抽象层：可扩展架构的核心。

新增一个资源源（百度网盘 / 阿里云盘 / ...）的步骤：
  1. 实现 ResourceSource 子类（search / save 两个能力点，按需覆写）
  2. 在 app/resource/services/registry.py 里注册一行
  3. 前端 /api/resource/sources 会自动多出一个可选项，无需改 controller

搜什么、怎么搜（Bing/DDG/自定义 API）由源内部用 SearchProvider 策略组合，
转存走各网盘官方接口（QuarkClient），与抽象层解耦。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.resource.schemas.resource import ResourceItem, SearchResult

if TYPE_CHECKING:
    from app.resource.models import ResourceSaveTask


class ResourceSourceError(Exception):
    """资源源业务错误（参数不合法 / 外部接口失败 / cookie 失效等），message 可直接展示给用户。"""


class ResourceSource(ABC):
    """资源源抽象基类。"""

    source_id: str = ""
    source_name: str = ""
    supports_search: bool = True
    supports_save: bool = False
    search_providers: list[str] = []

    @abstractmethod
    def search(self, keyword: str, category: str, page: int, page_size: int) -> SearchResult:
        """在源内搜索资源，返回标准化条目列表。category 为空表示不区分类型。"""

    def save(self, share_url: str, share_pwd: str, target_dir: str, db: Session) -> ResourceSaveTask:
        """把分享链接转存到用户网盘并落库转存记录。默认不支持转存。"""
        raise ResourceSourceError(f"资源源 {self.source_id} 暂不支持转存")
