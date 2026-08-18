"""源字典的种子数据与 CRUD。

seed_default_sources() 在 main.py lifespan 里调用，幂等：已存在的 id 跳过，
不覆盖用户在前端改过的 name/cron/enabled 等字段——这样重启不会把用户的改动冲掉。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.hotlist.models import HotSource

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


def seed_default_sources(db: Session | None = None) -> None:
    """幂等 seed：已存在的 id 跳过。main.py lifespan 里调用。"""
    if db is None:
        with SessionLocal() as local_db:
            seed_default_sources(local_db)
        return
    now = datetime.now(timezone.utc)
    changed = False
    for sort_order, (source_id, name, expected_domain) in enumerate(DEFAULT_SOURCES):
        if db.get(HotSource, source_id) is not None:
            continue
        db.add(
            HotSource(
                id=source_id,
                name=name,
                source_kind="hotlist",
                adapter="newsnow",
                adapter_params=json.dumps({"platform": source_id}, ensure_ascii=False),
                expected_domain=expected_domain,
                decay_half_life_hours=0.0,
                cron_expr="*/30 * * * *",
                enabled=True,
                sort_order=sort_order,
                created_at=now,
                updated_at=now,
            )
        )
        changed = True
    for sort_order, tech in enumerate(DEFAULT_TECH_SOURCES, start=len(DEFAULT_SOURCES)):
        if db.get(HotSource, tech["id"]) is not None:
            continue
        db.add(
            HotSource(
                id=tech["id"],
                name=tech["name"],
                source_kind="tech",
                adapter=tech["adapter"],
                adapter_params=json.dumps(tech["adapter_params"], ensure_ascii=False),
                expected_domain=tech["expected_domain"],
                decay_half_life_hours=tech["decay_half_life_hours"],
                cron_expr=tech["cron_expr"],
                enabled=True,
                sort_order=sort_order,
                created_at=now,
                updated_at=now,
            )
        )
        changed = True
    if changed:
        db.commit()


def list_sources(db: Session) -> list[HotSource]:
    return db.query(HotSource).order_by(HotSource.sort_order.asc(), HotSource.id.asc()).all()


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
