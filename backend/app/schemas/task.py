from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    module: str
    task_type: str
    status: str
    params: dict
    result_summary: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class TaskCenterResponse(BaseModel):
    running: list[TaskOut]
    completed: list[TaskOut]
    failed: list[TaskOut]
