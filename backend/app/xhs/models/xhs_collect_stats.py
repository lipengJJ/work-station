from __future__ import annotations

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class XhsCollectStats(Base):
    """
    一次采集任务的过滤/处理明细。单独开一张新表而不是往 XhsTaskExtra 加列——那张表
    是已经在生产库里存在的旧表，create_all() 不会给已存在的表补列，加列需要手工迁移；
    新表不受这个限制，create_all() 会直接建好。

    candidate_count：search_some_note 搜到的候选笔记总数（还没抓详情）。
    fetch_failed_count：spider_note/缓存都失败、详情抓取不到跳过的数量。
    low_content_count：规则判定为"求攻略/求推荐"之类没有实质内容、被过滤掉不采集的数量。
    collected_count：最终真正采集入库的笔记数（= candidate_count - fetch_failed_count
        - low_content_count，三者应该能对上，便于核对）。
    structured_ok_count / structured_failed_count：笔记结构化预处理（note_structurer）
        成功/失败的数量，仅统计 collected_count 这部分笔记。
    """

    __tablename__ = "xhs_collect_stats"

    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    fetch_failed_count: Mapped[int] = mapped_column(Integer, default=0)
    low_content_count: Mapped[int] = mapped_column(Integer, default=0)
    collected_count: Mapped[int] = mapped_column(Integer, default=0)
    structured_ok_count: Mapped[int] = mapped_column(Integer, default=0)
    structured_failed_count: Mapped[int] = mapped_column(Integer, default=0)
