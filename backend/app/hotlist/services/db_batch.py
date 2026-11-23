"""热榜共享的批量删除辅助：分批 DELETE 以避开 SQLite 999 参数上限。

crawl_service（保留策略清理）与 source_service（级联删源）都按同一方式批量删除，
抽到独立模块避免互相 import 另一个服务的私有成员（Google 规范：不跨模块访问
下划线私有成员，共享能力下沉到公共模块）。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

# 批量删除时的分批大小，留足余量避开 SQLite 999 参数上限
SQLITE_BATCH_SIZE = 500


def delete_in_batches(db: Session, model, column, ids: list) -> int:
    """按 SQLITE_BATCH_SIZE 分批 DELETE ... WHERE column IN (...)。

    分批可避开 SQLite 的 999 绑定参数上限，避免一次性删除大 id 集合时报错。
    返回删除总行数。
    """
    deleted = 0
    for i in range(0, len(ids), SQLITE_BATCH_SIZE):
        chunk = ids[i : i + SQLITE_BATCH_SIZE]
        deleted += (
            db.query(model)
            .filter(column.in_(chunk))
            .delete(synchronize_session=False)
        )
    return deleted