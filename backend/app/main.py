from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, home, system, tasks_center
from app.api import xhs as xhs_api
from app.api.placeholder import datacenter_router, stock_router, xhs_router
from app.core.config import get_settings
from app.core.database import init_db
from app.core.scheduler import shutdown_scheduler, start_scheduler
from app.xhs import tasks as xhs_tasks

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    xhs_tasks.requeue_pending_tasks()
    xhs_tasks.start_worker()
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
    app.include_router(home.router)
    app.include_router(tasks_center.router)
    app.include_router(system.router)
    app.include_router(stock_router)
    app.include_router(xhs_api.router)
    app.include_router(xhs_router)
    app.include_router(datacenter_router)

    return app


app = create_app()
