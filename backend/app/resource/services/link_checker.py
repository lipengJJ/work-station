"""
夸克分享链接有效性校验服务。

- 走 QuarkClient.check_share（shareinfo 接口），需要夸克 Cookie；
- 未配置 Cookie 时降级为 unknown（无法校验），不影响搜索/展示；
- 内存缓存（默认 1 小时），同一 share_id+pwd 不重复请求，避免触发夸克风控；
- 并发上限 3，单次批量不超过 20。
"""
from __future__ import annotations

import concurrent.futures
import threading
import time

from loguru import logger
from sqlalchemy.orm import Session

from app.resource.services import cookie_store
from app.resource.services.base import ResourceSourceError
from app.resource.services.quark_client import QuarkClient
from app.resource.services.search_providers import parse_share_id

CACHE_TTL_SECONDS = 3600
CHECK_CONCURRENCY = 3

_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()


def _cache_key(share_id: str, pwd: str) -> str:
    return f"{share_id}|{pwd}"


def _from_cache(share_id: str, pwd: str, now: float) -> dict | None:
    with _cache_lock:
        entry = _cache.get(_cache_key(share_id, pwd))
    if entry and now - entry["checked_at"] < CACHE_TTL_SECONDS:
        return entry
    return None


def _to_cache(share_id: str, pwd: str, entry: dict) -> None:
    with _cache_lock:
        _cache[_cache_key(share_id, pwd)] = entry


def check_links(db: Session, links: list[dict]) -> list[dict]:
    """
    批量校验链接。links: [{"url"?, "share_id"?, "pwd"?}, ...]
    返回按输入顺序的 [{url, share_id, status, message, file_count}]。
    """
    now = time.time()
    results: list[dict] = []
    pending: list[tuple[str, str, str, dict]] = []  # (share_id, pwd, url, item)

    for item in links:
        share_id = parse_share_id(item.get("url") or "") or (item.get("share_id") or "").strip()
        pwd = (item.get("pwd") or "").strip()
        url = (item.get("url") or "").strip() or f"https://pan.quark.cn/s/{share_id}"
        if not share_id:
            results.append(
                {"url": url, "share_id": share_id, "status": "unknown", "message": "无效的分享链接", "file_count": 0}
            )
            continue
        cached = _from_cache(share_id, pwd, now)
        if cached:
            results.append({**cached, "url": url})
        else:
            pending.append((share_id, pwd, url, item))

    if pending:
        cookies_str = cookie_store.get_cookies_str(db)
        if not cookies_str:
            for share_id, _pwd, url, _item in pending:
                results.append(
                    {
                        "url": url,
                        "share_id": share_id,
                        "status": "unknown",
                        "message": "未配置夸克 Cookie，无法校验链接有效性",
                        "file_count": 0,
                    }
                )
        else:
            client = QuarkClient(cookies_str)
            fetched: dict[str, dict] = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=CHECK_CONCURRENCY) as pool:
                futures = {pool.submit(client.check_share, sid, pwd): (sid, pwd, url) for sid, pwd, url, _ in pending}
                for fut in concurrent.futures.as_completed(futures):
                    sid, pwd, url = futures[fut]
                    try:
                        status, message, file_count = fut.result()
                    except Exception as exc:  # noqa: BLE001 单条失败降级 unknown
                        status, message, file_count = "unknown", f"校验异常：{exc}", 0
                        logger.warning(f"resource.check_links 校验失败 share_id={sid}: {exc}")
                    entry = {"share_id": sid, "status": status, "message": message, "file_count": file_count, "checked_at": now}
                    _to_cache(sid, pwd, entry)
                    fetched[(sid, pwd)] = entry
            for share_id, pwd, url, _item in pending:
                entry = fetched.get((share_id, pwd))
                if entry:
                    results.append({**entry, "url": url})

    return results


def invalidate_cache(share_id: str | None = None, pwd: str = "") -> None:
    """清空指定（或全部）链接的校验缓存。"""
    with _cache_lock:
        if share_id is None:
            _cache.clear()
            return
        _cache.pop(_cache_key(share_id, pwd), None)
