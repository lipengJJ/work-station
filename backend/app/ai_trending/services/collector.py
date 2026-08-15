"""统一 Collector：抓取 → 重试 → 去重 upsert → 状态更新 → 保留策略。

- 每个源独立执行，任一源失败不阻塞其他源；
- 跨源同 URL 只保留热度最高的一条（url_hash 去重 + 热度更高覆盖）；
- 失败重试：初始 + 2 次重试（5s / 15s 退避），最终失败记入来源健康状态。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.ai_trending.models import AiTrendingItem, AiTrendingSourceStatus
from app.ai_trending.services.base import (
    RawItem,
    TrendingSource,
    TrendingSourceError,
    url_hash,
)
from app.ai_trending.services.sources import registry  # noqa: F401  确保源已注册
from app.core.database import SessionLocal

RETRY_DELAYS = (5, 15)  # 初始失败后重试 2 次的退避秒数
RETENTION_DAYS = 7  # 超过 7 天清理
MAX_ITEMS = 2000  # 最多保留 2000 条


class Collector:
    """热点聚合执行器：定时任务 / 手动刷新共用同一入口。"""

    # ------------------------------------------------------------ 入口 ----
    def run_source(self, source_id: str, db: Session | None = None) -> dict[str, Any]:
        """抓取单个源并入库。db 为空时自开自关一个会话（调度器线程场景）。"""
        if db is None:
            with SessionLocal() as local_db:
                return self._run_source_inner(source_id, local_db)
        return self._run_source_inner(source_id, db)

    def run_all(self, db: Session | None = None) -> dict[str, dict[str, Any]]:
        """抓取全部源（串行），返回 {source_id: result}。"""
        results: dict[str, dict[str, Any]] = {}
        for source in registry.list():
            results[source.source_id] = self.run_source(source.source_id, db=db)
        return results

    # ------------------------------------------------------------ 内部 ----
    def _run_source_inner(self, source_id: str, db: Session) -> dict[str, Any]:
        source = registry.get(source_id)  # 未知源抛 TrendingSourceError
        result: dict[str, Any] = {
            "source_id": source_id,
            "added": 0,
            "updated": 0,
            "skipped": 0,
            "status": "success",
            "error": "",
        }
        try:
            items = self._fetch_with_retry(source)
            counts = self._upsert_items(db, items)
            result.update(counts)
            self._update_status(db, source_id, ok=True, error="", fetched=len(items))
            logger.info(
                f"ai_trending 源 {source_id} 抓取成功: "
                f"新增 {result['added']} / 更新 {result['updated']} / 跳过 {result['skipped']} / 共 {len(items)} 条"
            )
        except TrendingSourceError as exc:
            result["status"] = "failed"
            result["error"] = str(exc)
            self._update_status(db, source_id, ok=False, error=str(exc), fetched=0)
            logger.warning(f"ai_trending 源 {source_id} 抓取失败: {exc}")
        except Exception as exc:  # noqa: BLE001  兜底：任何异常都不阻塞其他源
            logger.exception(f"ai_trending 源 {source_id} 发生未预期异常")
            result["status"] = "failed"
            result["error"] = str(exc)
            self._update_status(db, source_id, ok=False, error=str(exc), fetched=0)
        return result

    def _fetch_with_retry(self, source: TrendingSource) -> list[RawItem]:
        """最多 3 次尝试（初始 + 2 次重试，5s / 15s 退避）；全失败抛 TrendingSourceError。"""
        last_error = ""
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                items = source.fetch()
                return items or []
            except TrendingSourceError as exc:
                last_error = str(exc)
            except Exception as exc:  # noqa: BLE001  解析层意外异常同样重试
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < len(RETRY_DELAYS):
                delay = RETRY_DELAYS[attempt]
                logger.warning(
                    f"源 {source.source_id} 第 {attempt + 1} 次抓取失败: {last_error}，{delay}s 后重试"
                )
                time.sleep(delay)
        raise TrendingSourceError(f"源 {source.source_id} 连续抓取失败: {last_error}")

    def _upsert_items(self, db: Session, items: list[RawItem]) -> dict[str, int]:
        """逐条 url_hash 查重入库：
        - 不存在 → INSERT（added+1）
        - 已存在且新 heat_score 更高 → 覆盖（source/title/url/summary/heat_score/category/tags/heat_meta/published_at，updated+1）
        - 已存在且热度不更高 → 忽略（skipped+1）
        """
        added = updated = skipped = 0
        now = datetime.now(timezone.utc)
        for item in items:
            h = url_hash(item.url)
            if not h:
                skipped += 1
                continue
            existing = (
                db.query(AiTrendingItem)
                .filter(AiTrendingItem.url_hash == h)
                .first()
            )
            if existing is None:
                db.add(
                    AiTrendingItem(
                        source=item.source[:32],
                        title=(item.title or "")[:512],
                        url=(item.url or "")[:1024],
                        url_hash=h,
                        summary=item.summary or "",
                        heat_score=item.heat_score,
                        category=item.category or "news",
                        tags=json.dumps(item.tags, ensure_ascii=False),
                        heat_meta=json.dumps(item.heat_meta, ensure_ascii=False),
                        published_at=item.published_at or now,
                        fetched_at=now,
                        created_at=now,
                    )
                )
                added += 1
            elif item.heat_score > (existing.heat_score or 0):
                existing.source = item.source[:32]
                existing.title = (item.title or "")[:512]
                existing.url = (item.url or "")[:1024]
                existing.summary = item.summary or ""
                existing.heat_score = item.heat_score
                existing.category = item.category or "news"
                existing.tags = json.dumps(item.tags, ensure_ascii=False)
                existing.heat_meta = json.dumps(item.heat_meta, ensure_ascii=False)
                existing.published_at = item.published_at or existing.published_at
                existing.fetched_at = now
                updated += 1
            else:
                skipped += 1
        db.commit()
        return {"added": added, "updated": updated, "skipped": skipped}

    def _update_status(
        self, db: Session, source_id: str, ok: bool, error: str, fetched: int
    ) -> None:
        """更新来源健康状态行（不存在则创建）。

        成功 → consecutive_failures 清零、last_status=success、last_success_at=now、total_fetched+=fetched；
        失败 → last_status=failed、consecutive_failures+=1，连续失败 >= 3 时 fail_count+=1。
        """
        status = db.get(AiTrendingSourceStatus, source_id)
        if status is None:
            source = registry.get(source_id)
            status = AiTrendingSourceStatus(
                source_id=source.source_id,
                source_name=source.source_name,
                category_type=source.category_type,
            )
            db.add(status)
        now = datetime.now(timezone.utc)
        status.last_fetched_at = now
        if ok:
            status.last_status = "success"
            status.last_error = ""
            status.consecutive_failures = 0
            status.last_success_at = now
            status.total_fetched = (status.total_fetched or 0) + fetched
        else:
            status.last_status = "failed"
            status.last_error = (error or "")[:500]
            status.consecutive_failures = (status.consecutive_failures or 0) + 1
            if status.consecutive_failures >= 3:
                status.fail_count = (status.fail_count or 0) + 1
        db.commit()

    # -------------------------------------------------------- 保留策略 ----
    def cleanup_old_items(self, db: Session | None = None) -> int:
        """保留策略：先删超过 7 天的条目，再删至最多 2000 条（按发布时间保留最新）。"""
        if db is None:
            with SessionLocal() as local_db:
                return self.cleanup_old_items(local_db)
        deleted = 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
        deleted += (
            db.query(AiTrendingItem)
            .filter(AiTrendingItem.published_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        total = db.query(AiTrendingItem).count()
        if total > MAX_ITEMS:
            excess = total - MAX_ITEMS
            old_ids = [
                row[0]
                for row in db.query(AiTrendingItem.id)
                .order_by(
                    AiTrendingItem.published_at.desc(), AiTrendingItem.id.desc()
                )
                .offset(MAX_ITEMS)
                .limit(excess)
                .all()
            ]
            if old_ids:
                deleted += (
                    db.query(AiTrendingItem)
                    .filter(AiTrendingItem.id.in_(old_ids))
                    .delete(synchronize_session=False)
                )
                db.commit()
        return deleted


collector = Collector()
