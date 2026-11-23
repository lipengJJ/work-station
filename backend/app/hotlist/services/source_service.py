"""源字典的种子数据与 CRUD。

seed_default_sources() 在 main.py lifespan 里调用，幂等：已存在的 id 跳过，
不覆盖用户在前端改过的 name/cron/enabled 等字段——这样重启不会把用户的改动冲掉。
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.hotlist.models import (
    HotCrawlSourceStatus,
    HotItem,
    HotItemContent,
    HotItemEmbedding,
    HotRankHistory,
    HotReportCandidate,
    HotSemanticHit,
    HotSource,
    HotSourceGroup,
    HotTopicSource,
)
from app.hotlist.services.db_batch import SQLITE_BATCH_SIZE, delete_in_batches

if TYPE_CHECKING:
    from app.hotlist.schemas.source_group import (
        SourceGroupIn,
        SourceGroupUpdateIn,
    )

BOOTSTRAP_DONE_KEY = "hotlist_defaults_bootstrapped"
"""ApiConfig 里的一次性开关：置位后 seed_default_groups/seed_default_sources
直接跳过。内置分组（中文热榜/技术社区）现在允许被删除（含级联删除组内源），
如果这两个函数继续按「已存在的 name/id 跳过、否则新建」的老逻辑每次启动都跑，
用户删完重启一次就会被原样种回来——删除必须是真正的删除，不是每次重启都撤销。
只在数据库第一次跑起来时播种一次，之后不管用户删没删都不再插手。"""


def seed_default_groups(db: Session | None = None) -> int:
    """幂等：确保「中文热榜」「技术社区」两个内置分组存在，返回新建数。

    main.py lifespan 里在 seed_default_sources() 之前调用（T03 接上）。
    已存在的分组不覆盖（不冲掉用户改过的 name/description/color）。
    只在 BOOTSTRAP_DONE_KEY 未置位时跑（见上方说明）。
    """
    if db is None:
        with SessionLocal() as local_db:
            return seed_default_groups(local_db)
    from app.common.services.gemini_config import get_config_value

    if get_config_value(db, BOOTSTRAP_DONE_KEY):
        return 0
    now = datetime.now(timezone.utc)
    defaults = [
        ("中文热榜", "中文热点资讯 RSS 源", "#ff4d4f", 0),
        ("技术社区", "技术资讯 RSS 源", "#1677ff", 1),
    ]
    existing = {g.name for g in db.query(HotSourceGroup).all()}
    created = 0
    for name, description, color, sort_order in defaults:
        if name in existing:
            continue
        db.add(
            HotSourceGroup(
                name=name,
                description=description,
                color=color,
                sort_order=sort_order,
                is_builtin=True,
                created_at=now,
                updated_at=now,
            )
        )
        created += 1
    if created:
        db.commit()
    return created


# ------------------------------------------------------------ 分组管理 ----

def list_groups(db: Session) -> list[HotSourceGroup]:
    """全部分组，按 sort_order, id 排序。"""
    return (
        db.query(HotSourceGroup)
        .order_by(HotSourceGroup.sort_order.asc(), HotSourceGroup.id.asc())
        .all()
    )


def get_group(db: Session, group_id: int) -> HotSourceGroup | None:
    return db.get(HotSourceGroup, group_id)


def source_count_for_group(db: Session, group_id: int) -> int:
    """组内源数（NULL group_id 不计入任何组）。"""
    return db.query(HotSource).filter(HotSource.group_id == group_id).count()


def create_group(db: Session, data: SourceGroupIn) -> HotSourceGroup:
    """新建分组。name 唯一冲突抛 ValueError。"""
    name = (data.name or "").strip()
    if not name:
        raise ValueError("分组名不能为空")
    if (
        db.query(HotSourceGroup)
        .filter(HotSourceGroup.name == name)
        .first()
    ) is not None:
        raise ValueError(f"分组名已存在: {name}")
    now = datetime.now(timezone.utc)
    group = HotSourceGroup(
        name=name,
        description=data.description or "",
        color=data.color or "",
        sort_order=data.sort_order or 0,
        crawl_enabled=bool(data.crawl_enabled),
        is_builtin=False,
        created_at=now,
        updated_at=now,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def update_group(
    db: Session,
    group_id: int,
    data: SourceGroupUpdateIn,
) -> HotSourceGroup:
    """更新分组 name/description/color/sort_order。name 冲突抛 ValueError。"""
    group = db.get(HotSourceGroup, group_id)
    if group is None:
        raise ValueError("分组不存在")
    updates = data.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] is not None:
        new_name = updates["name"].strip()
        if not new_name:
            raise ValueError("分组名不能为空")
        dup = (
            db.query(HotSourceGroup)
            .filter(
                HotSourceGroup.name == new_name,
                HotSourceGroup.id != group_id,
            )
            .first()
        )
        if dup is not None:
            raise ValueError(f"分组名已存在: {new_name}")
        updates["name"] = new_name
    for key, value in updates.items():
        if value is not None:
            setattr(group, key, value)
    group.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(group)
    return group


def _sources_with_topic_link(db: Session, source_ids: list[str]) -> set[str]:
    """source_ids 里被任意主题引用过的子集（不管 HotTopicSource.enabled 是不是
    True——哪怕主题里暂时关掉了这个源，关联关系还在，删源前必须先去主题里解除
    关联，否则主题重新开启这个源时会指向一个已经不存在的源）。"""
    if not source_ids:
        return set()
    linked: set[str] = set()
    for i in range(0, len(source_ids), SQLITE_BATCH_SIZE):
        chunk = source_ids[i : i + SQLITE_BATCH_SIZE]
        linked |= {
            row[0]
            for row in db.query(HotTopicSource.source_id)
            .filter(HotTopicSource.source_id.in_(chunk))
            .distinct()
            .all()
        }
    return linked


def delete_group(db: Session, group_id: int) -> dict:
    """删除分组：连组内的源一起删，并级联清掉这些源抓到的全部新闻数据。

    不再保护内置分组（中文热榜/技术社区）不让删——播种改成只在首次启动跑一次
    （见 BOOTSTRAP_DONE_KEY），删掉之后不会在下次重启时被重新种回来，删除是
    真正、彻底、不可逆的。这是个重操作，前端必须在二次确认里讲清楚会删多少
    源、多少条新闻，不能让用户以为只是"移出分组"。

    组内只要有一个源仍被任意主题订阅关联，整组删除就拒绝——不能因为删了分组
    而让某个主题的数据源悄悄消失。
    """
    group = db.get(HotSourceGroup, group_id)
    if group is None:
        raise ValueError("分组不存在")
    source_ids = [
        row[0]
        for row in db.query(HotSource.id).filter(HotSource.group_id == group_id).all()
    ]
    linked = _sources_with_topic_link(db, source_ids)
    if linked:
        raise ValueError(
            f"组内有 {len(linked)} 个源仍被主题订阅关联，请先在相关主题里移除这些源再删除分组"
        )
    deleted_items = _cascade_delete_sources(db, source_ids) if source_ids else 0
    db.delete(group)
    db.commit()
    return {"deleted_sources": len(source_ids), "deleted_items": deleted_items}


def _cascade_delete_sources(db: Session, source_ids: list[str]) -> int:
    """按 source_id 列表彻底删除源及其产出的全部新闻数据（不可逆，调用方负责 commit 前的确认）。

    删除顺序：先按 item_id 清子表，再清按 source_id 关联的表，最后删 HotSource 本身。
    HotItemEmbedding / HotSemanticHit / HotReportCandidate 虽然对 hot_items.id 有
    ON DELETE CASCADE（database.py 里为 SQLite 开了 PRAGMA foreign_keys=ON），
    HotRankHistory / HotItemContent 的 item_id 不是真实外键、不会自动级联——
    统一显式批量删，和 crawl_service.cleanup_old_items 用同一套防御性写法，
    不依赖"这张表现在到底有没有加外键"这种容易随重构漂移的隐性前提。
    """
    item_ids = [
        row[0]
        for row in db.query(HotItem.id).filter(HotItem.source_id.in_(source_ids)).all()
    ]
    if item_ids:
        delete_in_batches(db, HotRankHistory, HotRankHistory.item_id, item_ids)
        delete_in_batches(db, HotItemContent, HotItemContent.item_id, item_ids)
        delete_in_batches(db, HotItemEmbedding, HotItemEmbedding.item_id, item_ids)
        delete_in_batches(db, HotSemanticHit, HotSemanticHit.item_id, item_ids)
        delete_in_batches(db, HotReportCandidate, HotReportCandidate.item_id, item_ids)
    deleted_items = (
        delete_in_batches(db, HotItem, HotItem.id, item_ids) if item_ids else 0
    )
    delete_in_batches(
        db, HotCrawlSourceStatus, HotCrawlSourceStatus.source_id, source_ids
    )
    delete_in_batches(db, HotTopicSource, HotTopicSource.source_id, source_ids)
    db.query(HotSource).filter(HotSource.id.in_(source_ids)).delete(
        synchronize_session=False
    )
    return deleted_items


def batch_move_sources(
    db: Session,
    source_ids: list[str],
    group_id: int | None,
) -> int:
    """批量移动源到分组（group_id=None = 移出分组）。返回改动条数。"""
    if group_id is not None and db.get(HotSourceGroup, group_id) is None:
        raise ValueError("分组不存在")
    ids = [s for s in (source_ids or []) if s]
    if not ids:
        return 0
    changed = (
        db.query(HotSource)
        .filter(
            HotSource.id.in_(ids),
            HotSource.group_id.isnot(group_id)
            if group_id is not None
            else HotSource.group_id.isnot(None),
        )
        .update({HotSource.group_id: group_id}, synchronize_session=False)
    )
    db.commit()
    return changed


def batch_set_enabled(
    db: Session,
    source_ids: list[str],
    enabled: bool,
) -> int:
    """批量启停源。返回改动条数。"""
    ids = [s for s in (source_ids or []) if s]
    if not ids:
        return 0
    changed = (
        db.query(HotSource)
        .filter(HotSource.id.in_(ids), HotSource.enabled.isnot(enabled))
        .update({HotSource.enabled: enabled}, synchronize_session=False)
    )
    db.commit()
    return changed


def seed_default_sources(db: Session | None = None) -> None:
    """置位 BOOTSTRAP_DONE_KEY（不再播种任何默认源）。

    只支持 RSS 一种源类型后，原来靠 newsnow/hackernews/github/huggingface/arxiv
    适配器播种的默认源（中文热榜 11 个 + 技术源 5 个）已随适配器一起下掉——
    RSS 地址是用户自己的东西，没有通用的"默认值"可以播种，全新安装的源管理页
    从空开始，靠用户新建 / OPML 批量导入。
    这个函数留着只是为了保持 main.py lifespan 调用顺序不变，并统一在这里给
    BOOTSTRAP_DONE_KEY 落一次位（见该常量的说明：一次性开关，之后
    seed_default_groups 不会再重新播种内置分组）。
    """
    if db is None:
        with SessionLocal() as local_db:
            seed_default_sources(local_db)
        return
    from app.common.services.gemini_config import get_config_value, set_config_value

    if get_config_value(db, BOOTSTRAP_DONE_KEY):
        return
    set_config_value(
        db,
        BOOTSTRAP_DONE_KEY,
        "1",
        "hotlist 默认分组已完成首次播种；置位后不再重新播种，"
        "用户删除内置分组/源后不会在下次启动时被种回来",
    )
    db.commit()


def list_sources(db: Session, group_id: int | None = None) -> list[HotSource]:
    """源列表；group_id 给定 = 只返回该分组的源。"""
    q = db.query(HotSource)
    if group_id is not None:
        q = q.filter(HotSource.group_id == group_id)
    return q.order_by(HotSource.sort_order.asc(), HotSource.id.asc()).all()


def list_enabled_source_ids(db: Session) -> list[str]:
    """全部启用中的源 id，按 sort_order 排序（手动抓取「全部源」时的默认范围）。"""
    return [
        row[0]
        for row in db.query(HotSource.id)
        .filter(HotSource.enabled.is_(True))
        .order_by(HotSource.sort_order.asc())
        .all()
    ]


def get_group_source_ids(db: Session, group_id: int) -> list[str]:
    """组内全部源 id（删除分组前先取 id，便于摘掉调度器里的 job）。"""
    return [
        row[0]
        for row in db.query(HotSource.id).filter(HotSource.group_id == group_id).all()
    ]


def resolve_group_source_ids(db: Session, group: str) -> list[str] | None:
    """把「分组过滤」字符串解析成源 id 列表（榜单/摘要按分组筛选用）。

    空字符串 = 不筛（返回 None）；'ungrouped' = 未分组源；其余解析为分组 id。
    解析失败抛 ValueError，由调用方转成 400。
    """
    if not group:
        return None
    if group == "ungrouped":
        q = db.query(HotSource.id).filter(HotSource.group_id.is_(None))
    else:
        try:
            group_id = int(group)
        except ValueError as exc:
            raise ValueError(f"非法分组: {group}") from exc
        q = db.query(HotSource.id).filter(HotSource.group_id == group_id)
    return [row[0] for row in q.all()]


def get_source(db: Session, source_id: str) -> HotSource | None:
    return db.get(HotSource, source_id)


_UPDATABLE_FIELDS = {
    "name",
    "enabled",
    "interval_hours",
    "expected_domain",
    "decay_half_life_hours",
    "sort_order",
}


def update_source(db: Session, source_id: str, **fields) -> HotSource:
    source = db.get(HotSource, source_id)
    if source is None:
        raise ValueError(f"未知源: {source_id}")
    for key, value in fields.items():
        if key in _UPDATABLE_FIELDS and value is not None:
            setattr(source, key, value)
    source.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(source)
    return source


def create_source(
    db: Session,
    *,
    id: str,
    name: str,
    adapter: str,
    adapter_params: dict,
    expected_domain: str = "",
    decay_half_life_hours: float = 0.0,
    interval_hours: float = 0.5,
    enabled: bool = True,
    sort_order: int = 0,
    group_id: int | None = None,
) -> HotSource:
    if db.get(HotSource, id) is not None:
        raise ValueError(f"源 id 已存在: {id}")
    if adapter != "rss":
        raise ValueError(f"暂不支持的源类型: {adapter!r}，当前只支持 RSS/Atom")
    if not (adapter_params or {}).get("url"):
        raise ValueError("RSS 源缺少 url 参数")
    now = datetime.now(timezone.utc)
    source = HotSource(
        id=id,
        name=name,
        adapter=adapter,
        adapter_params=json.dumps(adapter_params, ensure_ascii=False),
        expected_domain=expected_domain,
        decay_half_life_hours=decay_half_life_hours,
        interval_hours=interval_hours,
        enabled=enabled,
        sort_order=sort_order,
        group_id=group_id,
        created_at=now,
        updated_at=now,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def delete_source(db: Session, source_id: str) -> None:
    """删除单个源：仍被任意主题订阅关联则拒绝；允许删的话，级联清掉这个源
    抓到的全部新闻数据（含向量索引），和分组级联删除走同一套逻辑，不留孤儿数据。
    """
    source = db.get(HotSource, source_id)
    if source is None:
        return
    if _sources_with_topic_link(db, [source_id]):
        raise ValueError("该源仍被主题订阅关联，请先在相关主题里移除该源再删除")
    _cascade_delete_sources(db, [source_id])
    db.commit()
