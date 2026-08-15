"""
ApiConfig 的"文件镜像"：数据库仍是权威存储，但每次写操作后同步导出一份
可读的 config.json（与 workbench.db 同目录），并在启动时自动恢复——

场景：容器重启/重建后配置自动加载；甚至 docker compose down -v 清掉卷，
只要宿主机目录（bind mount）还在，重启后配置自动恢复。
"""
from __future__ import annotations

import json
import os

from sqlalchemy.orm import Session

from app.common.models import ApiConfig

_CONFIG_FILE_NAME = "config.json"


def _config_dir() -> str:
    """与数据库文件同目录（docker: /app/data，本地: backend/）"""
    from sqlalchemy import create_engine
    from app.core.database import engine
    url = str(engine.url)
    if url.startswith("sqlite:///"):
        db_path = url[len("sqlite:///"):]
        return os.path.dirname(os.path.abspath(db_path))
    return os.path.dirname(os.path.abspath(__file__))


def config_file_path() -> str:
    return os.path.join(_config_dir(), _CONFIG_FILE_NAME)


def sync_config_to_file(db: Session) -> None:
    """把 api_configs 表全量导出为 config.json（可读、可备份、可迁移）"""
    try:
        rows = db.query(ApiConfig).all()
        payload = {
            r.name: {"value": r.value, "description": r.description}
            for r in rows
        }
        path = config_file_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        # 导出失败不影响主流程（数据库仍是权威）
        pass


def restore_config_from_file(db: Session) -> int:
    """表为空且 config.json 存在时，从文件恢复配置。返回恢复条数。"""
    try:
        if db.query(ApiConfig).count() > 0:
            return 0
        path = config_file_path()
        if not os.path.exists(path):
            return 0
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        restored = 0
        for name, item in payload.items():
            if not db.query(ApiConfig).filter(ApiConfig.name == name).first():
                db.add(ApiConfig(
                    name=name,
                    value=item.get("value", ""),
                    description=item.get("description"),
                ))
                restored += 1
        db.commit()
        return restored
    except Exception:
        return 0
