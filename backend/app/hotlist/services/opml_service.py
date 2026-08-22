"""OPML 导入：解析 → normalize_url 去重 → 复用/新建源 →（可选）建分组/主题关联。

刻意不预置任何仓库的文件清单——硬编码文件名等于埋一个必然失效的依赖。
RSS 源默认 4 小时抓一次（cron_expr="0 */4 * * *"），不要跟中文热榜一样 30 分钟。
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

RSS_FETCH_CRON = "0 */4 * * *"
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
    - group_id 给定时：**新建**的源写入该分组（复用的源不挪动，避免覆盖用户手动归组）
    - topic_id 给定时：为每个源建 HotTopicSource(enabled=False)；两者可同时给、可都空
    - imported_from：关联来源标记（如 "opml:paste" / "opml:{filename}"），默认 ""
    """
    if not (content or "").strip():
        raise ValueError("请提供 OPML 文本")

    entries = parse_opml(content)
    if not entries:
        raise ValueError("OPML 中没有任何带 xmlUrl 的订阅项")

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
                name=entry["title"] or source_id,
                source_kind="tech",
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
                cron_expr=RSS_FETCH_CRON,
                enabled=True,
                group_id=group_id,  # 新建的源写入分组
                created_at=now,
                updated_at=now,
            )
            db.add(existing)
            db.flush()
            result.created.append(existing.id)
        else:
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
