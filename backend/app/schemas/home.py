from datetime import datetime

from pydantic import BaseModel

from app.schemas.task import TaskOut


class DataSourceStatus(BaseModel):
    module: str
    last_run_at: datetime | None
    last_status: str | None
    total_tasks: int


class HomeSummary(BaseModel):
    total_tasks: int
    success_count: int
    failed_count: int
    running_count: int


class HomeResponse(BaseModel):
    data_sources: list[DataSourceStatus]
    recent_tasks: list[TaskOut]
    summary: HomeSummary
