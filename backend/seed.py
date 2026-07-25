"""
一次性种子数据脚本：管理员账号 + 几条示例任务，供骨架验证用。
用法：cd backend && python seed.py
"""
from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal, init_db
from app.core.security import hash_password
from app.models import Task, User

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
            sample_tasks = [
                Task(
                    module="stock", task_type="analyze", status="success",
                    params={"tickers": ["AAPL", "QQQ"]},
                    result_summary="分析完成，写入 2 份报告",
                    created_at=now - timedelta(hours=2), started_at=now - timedelta(hours=2),
                    finished_at=now - timedelta(hours=1, minutes=55),
                ),
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
                Task(
                    module="stock", task_type="analyze", status="pending",
                    params={"tickers": ["NVDA", "TSLA"]},
                    created_at=now - timedelta(minutes=1),
                ),
            ]
            db.add_all(sample_tasks)
            print(f"created {len(sample_tasks)} sample tasks")

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
