"""
一次性种子数据脚本：管理员账号 + 几条示例任务，供骨架验证用。
用法：cd backend && python seed.py
"""
from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal, init_db
from app.core.security import hash_password
from app.common.models import Task, User

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"  # 仅骨架阶段本地验证用，Phase 3 前务必修改/加强


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.username == ADMIN_USERNAME).first():
            db.add(User(username=ADMIN_USERNAME, hashed_password=hash_password(ADMIN_PASSWORD), role="admin"))
            print(f"created admin user: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")

        if db.query(Task).count() == 0:
            now = datetime.now(timezone.utc)
            # 示例任务只保留 xhs 的（stock 模块尚未接入真实任务，不再造 mock 数据，
            # 避免首页看板出现"stock 残留任务"的假象）
            sample_tasks = [
                Task(
                    module="xhs", task_type="xhs_search", status="running",
                    params={"keyword": "普吉岛酒店推荐", "require_num": 20},
                    created_at=now - timedelta(minutes=5), started_at=now - timedelta(minutes=5),
                ),
                Task(
                    module="xhs", task_type="xhs_search", status="failed",
                    params={"keyword": "曼谷咖啡店"},
                    result_summary="访问频繁，请稍后再试",
                    created_at=now - timedelta(days=1), started_at=now - timedelta(days=1),
                    finished_at=now - timedelta(days=1) + timedelta(minutes=2),
                ),
            ]
            db.add_all(sample_tasks)
            print(f"created {len(sample_tasks)} sample tasks")

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
