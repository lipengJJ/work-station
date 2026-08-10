"""
loguru 落盘配置：默认只往 stderr 打，进程重启/容器重启后就什么都没了，没法回头排查
"AI 分析超时""任务失败"这类问题。这里加一个按大小轮转的文件 sink，系统设置里的
日志查看页面直接读这个文件的尾部。
"""
from __future__ import annotations

import sys

from loguru import logger

from app.core.config import BASE_DIR

LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "app.log"


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add(
        LOG_FILE,
        level="INFO",
        rotation="20 MB",
        retention=5,
        encoding="utf-8",
        # enqueue=True 把实际写盘放到后台线程处理，xhs 采集 worker 和请求处理线程
        # 并发往同一个文件写日志时不会互相破坏内容
        enqueue=True,
    )
