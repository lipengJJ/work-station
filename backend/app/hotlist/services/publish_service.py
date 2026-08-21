"""S3 兼容对象存储发布（Phase 7 §6）。

只做 S3 兼容一种实现：七牛、腾讯 COS、阿里 OSS、MinIO 全部提供 S3 兼容端点，
不引入各厂商 SDK。配置存 ApiConfig（key 前缀 hotlist_s3_）：

    hotlist_s3_endpoint / hotlist_s3_region / hotlist_s3_bucket
    hotlist_s3_access_key / hotlist_s3_secret_key / hotlist_s3_public_base_url

发布物与路径约定（§6.2）：
    topics.json                             全部主题清单
    reports/{slug}/index.json               期数索引（可缓存的动态索引）
    reports/{slug}/latest.json              最新一期
    reports/{slug}/{period_key}.json        结构化数据（immutable）
    reports/{slug}/{period_key}.html        自包含 HTML（immutable）

发布失败不影响报告：publish_status=failed + error，页面提供「重新发布」。
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy.orm import Session

from app.common.services.gemini_config import get_config_value

if TYPE_CHECKING:
    from app.hotlist.models import HotTopicReport

CONFIG_KEYS = (
    "hotlist_s3_endpoint",
    "hotlist_s3_region",
    "hotlist_s3_bucket",
    "hotlist_s3_access_key",
    "hotlist_s3_secret_key",
    "hotlist_s3_public_base_url",
)

IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
SHORT_CACHE = "public, max-age=300"


class PublishError(Exception):
    """发布失败（配置缺失 / boto3 不可用 / S3 返回错误），message 可展示。"""


def _get_s3_config(db: Session) -> dict:
    return {key: get_config_value(db, key) or "" for key in CONFIG_KEYS}


def is_configured(db: Session) -> bool:
    cfg = _get_s3_config(db)
    return bool(
        cfg["hotlist_s3_endpoint"]
        and cfg["hotlist_s3_bucket"]
        and cfg["hotlist_s3_access_key"]
    )


def get_public_base(db: Session) -> str:
    """公开访问基地址：配置了 public_base_url 用它，否则返回空（客户端自拼）。"""
    return (_get_s3_config(db)["hotlist_s3_public_base_url"] or "").rstrip("/")


def _get_client(cfg: dict):
    """延迟创建 boto3 client（boto3 是可选依赖，未安装时抛 PublishError）。"""
    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except ImportError as exc:
        raise PublishError("boto3 未安装（pip install boto3），无法发布") from exc

    return boto3.client(
        "s3",
        endpoint_url=cfg["hotlist_s3_endpoint"],
        region_name=cfg["hotlist_s3_region"] or "auto",
        aws_access_key_id=cfg["hotlist_s3_access_key"],
        aws_secret_access_key=cfg["hotlist_s3_secret_key"],
        config=BotoConfig(
            signature_version="s3v4",
            connect_timeout=10,
            read_timeout=30,
        ),
    )


def _put_object(
    client,
    bucket: str,
    key: str,
    body: str,
    content_type: str,
    cache_control: str,
) -> None:
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType=content_type,
        CacheControl=cache_control,
    )


# ------------------------------------------------------------ 组装 ----

def _topic_payload(db: Session, report) -> dict:
    """单期报告的结构化 JSON（§6.2 的客户端渲染数据，不依赖后端）。"""
    from app.hotlist.models import HotItem, HotTopic

    topic = db.get(HotTopic, report.topic_id)
    items: list[dict] = []
    if report.item_ids:
        rows = (
            db.query(HotItem)
            .filter(HotItem.id.in_(json.loads(report.item_ids or "[]")))
            .all()
        )
        for row in rows:
            items.append(
                {
                    "id": row.id,
                    "title": row.title,
                    "url": row.url,
                    "source": row.source_id,
                    "weight": row.weight,
                    "published_at": (
                        row.published_at.isoformat()
                        if row.published_at
                        else None
                    ),
                }
            )
    highlights = []
    try:
        highlights = json.loads(report.highlights or "[]")
    except (ValueError, TypeError):
        pass
    return {
        "period": report.period_key,
        "topic": {
            "slug": topic.slug if topic else "",
            "name": topic.name if topic else "",
        },
        "highlights": highlights,
        "content_md": report.content_md,
        "items": items,
    }


def render_report_html(report: HotTopicReport, topic_name: str) -> str:
    """自包含 HTML：直接浏览器打开，正文渲染 markdown 要点 + 引用链接可点。"""
    import html as html_lib

    highlights = []
    try:
        highlights = json.loads(report.highlights or "[]")
    except (ValueError, TypeError):
        pass
    item_ids = []
    try:
        item_ids = json.loads(report.item_ids or "[]")
    except (ValueError, TypeError):
        pass

    def _md_to_html(text: str) -> str:
        """极简 markdown → HTML（标题/列表/粗体/引用/链接），够报告阅读用。"""
        import re as _re

        out_lines: list[str] = []
        in_list = False
        for line in (text or "").splitlines():
            stripped = line.strip()
            if stripped.startswith(("## ", "### ", "#### ")):
                if in_list:
                    out_lines.append("</ul>")
                    in_list = False
                level = min(len(stripped) - stripped.index(" ") - 1, 4)
                out_lines.append(
                    f"<h{level}>{html_lib.escape(stripped.split(' ', 1)[1])}"
                    f"</h{level}>"
                )
            elif stripped.startswith(("- ", "* ")):
                if not in_list:
                    out_lines.append("<ul>")
                    in_list = True
                out_lines.append(f"<li>{html_lib.escape(stripped[2:])}</li>")
            elif stripped == "":
                if in_list:
                    out_lines.append("</ul>")
                    in_list = False
                out_lines.append("")
            else:
                if in_list:
                    out_lines.append("</ul>")
                    in_list = False
                out_lines.append(f"<p>{html_lib.escape(line)}</p>")
        if in_list:
            out_lines.append("</ul>")
        return "\n".join(out_lines)

    hl_items = "".join(f"<li>{html_lib.escape(h)}</li>" for h in highlights)
    hl_html = f"<h2>核心结论</h2><ul>{hl_items}</ul>" if hl_items else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_lib.escape(topic_name)} · {html_lib.escape(report.period_key)}</title>
<style>
body{{max-width:820px;margin:0 auto;padding:24px 16px 80px;font:16px/1.75 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#222}}
h1{{font-size:26px;border-bottom:2px solid #eee;padding-bottom:8px}}
h2{{font-size:20px;margin-top:32px}}h3{{font-size:17px}}h4{{font-size:15px}}
a{{color:#2563eb;text-decoration:none}}a:hover{{text-decoration:underline}}
.meta{{color:#888;font-size:13px;margin-bottom:24px}}
ul{{padding-left:22px}}li{{margin:6px 0}}
blockquote{{border-left:4px solid #ddd;margin:12px 0;padding:4px 16px;color:#555}}
code{{background:#f4f4f4;padding:1px 6px;border-radius:4px;font-size:14px}}
</style>
</head>
<body>
<h1>{html_lib.escape(topic_name)} · {html_lib.escape(report.period_key)}</h1>
<div class="meta">生成时间：{report.created_at.isoformat() if report.created_at else ''} · 引用条目 {len(item_ids)} 条</div>
{hl_html}
<div class="content">
{_md_to_html(report.content_md)}
</div>
</body>
</html>"""


# ------------------------------------------------------------ 发布 ----

def publish_report(db: Session, report: HotTopicReport) -> dict:
    """发布一期报告 + 增量维护索引。

    返回 {"status": "success"|"failed", "urls": {...}, "error": ""}。
    任何失败都不抛——报告本身照常可读，页面提供重新发布。
    """
    if not is_configured(db):
        return {
            "status": "failed",
            "urls": {},
            "error": "S3 发布未配置（系统设置 → API 配置 → hotlist_s3_*）",
        }
    if report.status != "success":
        return {"status": "failed", "urls": {}, "error": "报告未生成成功，无法发布"}

    from app.hotlist.models import HotTopic

    topic = db.get(HotTopic, report.topic_id)
    if topic is None:
        return {"status": "failed", "urls": {}, "error": "主题不存在"}

    try:
        cfg = _get_s3_config(db)
        client = _get_client(cfg)
        base = f"reports/{topic.slug}"
        urls: dict[str, str] = {}

        formats = []
        try:
            formats = json.loads(topic.publish_formats or '["json","html"]')
        except (ValueError, TypeError):
            formats = ["json", "html"]

        if "json" in formats:
            payload = json.dumps(
                _topic_payload(db, report), ensure_ascii=False, indent=2
            )
            _put_object(
                client,
                cfg["hotlist_s3_bucket"],
                f"{base}/{report.period_key}.json",
                payload,
                "application/json; charset=utf-8",
                IMMUTABLE_CACHE,
            )
            urls["json"] = f"{base}/{report.period_key}.json"
        if "html" in formats:
            html = render_report_html(report, topic.name)
            _put_object(
                client,
                cfg["hotlist_s3_bucket"],
                f"{base}/{report.period_key}.html",
                html,
                "text/html; charset=utf-8",
                IMMUTABLE_CACHE,
            )
            urls["html"] = f"{base}/{report.period_key}.html"

        # latest.json（每期覆盖）
        latest = _topic_payload(db, report)
        _put_object(
            client,
            cfg["hotlist_s3_bucket"],
            f"{base}/latest.json",
            json.dumps(latest, ensure_ascii=False, indent=2),
            "application/json; charset=utf-8",
            SHORT_CACHE,
        )

        # index.json（期数索引增量维护）
        index = _build_index(db, client, cfg, topic)
        _put_object(
            client,
            cfg["hotlist_s3_bucket"],
            f"{base}/index.json",
            json.dumps(index, ensure_ascii=False, indent=2),
            "application/json; charset=utf-8",
            SHORT_CACHE,
        )

        # topics.json（全部主题清单）
        _publish_topics_index(db, client, cfg)

        public_base = get_public_base(db)
        if public_base:
            urls = {k: f"{public_base}/{v}" for k, v in urls.items()}
        return {"status": "success", "urls": urls, "error": ""}
    except Exception as exc:  # noqa: BLE001  发布失败不影响报告
        logger.exception(f"主题报告发布失败（topic {topic.id} {report.period_key}）")
        return {"status": "failed", "urls": {}, "error": str(exc)[:500]}


def _build_index(db: Session, client, cfg: dict, topic) -> dict:
    """重建该主题的 index.json：读对象存储上的历史期（或从本地库补），合并本期。"""
    from app.hotlist.models import HotTopicReport

    periods: list[dict] = []
    # 从对象存储读现有 index（增量维护，历史期不被改写）
    try:
        resp = client.get_object(
            Bucket=cfg["hotlist_s3_bucket"],
            Key=f"reports/{topic.slug}/index.json",
        )
        existing = json.loads(resp["Body"].read().decode("utf-8"))
        periods = existing.get("periods", [])
    except Exception:  # noqa: BLE001  首次发布没有历史索引
        pass

    known = {p["key"] for p in periods}
    # 本地库的成功报告全量核对，补齐对象存储上缺失的期（换桶/重建场景）
    local_rows = (
        db.query(HotTopicReport)
        .filter(
            HotTopicReport.topic_id == topic.id,
            HotTopicReport.status == "success",
        )
        .order_by(HotTopicReport.period_end.desc())
        .all()
    )
    for row in local_rows:
        if row.period_key not in known:
            highlights = []
            try:
                highlights = json.loads(row.highlights or "[]")
            except (ValueError, TypeError):
                pass
            periods.append(
                {
                    "key": row.period_key,
                    "start": (
                        row.period_start.isoformat()
                        if row.period_start
                        else ""
                    ),
                    "end": (
                        row.period_end.isoformat()
                        if row.period_end
                        else ""
                    ),
                    "item_count": row.item_count,
                    "highlights": highlights[:5],
                    "json": f"reports/{topic.slug}/{row.period_key}.json",
                    "html": f"reports/{topic.slug}/{row.period_key}.html",
                }
            )
    periods.sort(key=lambda p: p["key"], reverse=True)
    return {
        "topic": {
            "slug": topic.slug,
            "name": topic.name,
            "period": topic.digest_period,
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "periods": periods,
    }


def _publish_topics_index(db: Session, client, cfg: dict) -> None:
    """topics.json：全部启用主题的清单（客户端发现用）。"""
    from app.hotlist.models import HotTopic, HotTopicReport

    topics = (
        db.query(HotTopic)
        .filter(HotTopic.enabled.is_(True))
        .order_by(HotTopic.sort_order.asc())
        .all()
    )
    payload = []
    for topic in topics:
        latest = (
            db.query(HotTopicReport)
            .filter(
                HotTopicReport.topic_id == topic.id,
                HotTopicReport.status == "success",
            )
            .order_by(HotTopicReport.period_end.desc())
            .first()
        )
        payload.append(
            {
                "slug": topic.slug,
                "name": topic.name,
                "description": topic.description,
                "period": topic.digest_period,
                "latest": latest.period_key if latest else "",
                "index": f"reports/{topic.slug}/index.json",
            }
        )
    _put_object(
        client, cfg["hotlist_s3_bucket"], "topics.json",
        json.dumps(payload, ensure_ascii=False, indent=2),
        "application/json; charset=utf-8", SHORT_CACHE,
    )
