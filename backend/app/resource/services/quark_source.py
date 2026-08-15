"""
夸克网盘资源源：实现 ResourceSource 抽象层。

- search：通过 SearchProvider 策略（B站/头条/Bing/DDG/自定义 API）发现夸克分享链接，
  0 结果时自动降级换词重试；统一解析提取码；搜索本身不需要登录态。
- save：用用户配置的夸克 Cookie 走官方接口转存（QuarkClient），并落库转存记录。
"""
from __future__ import annotations

from datetime import timezone

from loguru import logger
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

# 搜索词降级变体：首轮用"关键词 分类词 夸克网盘"，0 结果时依次降级替换后缀，
# 避免因搜索引擎对固定词的收录/风控差异导致整轮搜索落空。
# 实测 B站/头条对"X 夸克网盘"收录不全，去掉后缀或换"夸克/网盘资源"能显著提升召回。
_FALLBACK_SUFFIXES = ["", "夸克", "网盘资源"]
# 最多尝试的搜索词轮数（含首轮），防止频繁降级触发渠道风控（B站 -412）
_MAX_QUERY_ROUNDS = 3


class QuarkSource(ResourceSource):
    source_id = "quark"
    source_name = "夸克网盘"
    supports_search = True
    supports_save = True
    search_providers = ["bilibili", "toutiao", "bing", "duckduckgo", "custom_api"]

    def _build_query(self, keyword: str, category: str) -> list[str]:
        """构造搜索词候选序列：完整词优先，0 结果时按变体词逐个降级重试。"""
        base = keyword.strip()
        if category in CATEGORY_WORDS:
            base = f"{base} {CATEGORY_WORDS[category]}"
        # 第一候选保留"夸克网盘"强相关词；后续降级词用于扩大召回
        candidates = [f"{base} 夸克网盘"] + [f"{base} {suffix}".strip() for suffix in _FALLBACK_SUFFIXES]
        # 去重且保留顺序
        seen: set[str] = set()
        out: list[str] = []
        for q in candidates:
            if q not in seen:
                seen.add(q)
                out.append(q)
        return out[:_MAX_QUERY_ROUNDS]

    def search(self, keyword: str, category: str, page: int, page_size: int) -> SearchResult:
        queries = self._build_query(keyword, category)

        last_error: str = ""
        provider_chain: list[str] = []
        seen_ids: set[str] = set()
        merged: list[ResourceItem] = []

        for query in queries:
            try:
                links, provider = search_with_providers(query, page, page_size)
            except RuntimeError as exc:
                # 渠道全挂：记录错误，继续尝试下一个变体词（可能换词后渠道恢复）
                last_error = str(exc)
                continue
            if not links:
                # 0 结果：降级重试下一个变体词
                logger.info(f"resource.search 0 结果降级: {query!r} -> 尝试下一个变体")
                continue
            # 命中：合并各变体词的结果（按 share_id 去重），不再继续降级
            provider_chain.append(provider)
            for link in links:
                if link.share_id in seen_ids:
                    continue
                seen_ids.add(link.share_id)
                merged.append(
                    ResourceItem(
                        source=self.source_id,
                        title=link.title,
                        url=link.url,
                        share_id=link.share_id,
                        share_pwd=link.pwd,
                        category=category,
                        snippet=link.snippet,
                    )
                )
            break

        if merged:
            providers = "、".join(dict.fromkeys(provider_chain))
            message = f"通过 {providers} 渠道搜索到 {len(merged)} 条结果"
            return SearchResult(
                source=self.source_id,
                provider=providers,
                items=merged,
                total=len(merged),
                page=page,
                page_size=page_size,
                message=message,
            )
        if last_error:
            raise ResourceSourceError(f"搜索渠道均不可用：{last_error}")
        return SearchResult(
            source=self.source_id,
            provider="",
            items=[],
            total=0,
            page=page,
            page_size=page_size,
            message="未找到夸克网盘资源，可尝试更换关键词、或直接粘贴夸克分享链接进行转存",
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
