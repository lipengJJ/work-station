"""
种子脚本：初始化管理员账号（幂等，已存在则跳过）。
用法：cd backend && python seed.py
"""
from app.core.database import SessionLocal, init_db
from app.core.security import hash_password
from app.common.models import User

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"  # 仅骨架阶段本地验证用，Phase 3 前务必修改/加强


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.username == ADMIN_USERNAME).first():
            db.add(User(username=ADMIN_USERNAME, hashed_password=hash_password(ADMIN_PASSWORD), role="admin"))
            print(f"created admin user: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")

        # 不再创建示例任务（mock 数据会造成首页看板出现"假任务/残留任务"的困扰），
        # 全新部署后首页统计为 0，一切以真实采集为准。

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
