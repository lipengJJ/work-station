"""AI 热点定时推送编排服务：取配置 → 查当日热点 → AI 总结(可降级) → 组 markdown → 发送(重试) → 写 log。

与设计对齐：
- 定时触发（force=False）：未启用或 webhook_url 为空 → return None（静默跳过）；
- 测试触发（force=True）：webhook_url 为空 → 由 controller 抛 400（此处兜底写 failed log）；
- 发送通道走 build_sender(config) 工厂（当前 mock，未来可切 FutureWecomSender，本文件无需改动）；
- AI 调用：get_ai_credentials(db) + AIRequest + ai_gateway_service.stream 累积 EVENT_DELTA，
  失败/未配置 → 规则降级（DB summary[:80] + 规则综述），log 标记 degraded；
- URL 一律服务端从 DB 拼装（AI 只生成 JSON {overview, summaries[]}，杜绝幻觉链接）。
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.ai_trending.models import AiTrendingItem, AiTrendingPushConfig, AiTrendingPushLog
from app.ai_trending.schemas.push import PushLogOut
from app.ai_trending.services.push_webhook import build_sender, truncate_to_bytes
from app.common.services.ai_config import get_ai_credentials
from app.common.services.ai_gateway import service as ai_gateway_service
from app.common.services.ai_gateway.base import EVENT_DELTA, EVENT_ERROR, AIRequest

# 与 collector._fetch_with_retry 一致：初始 1 次 + 2 次重试（5s / 15s 退避）
RETRY_DELAYS = (5, 15)

# 消息内来源中文标识（与热榜页来源 Tab 一致）
SOURCE_LABELS = {
    "hn": "HN",
    "github": "GitHub",
    "arxiv": "arXiv",
    "hf_models": "HF 模型",
    "hf_papers": "HF 论文",
    "infoq": "InfoQ",
    "kr36": "36氪",
}

DEFAULT_SUMMARY_PROMPT = """你是「AI 开发热点日报」的编辑，请基于给定的当日 AI 开发热点条目，输出一份中文日报内容。
要求：
1. 只输出一个 JSON 对象（不要 markdown 代码块围栏、不要 JSON 以外的任何文字），结构为：
{"overview": "整体趋势综述", "summaries": ["第1条摘要", "第2条摘要", ...]}
2. overview：概括当天热点整体趋势，2-4 句中文，简洁有信息量，不要编造事实。
3. summaries：数组长度必须与输入条目数完全一致，顺序与输入一致；每条摘要 1-2 句（60 字以内），突出亮点。
4. 不要输出任何原文链接（链接由系统服务端从数据库拼装），不要输出序号与标题本身。"""

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class PushService:
    """推送编排（定时 job 与测试推送共用同一入口 run_push）。"""

    # ------------------------------------------------------------ 配置 ----
    def get_config(self, db: Session) -> AiTrendingPushConfig:
        """查单行配置 id=1；不存在则创建默认行（enabled=False）并 commit。"""
        cfg = db.get(AiTrendingPushConfig, 1)
        if cfg is None:
            cfg = AiTrendingPushConfig(id=1)
            db.add(cfg)
            db.commit()
            db.refresh(cfg)
        return cfg

    @staticmethod
    def _merged_config(
        cfg: AiTrendingPushConfig, override: dict | None
    ) -> AiTrendingPushConfig | SimpleNamespace:
        """浅合并 config_override：非空时仅本次生效，不落库；返回 SimpleNamespace。"""
        if not override:
            return cfg
        data = {
            "enabled": cfg.enabled,
            "webhook_url": cfg.webhook_url or "",
            "webhook_secret": cfg.webhook_secret,
            "keyword": cfg.keyword,
            "push_time": cfg.push_time,
            "top_n": cfg.top_n,
            "summary_prompt": cfg.summary_prompt,
        }
        data.update(override)
        return SimpleNamespace(**data)

    # ------------------------------------------------------------ 主入口 ----
    def run_push(
        self,
        db: Session,
        *,
        force: bool = False,
        config_override: dict | None = None,
    ) -> PushLogOut | None:
        """完整推送管线（定时与测试共用）。

        - config = get_config(db)；config_override 非空时浅合并（仅本次生效，不落库）
        - 定时触发（force=False）：未启用或 webhook_url 为空 → return None（静默跳过）
        - 测试触发（force=True）：webhook_url 为空 → 由 controller 抛 400（此处兜底 failed）
        - 查询当日热点 → AI 总结（重试 2 次 5s/15s；失败/未配置 → 规则降级）
        - 组 markdown（标题内嵌关键词；≤4096 字节截断）→ 发送（重试 2 次 5s/15s）
        - 写 push_log：success / degraded / failed；返回 PushLogOut
        """
        cfg = self.get_config(db)
        cfg = self._merged_config(cfg, config_override)

        if not (cfg.webhook_url or "").strip():
            if force:
                return self._write_and_out(db, "failed", "webhook_url 未配置", 0, "")
            return None
        if not force and not cfg.enabled:
            return None

        # 查当日热点（fetched_at >= 服务器本地 00:00 转 UTC，热度降序，limit top_n）
        items = self._query_today_items(db, cfg.top_n)
        if not items:
            logger.warning("AI 热点推送：当日无热点数据，跳过推送")
            return self._write_and_out(db, "failed", "当日无热点数据", 0, "")

        # AI 总结（可降级）：失败/未配置 → 规则降级，不阻断推送
        ai_result = self._ai_summarize(db, items, cfg.summary_prompt)
        degraded = ai_result is None

        # 组 markdown（≤4096 字节截断），URL 由服务端从 DB 拼装
        date_str = datetime.now().astimezone().strftime("%Y-%m-%d")
        content = self._build_markdown(items, ai_result, cfg, date_str)
        content = truncate_to_bytes(content)
        final_count = len(re.findall(r"(?m)^\d+\. \*\*", content)) or len(items)

        # 发送（重试 2 次 5s/15s）
        ok, error = self._send_with_retry(cfg, content)
        if not ok:
            logger.warning(f"AI 热点推送发送最终失败: {error}")
            return self._write_and_out(db, "failed", error, 0, content[:500])

        status = "degraded" if degraded else "success"
        log = self._write_log(db, status, "", final_count, content[:500])
        logger.info(
            f"AI 热点推送完成: status={status}, items={final_count}, "
            f"AI总结={'降级' if degraded else '正常'}"
        )
        return PushLogOut.model_validate(log)

    # ------------------------------------------------------------ 查询 ----
    def _query_today_items(self, db: Session, top_n: int) -> list[AiTrendingItem]:
        """当天热点口径：fetched_at >= 服务器本地 00:00（换算成 UTC）再查询。

        与 push_time 的 APScheduler 触发口径一致（都是服务器本地日）。
        """
        local_now = datetime.now().astimezone()
        day_start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start_utc = day_start_local.astimezone(timezone.utc)
        rows = (
            db.query(AiTrendingItem)
            .filter(AiTrendingItem.fetched_at >= day_start_utc)
            .order_by(AiTrendingItem.heat_score.desc(), AiTrendingItem.id.desc())
            .limit(top_n)
            .all()
        )
        return list(rows)

    # ------------------------------------------------------------ AI 总结 ----
    def _ai_summarize(self, db: Session, items: list[AiTrendingItem], prompt: str | None) -> dict | None:
        """AI 总结：get_ai_credentials → 无 key 返回 None（降级）；
        组装 AIRequest + stream 累积 EVENT_DELTA，失败/JSON 不合法重试 2 次（5s/15s）后返回 None。
        返回 {"overview": str, "summaries": [str, ...]}，summaries 长度 == 条目数。
        """
        provider, api_key, model, thinking_enabled = get_ai_credentials(db)
        if not api_key:
            logger.warning("AI 未配置 API Key，推送将走规则降级")
            return None

        system_instruction = (prompt or "").strip() or DEFAULT_SUMMARY_PROMPT
        user_content = json.dumps(
            [
                {
                    "title": item.title,
                    "source": SOURCE_LABELS.get(item.source, item.source),
                    "category": item.category,
                    "summary": item.summary,
                    "heat_score": item.heat_score,
                }
                for item in items
            ],
            ensure_ascii=False,
        )

        last_error = ""
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                ai_request = AIRequest(
                    provider=provider,
                    model=model,
                    system_instruction=system_instruction,
                    messages=[{"role": "user", "content": user_content}],
                    thinking_enabled=thinking_enabled,
                )
                full_text = ""
                error_message = ""
                for event in ai_gateway_service.stream(ai_request, api_key):
                    etype = event.get("type")
                    if etype == EVENT_DELTA:
                        full_text += event.get("text", "")
                    elif etype == EVENT_ERROR:
                        error_message = event.get("message", "")
                if error_message:
                    raise RuntimeError(error_message)
                parsed = self._parse_ai_json(full_text)
                if parsed and len(parsed["summaries"]) == len(items):
                    return parsed
                last_error = "AI 输出 JSON 解析失败或 summaries 数量与条目数不一致"
            except Exception as exc:  # noqa: BLE001  AI 失败走降级，不阻断推送
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < len(RETRY_DELAYS):
                delay = RETRY_DELAYS[attempt]
                logger.warning(f"AI 总结第 {attempt + 1} 次失败: {last_error}，{delay}s 后重试")
                time.sleep(delay)

        logger.warning(f"AI 总结最终失败: {last_error}，推送走规则降级")
        return None

    @staticmethod
    def _parse_ai_json(text: str) -> dict | None:
        """从 AI 输出中提取 JSON {overview, summaries[]}；提取失败返回 None。"""
        match = _JSON_BLOCK_RE.search(text or "")
        raw = match.group(1) if match else (text or "").strip()
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            start = (text or "").find("{")
            end = (text or "").rfind("}")
            if start == -1 or end <= start:
                return None
            try:
                data = json.loads(text[start : end + 1])
            except (ValueError, TypeError):
                return None
        if not isinstance(data, dict):
            return None
        overview = data.get("overview")
        summaries = data.get("summaries")
        if not isinstance(overview, str) or not overview.strip():
            return None
        if not isinstance(summaries, list) or not all(isinstance(s, str) for s in summaries):
            return None
        return {
            "overview": overview.strip(),
            "summaries": [s.strip() for s in summaries],
        }

    # ------------------------------------------------------------ 组消息 ----
    def _build_markdown(
        self,
        items: list[AiTrendingItem],
        ai_result: dict | None,
        cfg: Any,
        date_str: str,
    ) -> str:
        """按设计 3.4 模板组 markdown；AI 结果缺失时逐条用 DB summary[:80] 兜底；
        标题含 keyword 则内嵌（企微自定义关键词校验）。"""
        overview = ai_result["overview"] if ai_result else self._fallback_overview(items)
        summaries = ai_result["summaries"] if ai_result else None

        title = f"🚀 AI 开发热点日报 {date_str}"
        keyword = (cfg.keyword or "").strip()
        if keyword:
            title = f"{keyword} · {title}"

        lines: list[str] = [
            f"# {title}",
            "",
            "## 📊 今日趋势综述",
            overview,
            "",
            f"## 🔥 Top {len(items)} 热点",
        ]
        for idx, item in enumerate(items, start=1):
            summary = ""
            if summaries and idx - 1 < len(summaries):
                summary = summaries[idx - 1].strip()
            if not summary:
                summary = (item.summary or "").strip()[:80]
            label = SOURCE_LABELS.get(item.source, item.source)
            lines.append(f"{idx}. **{item.title}**（{label} · 热度 {item.heat_score:.0f}）")
            lines.append(f"   > {summary}")
            lines.append(f"   [查看原文]({item.url})")
        return "\n".join(lines)

    @staticmethod
    def _fallback_overview(items: list[AiTrendingItem]) -> str:
        """规则降级综述：今日共 N 条 AI 热点，最高热度来自 X，点击下方链接查看原文。"""
        top = max(items, key=lambda x: x.heat_score or 0)
        label = SOURCE_LABELS.get(top.source, top.source)
        return f"今日共 {len(items)} 条 AI 热点，最高热度来自 {label}，点击下方链接查看原文。"

    # ------------------------------------------------------------ 发送 ----
    def _send_with_retry(self, cfg: Any, content: str) -> tuple[bool, str]:
        """循环最多 3 次（初始 + 2 次，sleep 5/15）；sender = build_sender(cfg)。
        成功 → (True, "")；失败/异常 → (False, errmsg[:500])。"""
        sender = build_sender(cfg)
        last_error = ""
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                result = sender.send(content)
                if result.status:
                    logger.info(f"AI 热点推送发送成功（第 {attempt + 1} 次尝试）")
                    return True, ""
                last_error = f"errcode={result.errcode} errmsg={result.errmsg}"
                logger.warning(f"AI 热点推送第 {attempt + 1} 次发送失败: {last_error}")
            except Exception as exc:  # noqa: BLE001  发送器异常同样重试
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(f"AI 热点推送第 {attempt + 1} 次发送异常: {last_error}")
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
        return False, last_error[:500]

    # ------------------------------------------------------------ 写 log ----
    def _write_log(
        self, db: Session, status: str, error: str, count: int, preview: str
    ) -> AiTrendingPushLog:
        """写推送记录并 commit（error/preview 分别截断 500 字）。"""
        log = AiTrendingPushLog(
            status=status,
            error=(error or "")[:500],
            items_count=int(count or 0),
            summary_preview=(preview or "")[:500],
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

    def _write_and_out(
        self, db: Session, status: str, error: str, count: int, preview: str
    ) -> PushLogOut:
        log = self._write_log(db, status, error, count, preview)
        return PushLogOut.model_validate(log)


push_service = PushService()
