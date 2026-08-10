"""
夸克网盘资源源：实现 ResourceSource 抽象层。

- search：通过 SearchProvider 策略（Bing/DDG/自定义 API）发现夸克分享链接，
  统一解析提取码；搜索本身不需要登录态。
- save：用用户配置的夸克 Cookie 走官方接口转存（QuarkClient），并落库转存记录。
"""
from __future__ import annotations

from datetime import timezone

from sqlalchemy.orm import Session

from app.resource.models import ResourceSaveTask
from app.resource.schemas.resource import ResourceItem, SearchResult
from app.resource.services import cookie_store
from app.resource.services.base import ResourceSource, ResourceSourceError
from app.resource.services.quark_client import QuarkClient
from app.resource.services.search_providers import (
    parse_share_id,
    search_with_providers,
)

# 分类 → 搜索词后缀，前端分类筛选与后端查询构造一一对应
CATEGORY_WORDS: dict[str, str] = {
    "movie": "电影",
    "tv": "剧集",
    "book": "电子书",
    "anime": "动漫",
    "music": "音乐",
    "software": "软件",
}


class QuarkSource(ResourceSource):
    source_id = "quark"
    source_name = "夸克网盘"
    supports_search = True
    supports_save = True
    search_providers = ["toutiao", "bing", "duckduckgo", "custom_api"]

    def search(self, keyword: str, category: str, page: int, page_size: int) -> SearchResult:
        query = keyword.strip()
        if category in CATEGORY_WORDS:
            query = f"{query} {CATEGORY_WORDS[category]}"
        query = f"{query} 夸克网盘"

        try:
            links, provider = search_with_providers(query, page, page_size)
        except RuntimeError as exc:
            raise ResourceSourceError(f"搜索渠道均不可用：{exc}") from exc

        items = [
            ResourceItem(
                source=self.source_id,
                title=link.title,
                url=link.url,
                share_id=link.share_id,
                share_pwd=link.pwd,
                category=category,
                snippet=link.snippet,
            )
            for link in links
        ]
        # 搜索是网页公开信息，命中数量用当前页条数近似，不做全量翻页统计
        if items:
            message = f"通过 {provider} 渠道搜索到 {len(items)} 条结果"
        else:
            message = "未找到夸克网盘资源，可更换关键词重试，或直接粘贴夸克分享链接进行转存"
        return SearchResult(
            source=self.source_id,
            provider=provider,
            items=items,
            total=len(items),
            page=page,
            page_size=page_size,
            message=message,
        )

    def save(self, share_url: str, share_pwd: str, target_dir: str, db: Session) -> ResourceSaveTask:
        cookies_str = cookie_store.get_cookies_str(db)
        if not cookies_str:
            raise ResourceSourceError("尚未配置夸克网盘 Cookie，请先到「网盘设置」页配置")

        share_id = parse_share_id(share_url)
        if not share_id:
            raise ResourceSourceError("不是有效的夸克分享链接：https://pan.quark.cn/s/xxxx")

        # 转存前先校验链接状态：已失效直接拒绝，避免白跑一轮接口
        client = QuarkClient(cookies_str)
        try:
            status, message, _file_count = client.check_share(share_id, share_pwd or "")
        except ResourceSourceError as exc:
            status, message = "invalid", str(exc)
        if status == "invalid":
            raise ResourceSourceError(message or "分享链接已失效，无法转存")
        if status == "needs_pwd" and not share_pwd:
            raise ResourceSourceError("该分享需要提取码，请填写提取码后再转存")

        task = ResourceSaveTask(
            user_id=1,
            source=self.source_id,
            resource_title=share_url,
            share_url=share_url,
            share_id=share_id,
            share_pwd=share_pwd or "",
            target_dir=target_dir or "",
            status="pending",
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        try:
            count, message = client.save_share(share_id, share_pwd or "", target_dir or "")
            task.status = "success"
            task.message = message
        except ResourceSourceError as exc:
            task.status = "failed"
            task.message = str(exc)
        except Exception as exc:  # noqa: BLE001 兜底：外部接口异常不把请求打崩
            task.status = "failed"
            task.message = f"转存异常：{exc}"

        db.commit()
        db.refresh(task)
        return task
