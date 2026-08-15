from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.common.controllers import auth, chat, home, system, tasks_center
from app.core.config import get_settings
from app.core.database import init_db
from app.core.logging import setup_logging
from app.core.placeholder import datacenter_router, stock_router
from app.core.scheduler import shutdown_scheduler, start_scheduler

setup_logging()
from app.analysis.controllers import analyses as analyses_api
from app.ai_trending.controllers import trending as ai_trending_api
from app.resource.controllers import resource as resource_api
from app.skills.controllers import skills as skills_api
from app.skills.services import registry_service as skills_registry
from app.stock.controllers import fundamentals as fundamentals_api
from app.stock.controllers import market_overview as market_overview_api
from app.stock.controllers import stock as stock_api
from app.stock.controllers import strategy_ai as strategy_ai_api
from app.xhs.controllers import analysis as xhs_analysis_api
from app.xhs.controllers import collect_tasks as xhs_api
from app.xhs.controllers import notes as xhs_notes_api
from app.xhs.controllers import tracking as xhs_tracking_api
from app.xhs.services import tasks as xhs_tasks
from app.xhs.services import tracking as xhs_tracking

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # 配置自动恢复：容器重建/清卷后，从宿主机 bind mount 目录的 config.json 恢复 API 配置
    try:
        from app.core.database import SessionLocal
        from app.common.services.config_file import restore_config_from_file
        with SessionLocal() as _db:
            _restored = restore_config_from_file(_db)
            if _restored:
                logger.info(f"已从 config.json 恢复 {_restored} 条 API 配置")
    except Exception:
        pass
    start_scheduler()
    skills_registry.scan_on_startup()
    xhs_tasks.requeue_pending_tasks()
    xhs_tasks.start_worker()
    xhs_tracking.register_all_enabled_jobs()
    # AI 开发热点聚合：每源独立 cron job + 每日清理 job
    from app.ai_trending.services import scheduler_jobs as ai_trending_scheduler_jobs

    ai_trending_scheduler_jobs.register_all_enabled_jobs()
    # 签名脚本缺失检测：clone 仓库后 backend/static 没有逆向签名脚本时给出明确提示
    # （不影响启动，评论等页面级功能正常；搜索/详情接口首次使用时会再次报错）
    try:
        from app.xhs.services.utils.xhs_util import missing_signature_files
        _missing = missing_signature_files()
        if _missing:
            logger.warning(
                f"检测到小红书签名脚本缺失（{len(_missing)} 个: {', '.join(_missing[:3])}{'…' if len(_missing) > 3 else ''}）。"
                "部署须知：该脚本为平台逆向产物不进版本库，请放入 backend/static/ 后重启，否则 xhs 搜索/详情接口不可用（见 README）"
            )
    except Exception:
        pass
    try:
        yield
    finally:
        shutdown_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_title, lifespan=lifespan)

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok", "service": "workbench-backend"}

    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(home.router)
    app.include_router(tasks_center.router)
    app.include_router(system.router)
    app.include_router(skills_api.router)
    app.include_router(analyses_api.router)
    app.include_router(stock_api.router)
    app.include_router(fundamentals_api.router)
    app.include_router(market_overview_api.router)
    app.include_router(strategy_ai_api.router)
    app.include_router(stock_router)
    app.include_router(xhs_api.router)
    app.include_router(xhs_notes_api.router)
    app.include_router(xhs_analysis_api.router)
    app.include_router(xhs_tracking_api.router)
    app.include_router(resource_api.router)
    app.include_router(ai_trending_api.router)
    app.include_router(datacenter_router)

    return app


app = create_app()
