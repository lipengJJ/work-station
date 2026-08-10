"""
资源源注册表：所有已注册的 ResourceSource 都在这里登记，
controller 通过 source_id 查找，新增源无需改动 controller。
"""
from __future__ import annotations

from app.resource.services.base import ResourceSource, ResourceSourceError


class ResourceSourceRegistry:
    def __init__(self) -> None:
        self._sources: dict[str, ResourceSource] = {}

    def register(self, source: ResourceSource) -> None:
        if not source.source_id:
            raise ResourceSourceError("资源源缺少 source_id")
        self._sources[source.source_id] = source

    def get(self, source_id: str) -> ResourceSource:
        source = self._sources.get(source_id)
        if not source:
            raise ResourceSourceError(f"未知资源源: {source_id}")
        return source

    def list(self) -> list[ResourceSource]:
        return list(self._sources.values())


registry = ResourceSourceRegistry()
