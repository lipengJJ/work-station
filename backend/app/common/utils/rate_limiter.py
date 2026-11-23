"""进程内限频器：单进程部署下用「锁 + 上次时间戳」做简单冷却限频。

适用于「手动刷新/手动生成」这类只应低频触发的操作；仅进程内有效，
多进程部署需要换成 Redis 之类的共享存储才能全局生效。
"""
from __future__ import annotations

import threading
import time


class RateLimiter:
    """线程安全的冷却限频器。

    用法：
        limiter = RateLimiter(cooldown_seconds=600)
        remaining = limiter.check_and_mark()
        if remaining > 0:
            # 仍在冷却中，remaining 为还需等待的秒数
            ...
    """

    def __init__(self, cooldown_seconds: float) -> None:
        self._cooldown = cooldown_seconds
        self._lock = threading.Lock()
        self._last: float | None = None

    def check_and_mark(self) -> float:
        """原子地「检查冷却 + 记录本次触发」。

        返回距下次可触发还需等待的秒数：0 表示本次已放行并记录；>0 表示仍在
        冷却中，调用方据此决定拒绝或等待。
        """
        with self._lock:
            now = time.time()
            if self._last is not None:
                remaining = self._cooldown - (now - self._last)
                if remaining > 0:
                    return remaining
            self._last = now
            return 0.0