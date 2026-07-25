"""
Phase 2 骨架阶段的占位响应：统一返回 "开发中"，前端据此渲染 Empty 状态而不是报错。
Phase 3 接入 stock-report/collector 和 Spider_XHS/webapp 的真实逻辑时，
按需把某个 module 下的具体路径从这里挪到 stock.py / xhs.py / datacenter.py 里实现真实版本。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user


def placeholder_router(prefix: str, tag: str, sections: dict[str, str]) -> APIRouter:
    """
    sections: {path_segment: 中文名}，为每个子页面生成一个 GET /{prefix}/{path_segment} 占位接口
    """
    router = APIRouter(prefix=prefix, tags=[tag])
    for path, label in sections.items():
        def _make_handler(label: str):
            def _handler(_=Depends(get_current_user)):
                return {"status": "coming_soon", "label": label, "message": f"{label}功能待 Phase 3 接入"}
            return _handler

        router.add_api_route(f"/{path}", _make_handler(label), methods=["GET"])
    return router


stock_router = placeholder_router(
    "/api/stock",
    "stock",
    {
        "watchlist": "自选股",
        "quotes": "行情与K线",
        "fundamentals": "基本面",
        "indicators": "技术指标",
        "options": "期权分析",
        "ai-report": "AI研究报告",
    },
)

xhs_router = placeholder_router(
    "/api/xhs",
    "xhs",
    {
        "notes": "笔记管理",
        "comments": "评论管理",
        "keyword-stats": "关键词统计",
        "sentiment": "情绪分析",
        "brand-ranking": "酒店/品牌提及排名",
        "collect-tasks": "采集任务",
    },
)

datacenter_router = placeholder_router(
    "/api/datacenter",
    "datacenter",
    {
        "upload": "Excel/CSV上传",
        "sources": "数据源管理",
        "exports": "导出记录",
    },
)
