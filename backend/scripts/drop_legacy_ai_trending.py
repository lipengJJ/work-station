"""下线旧 ai_trending 模块遗留的数据库表（显式执行，不在任何 lifespan/启动流程里自动跑）。

热点数据本来就是滚动更新的（新的 hotlist 模块跑一次全量抓取就补满），旧表弃用不迁数据，
详见 doc/HOTLIST_INTEGRATION_DESIGN.md §2.1。这个脚本只是清理这几张不再被任何代码引用
的空壳表，跑不跑不影响功能，纯粹是数据库整洁。

用法：
    cd backend && .venv/bin/python scripts/drop_legacy_ai_trending.py          # 只打印将要删除的表 + 行数，不执行
    cd backend && .venv/bin/python scripts/drop_legacy_ai_trending.py --yes    # 真正执行 DROP TABLE
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 让 backend/ 进 sys.path，支持直接 python scripts/xxx.py 运行

from sqlalchemy import inspect, text  # noqa: E402

from app.core.database import engine  # noqa: E402

LEGACY_TABLES = [
    "ai_trending_items",
    "ai_trending_push_log",
    "ai_trending_push_config",
    "ai_trending_topic",
    "ai_trending_source_status",
    "ai_trending_topic_hit",
]


def main() -> None:
    execute = "--yes" in sys.argv[1:]

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    to_drop = [t for t in LEGACY_TABLES if t in existing_tables]

    if not to_drop:
        print("没有找到任何旧 ai_trending_* 表，无需清理。")
        return

    with engine.connect() as conn:
        for table in to_drop:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            print(f"  {table}: {count} 行")

    if not execute:
        print(f"\n以上 {len(to_drop)} 张表将被删除（dry-run，未执行）。加 --yes 参数真正执行。")
        return

    with engine.begin() as conn:
        for table in to_drop:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
            print(f"已删除: {table}")

    print(f"\n完成，共删除 {len(to_drop)} 张表。")


if __name__ == "__main__":
    main()
