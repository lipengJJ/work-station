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
from app.hotlist.models import HotSource, HotSourceGroup

if TYPE_CHECKING:
    from app.hotlist.schemas.source_group import (
        SourceGroupIn,
        SourceGroupUpdateIn,
    )

# id, 显示名, 期望域名 —— 取自 TrendRadar config/config.yaml 的 platforms.sources
DEFAULT_SOURCES: list[tuple[str, str, str]] = [
    ("toutiao", "今日头条", "toutiao.com"),
    ("baidu", "百度热搜", "baidu.com"),
    ("wallstreetcn-hot", "华尔街见闻", "wallstreetcn.com"),
    ("thepaper", "澎湃新闻", "thepaper.cn"),
    ("bilibili-hot-search", "bilibili 热搜", "bilibili.com"),
    ("cls-hot", "财联社热门", "cls.cn"),
    ("ifeng", "凤凰网", "ifeng.com"),
    ("tieba", "贴吧", "baidu.com"),
    ("weibo", "微博", "weibo.com"),
    ("douyin", "抖音", "douyin.com"),
    ("zhihu", "知乎", "zhihu.com"),
]

# 技术源：字段比中文热榜多（各自 adapter 不同），用 dict 表达更清楚。
# decay_half_life_hours：HN/GitHub/HF 有原始热度指标撑着，48 小时半衰期；
# arXiv/RSS 纯按发布时间排，24 小时半衰期，新内容淘汰旧内容更快。
# expected_domain：hackernews 的链接指向任意外部站点（HN 的本质就是聚合外链），不做域名校验；
# 其余每个源的链接都固定落在自己的域下，照常开启。
DEFAULT_TECH_SOURCES: list[dict] = [
    {
        "id": "hackernews",
        "name": "Hacker News",
        "adapter": "hackernews",
        "adapter_params": {},
        "expected_domain": "",
        "decay_half_life_hours": 48.0,
        "cron_expr": "0 * * * *",
    },
    {
        "id": "github",
        "name": "GitHub Trending",
        "adapter": "github",
        "adapter_params": {},
        "expected_domain": "github.com",
        "decay_half_life_hours": 48.0,
        "cron_expr": "0 2,14 * * *",
    },
    {
        "id": "hf_models",
        "name": "HF 模型榜",
        "adapter": "huggingface",
        "adapter_params": {"mode": "models"},
        "expected_domain": "huggingface.co",
        "decay_half_life_hours": 48.0,
        "cron_expr": "0 * * * *",
    },
    {
        "id": "hf_papers",
        "name": "HF 每日论文",
        "adapter": "huggingface",
        "adapter_params": {"mode": "papers"},
        "expected_domain": "arxiv.org",
        "decay_half_life_hours": 48.0,
        "cron_expr": "0 * * * *",
    },
    {
        "id": "arxiv",
        "name": "arXiv",
        "adapter": "arxiv",
        "adapter_params": {},
        "expected_domain": "arxiv.org",
        "decay_half_life_hours": 24.0,
        "cron_expr": "0 * * * *",
    },
    {
        "id": "infoq",
        "name": "InfoQ",
        "adapter": "rss",
        "adapter_params": {"url": "https://www.infoq.cn/feed"},
        "expected_domain": "infoq.cn",
        "decay_half_life_hours": 24.0,
        "cron_expr": "0 * * * *",
    },
    {
        "id": "kr36",
        "name": "36氪",
        "adapter": "rss",
        "adapter_params": {"url": "https://www.36kr.com/feed"},
        "expected_domain": "36kr.com",
        "decay_half_life_hours": 24.0,
        "cron_expr": "0 * * * *",
    },
]


def seed_default_groups(db: Session | None = None) -> int:
    """幂等：确保「中文热榜」「技术社区」两个内置分组存在，返回新建数。

    main.py lifespan 里在 seed_default_sources() 之前调用（T03 接上）。
    已存在的分组不覆盖（不冲掉用户改过的 name/description/color）。
    """
    if db is None:
        with SessionLocal() as local_db:
            return seed_default_groups(local_db)
    now = datetime.now(timezone.utc)
    defaults = [
        ("中文热榜", "NewsNow 平台中文热榜源", "#ff4d4f", 0),
        ("技术社区", "HN / GitHub / arXiv / HF 等技术源", "#1677ff", 1),
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


def delete_group(db: Session, group_id: int) -> None:
    """删除分组：内置分组拒删；组内源的 group_id 置 NULL（不级联删源）。"""
    group = db.get(HotSourceGroup, group_id)
    if group is None:
        raise ValueError("分组不存在")
    if group.is_builtin:
        raise ValueError("内置分组不允许删除")
    db.query(HotSource).filter(HotSource.group_id == group_id).update(
        {HotSource.group_id: None}, synchronize_session=False
    )
    db.delete(group)
    db.commit()


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
    """幂等 seed：已存在的 id 跳过。main.py lifespan 里调用（seed_default_groups 之后）。

    新建的源按 source_kind 直接归入内置分组（中文热榜/技术社区），
    保证全新安装后源管理页不是一片「未分组」。
    """
    if db is None:
        with SessionLocal() as local_db:
            seed_default_sources(local_db)
        return
    now = datetime.now(timezone.utc)
    changed = False
    # 内置分组（可能尚未 seed，查不到就 None → 新源不归组，迁移阶段 4 会兜底补归）
    cn_group = (
        db.query(HotSourceGroup)
        .filter(HotSourceGroup.name == "中文热榜")
        .first()
    )
    tech_group = (
        db.query(HotSourceGroup)
        .filter(HotSourceGroup.name == "技术社区")
        .first()
    )
    cn_group_id = cn_group.id if cn_group else None
    tech_group_id = tech_group.id if tech_group else None
    for sort_order, (source_id, name, expected_domain) in enumerate(
        DEFAULT_SOURCES
    ):
        if db.get(HotSource, source_id) is not None:
            continue
        db.add(
            HotSource(
                id=source_id,
                name=name,
                source_kind="hotlist",
                adapter="newsnow",
                adapter_params=json.dumps(
                    {"platform": source_id},
                    ensure_ascii=False,
                ),
                expected_domain=expected_domain,
                decay_half_life_hours=0.0,
                cron_expr="*/30 * * * *",
                enabled=True,
                sort_order=sort_order,
                group_id=cn_group_id,
                created_at=now,
                updated_at=now,
            )
        )
        changed = True
    for sort_order, tech in enumerate(
        DEFAULT_TECH_SOURCES, start=len(DEFAULT_SOURCES)
    ):
        if db.get(HotSource, tech["id"]) is not None:
            continue
        db.add(
            HotSource(
                id=tech["id"],
                name=tech["name"],
                source_kind="tech",
                adapter=tech["adapter"],
                adapter_params=json.dumps(
                    tech["adapter_params"],
                    ensure_ascii=False,
                ),
                expected_domain=tech["expected_domain"],
                decay_half_life_hours=tech["decay_half_life_hours"],
                cron_expr=tech["cron_expr"],
                enabled=True,
                sort_order=sort_order,
                group_id=tech_group_id,
                created_at=now,
                updated_at=now,
            )
        )
        changed = True
    if changed:
        db.commit()


def list_sources(db: Session, group_id: int | None = None) -> list[HotSource]:
    """源列表；group_id 给定 = 只返回该分组的源。"""
    q = db.query(HotSource)
    if group_id is not None:
        q = q.filter(HotSource.group_id == group_id)
    return q.order_by(HotSource.sort_order.asc(), HotSource.id.asc()).all()


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
    "cron_expr",
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
    source_kind: str = "hotlist",
    expected_domain: str = "",
    decay_half_life_hours: float = 0.0,
    cron_expr: str = "*/30 * * * *",
    enabled: bool = True,
    sort_order: int = 0,
    group_id: int | None = None,
) -> HotSource:
    if db.get(HotSource, id) is not None:
        raise ValueError(f"源 id 已存在: {id}")
    now = datetime.now(timezone.utc)
    source = HotSource(
        id=id,
        name=name,
        source_kind=source_kind,
        adapter=adapter,
        adapter_params=json.dumps(adapter_params, ensure_ascii=False),
        expected_domain=expected_domain,
        decay_half_life_hours=decay_half_life_hours,
        cron_expr=cron_expr,
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
    source = db.get(HotSource, source_id)
    if source is None:
        return
    db.delete(source)
    db.commit()
