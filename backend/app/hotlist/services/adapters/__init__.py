"""adapter 注册表实例化：只支持 RSS/Atom 一种源类型（见 source_service.create_source
的 adapter 校验），别的协议不接了——之前接过的 NewsNow/HN/GitHub/HuggingFace/arXiv
适配器已下掉，维护成本不划算，实际也没人在用。
"""
from __future__ import annotations

# import 触发 register()
from app.hotlist.services.adapters import rss  # noqa: F401
from app.hotlist.services.adapters.base import get, registry

__all__ = ["registry", "get"]
