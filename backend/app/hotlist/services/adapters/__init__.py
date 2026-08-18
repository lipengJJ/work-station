"""adapter 注册表实例化：import 本包即完成全部 adapter 注册。

新增 adapter 只需新写一个模块（内部调用 base.register()）并在此追加一行 import，
HotSource.adapter 字段按 adapter_key 查表即可接入，controller / crawl_service 不用改。
"""
from __future__ import annotations

from app.hotlist.services.adapters import arxiv  # noqa: F401  import 触发 register()
from app.hotlist.services.adapters import github  # noqa: F401
from app.hotlist.services.adapters import hackernews  # noqa: F401
from app.hotlist.services.adapters import huggingface  # noqa: F401
from app.hotlist.services.adapters import newsnow  # noqa: F401
from app.hotlist.services.adapters import rss  # noqa: F401
from app.hotlist.services.adapters.base import get, registry

__all__ = ["registry", "get"]
