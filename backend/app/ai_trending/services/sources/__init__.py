"""热点源注册表实例化：注册 7 个源实例（HF 一个类两种 mode）。

新增数据源只需在此追加一行（并到 scheduler_jobs.py 加 cron 配置），
controller / collector / 前端来源 Tab 自动生效。
"""
from __future__ import annotations

from app.ai_trending.services.base import registry
from app.ai_trending.services.sources.arxiv import ArxivSource
from app.ai_trending.services.sources.github import GitHubSource
from app.ai_trending.services.sources.hf import HuggingFaceSource
from app.ai_trending.services.sources.hn import HackerNewsSource
from app.ai_trending.services.sources.infoq import InfoQSource
from app.ai_trending.services.sources.kr36 import Kr36Source

_SOURCES = [
    HackerNewsSource(),
    GitHubSource(),
    ArxivSource(),
    HuggingFaceSource(mode="models"),
    HuggingFaceSource(mode="papers"),
    InfoQSource(),
    Kr36Source(),
]

for _source in _SOURCES:
    registry.register(_source)

__all__ = ["registry"]
