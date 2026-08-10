from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class XhsTaskPendingOp(Base):
    """
    记录一个采集任务当前排队/正在执行的操作类型（'collect' 全新采集 | 'incremental'
    增量采集），只在任务处于 pending/running 期间存在，任务结束（成功或失败）后这行
    会被删除。

    存在的意义：requeue_pending_tasks() 在进程重启后要把遗留的 pending/running 任务
    重新排队，但"全新采集"和"增量采集"跑的是不同函数（_run_task 会用 task.params 里
    的原始关键词从头搜索，覆盖掉已有数据；_run_incremental_task 是在现有笔记基础上追加
    新的）——不区分的话，重启中途正在增量采集的任务会被错误地当成全新采集重跑，
    把已经积累的笔记数据整个冲掉。单独开一张新表而不是往 Task/XhsTaskExtra 加列——
    那两张都是已经在生产库里存在的旧表，create_all() 不会给已存在的表补列。
    """

    __tablename__ = "xhs_task_pending_op"

    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    op_type: Mapped[str] = mapped_column(String(16))  # collect | incremental
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
