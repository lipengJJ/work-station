"""OPML 导入：解析 → normalize_url 去重 → 复用/新建源 →（可选）建分组/主题关联。

刻意不预置任何仓库的文件清单——硬编码文件名等于埋一个必然失效的依赖。
RSS 源默认 4 小时抓一次（interval_hours=4.0），不要跟中文热榜一样 30 分钟。
拉取远端 OPML（fetch_opml）的动作移到 controller：controller 收到 url 先拉文本再传 content。
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Optional
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

import requests
from sqlalchemy.orm import Session

from app.common.utils.url import normalize_url
from app.hotlist.models import HotSource, HotTopicSource
from app.hotlist.schemas.topic import OpmlImportResult

RSS_FETCH_INTERVAL_HOURS = 4.0
RSS_DECAY_HALF_LIFE_HOURS = 24.0
OPML_HTTP_TIMEOUT = 15

_XML_NS_RE = re.compile(r"xmlns=[\"'][^\"']+[\"']")


def fetch_opml(url: str) -> str:
    """拉取远端 OPML 文本。失败抛 ValueError（message 可展示）。"""
    try:
        resp = requests.get(url, timeout=OPML_HTTP_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (compatible; WorkBench-Hotlist/1.0)"
        })
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError(f"拉取 OPML 失败: {exc}") from exc
    return resp.text


def _clean_xml(text: str) -> str:
    """容忍常见畸形：xmlns 声明残留（重复声明会导致 ET 解析失败）。"""
    text = (text or "").strip()
    # 去掉前导 XML 声明之外的多余 xmlns（Python ET 对重复默认命名空间声明不友好）
    if text.count("xmlns=") > 1:
        text = _XML_NS_RE.sub("", text, count=1)
    return text


def parse_opml(text: str) -> list[dict]:
    """解析 OPML，逐条取 xmlUrl / title / htmlUrl / text。
    返回 [{title, xml_url, html_url}]，跳过无 xmlUrl 的 outline。"""
    entries: list[dict] = []
    try:
        root = ET.fromstring(_clean_xml(text))
    except ET.ParseError as exc:
        raise ValueError(f"OPML 解析失败（不是合法 XML）: {exc}") from exc

    def _walk(node) -> None:
        for child in node:
            attrs = child.attrib or {}
            xml_url = (attrs.get("xmlUrl") or "").strip()
            if xml_url:
                entries.append(
                    {
                        "title": (
                            (attrs.get("title") or attrs.get("text") or "")
                            .strip()[:128]
                        ),
                        "xml_url": xml_url,
                        "html_url": (attrs.get("htmlUrl") or "").strip(),
                    }
                )
            _walk(child)  # 嵌套 outline（OPML 允许分组）

    _walk(root)
    return entries


def _find_source_by_url(db: Session, normalized: str) -> Optional[HotSource]:
    """全局查源：按 (adapter='rss', adapter_params.url == normalized) 精确匹配。

    源量级小（几十到几百行），全量过滤比 SQL LIKE 模糊匹配更稳（JSON 字段无法索引）。
    """
    for source in db.query(HotSource).filter(HotSource.adapter == "rss").all():
        try:
            params = json.loads(source.adapter_params or "{}")
        except (ValueError, TypeError):
            continue
        if normalize_url(params.get("url", "")) == normalized:
            return source
    return None


def import_opml(
    db: Session,
    content: str,
    group_id: int | None = None,
    topic_id: int | None = None,
    imported_from: str = "",
) -> OpmlImportResult:
    """导入 OPML 文本。返回新增/复用/跳过统计 + 全部源 id（source_ids）。

    - content = OPML 文本（拉取 URL 的动作在 controller 完成）
    - group_id 给定时：新建的源写入该分组；复用的源只在当前**未分组**时才挪进去
      （已经在别的分组里 = 用户手动归过组，不覆盖；未分组 = 从没组织过，导入时
      选了分组就该按选的来，不然用户选了分组、源却原地不动，一头雾水）
    - topic_id 给定时：为每个源建 HotTopicSource(enabled=False)；两者可同时给、可都空
    - imported_from：关联来源标记（如 "opml:paste" / "opml:{filename}"），默认 ""
    """
    if not (content or "").strip():
        raise ValueError("请提供 OPML 文本")

    entries = parse_opml(content)
    if not entries:
        raise ValueError("OPML 中没有任何带 xmlUrl 的订阅项")

    return _import_entries(db, entries, group_id, topic_id, imported_from)


def import_feed_urls(
    db: Session,
    urls: list[str],
    group_id: int | None = None,
    topic_id: int | None = None,
    imported_from: str = "",
) -> OpmlImportResult:
    """直接按 RSS/Atom 订阅地址列表导入（一行一个），不要求是 OPML 文档。

    「或填写 OPML 的 URL」这个输入框实际大多数时候被当成"粘贴一个 RSS 地址"用——
    真正的 OPML 是给一堆 outline 打包的聚合文档，用户手头常有的其实是散的 feed
    地址。与其要求先套一层 OPML 外壳，不如直接支持粘贴多行地址，每行当一个源，
    复用与 import_opml 完全相同的去重/建源/关联逻辑（parse_opml 解析出的 entries
    结构本来就是 {title, xml_url, html_url}，这里跳过解析直接构造）。
    """
    cleaned = [u.strip() for u in urls if u.strip()]
    if not cleaned:
        raise ValueError("请至少填写一个 RSS 订阅地址")
    entries = [{"title": "", "xml_url": u, "html_url": ""} for u in cleaned]
    return _import_entries(db, entries, group_id, topic_id, imported_from)


def _import_entries(
    db: Session,
    entries: list[dict],
    group_id: int | None,
    topic_id: int | None,
    imported_from: str,
) -> OpmlImportResult:
    """entries → 新建/复用源 + 可选分组/主题关联，OPML 解析结果与直填地址列表共用。"""
    result = OpmlImportResult()
    seen_urls: set[str] = set()
    now = datetime.now(timezone.utc)

    for entry in entries:
        xml_url = entry["xml_url"]
        normalized = normalize_url(xml_url)
        if not normalized or normalized.startswith("javascript:"):
            result.skipped += 1
            continue
        if normalized in seen_urls:  # 同一 OPML 内重复
            result.skipped += 1
            continue
        seen_urls.add(normalized)

        existing = _find_source_by_url(db, normalized)
        if existing is None:
            source_id = _unique_source_id(db, normalized)
            existing = HotSource(
                id=source_id,
                # 直填地址列表没有 title，退化用域名（比一串 rss-xxx-哈希 id 更好认）
                name=entry["title"] or _host_of(normalized) or source_id,
                adapter="rss",
                adapter_params=json.dumps(
                    {"url": normalized}, ensure_ascii=False
                ),
                # expected_domain 留空 = 不做域名校验。域名校验的本意是防公共聚合
                # 接口（NewsNow 实例）被篡改后返回钓鱼链接；而 OPML 订阅的 RSS 里，
                # 条目链接指向 feed 域名之外是完全正常的（转发型 feed 如
                # api.xgo.ing 的条目就指向 x.com），按 feed 域名校验会整源误杀。
                expected_domain="",
                decay_half_life_hours=RSS_DECAY_HALF_LIFE_HOURS,
                interval_hours=RSS_FETCH_INTERVAL_HOURS,
                enabled=True,
                group_id=group_id,  # 新建的源写入分组
                created_at=now,
                updated_at=now,
            )
            db.add(existing)
            db.flush()
            result.created.append(existing.id)
        else:
            if group_id is not None and existing.group_id is None:
                existing.group_id = group_id
            result.reused.append(existing.id)
        result.source_ids.append(existing.id)

        # 主题关联（已存在则只更新 imported_from，不动启用状态）
        if topic_id is not None:
            link = (
                db.query(HotTopicSource)
                .filter(
                    HotTopicSource.topic_id == topic_id,
                    HotTopicSource.source_id == existing.id,
                )
                .first()
            )
            if link is None:
                db.add(
                    HotTopicSource(
                        topic_id=topic_id,
                        source_id=existing.id,
                        enabled=False,
                        imported_from=imported_from,
                    )
                )
            elif link.imported_from != imported_from:
                link.imported_from = imported_from

    db.commit()
    result.detail = (
        f"导入完成：新增 {len(result.created)} 个源，复用 {len(result.reused)} 个，"
        f"跳过 {result.skipped} 个（重复或无效）。新源已启用；若同时关联了主题，关联默认关闭。"
    )
    return result


def _unique_source_id(db: Session, normalized_url: str) -> str:
    """生成稳定且唯一的源 id：以域名开头 + 短哈希。"""
    host = _host_of(normalized_url).replace(".", "-") or "rss"
    digest = hashlib.md5(normalized_url.encode("utf-8")).hexdigest()[:8]
    base = f"rss-{host}-{digest}"
    candidate = base
    n = 1
    while db.get(HotSource, candidate) is not None:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
