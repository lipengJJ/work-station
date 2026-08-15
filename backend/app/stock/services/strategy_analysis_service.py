"""
策略驱动的 AI 个股分析 —— 编排服务。

职责：
1. 组装输入 context：复用 orchestrator 各 build_*（cache-first，不重复拉数据源），
   控 token 只取关键子集（financials 跳过完整 series，kline 只留摘要），保证一次
   分析请求的 prompt 体量可控。
2. 把策略（描述 + rules）渲染成 system_instruction：策略决定关注哪些指标、风险
   偏好、买入/观望/回避的倾向，以及输出的小节结构。
3. 结论提取：prompt 要求 markdown 末尾输出独立 JSON 块（分级结论），流式结束后
   用正则取最后一个合法块解析；解析失败才降级 glm 结构化接口兜底（不依赖它也能
   工作，zhipu key 未配置时跳过兜底、rating 留空，报告本身不受影响）。

设计取舍：不做第二次模型调用来抽结论——让模型在正文末尾一次性输出结构化结论块，
零额外成本；可靠性由"独立 code block + 白名单枚举（buy/hold/avoid）"保证。
"""
from __future__ import annotations

import json
import re
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.common.services.ai_gateway.glm_structured import generate_structured
from app.common.services.zhipu_config import get_zhipu_config
from app.stock.models.stock_strategy import StockStrategy
from app.stock.services import kline_client, orchestrator

_RATING_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_RATING_WHITELIST = ("buy", "hold", "avoid")

# snapshot / overview 里已有的关键字段（build_overview 的 data 本身不大，全量给）
_CONTEXT_OVERVIEW_KEYS = [
    "symbol", "name", "sector", "industry", "price", "change", "change_percent",
    "pe_ttm", "pe_forward", "pb", "roe", "operating_margin", "market_cap", "fcf_yield",
    "next_earnings_date", "sec_entity_name",
]

_EARNINGS_KEYS = [
    "current_quarter_eps_estimate", "current_quarter_growth_estimate",
    "next_quarter_eps_estimate", "next_quarter_growth_estimate",
    "current_year_eps_estimate", "next_year_eps_estimate",
]


def _pick(data: dict, keys: list[str]) -> dict:
    return {k: data[k] for k in keys if k in data and data[k] is not None}


def build_strategy_context(db: Session, symbol: str) -> dict:
    """组装输入 context。返回 {"context": {...}, "sources": [...], "errors": [...]}，
    单个数据源失败不影响整体（errors 里记录，AI 会看到"数据不足"的部分）。"""
    context: dict = {}
    sources: list[str] = []
    errors: list[str] = []

    def _merge(env: dict | None) -> None:
        if env is None:
            return
        sources.extend(env.get("sources") or [])
        errors.extend(env.get("partial_failures") or [])

    try:
        overview_env = orchestrator.build_overview(db, symbol)
        _merge(overview_env)
        context["overview"] = _pick(overview_env["data"], _CONTEXT_OVERVIEW_KEYS)
    except orchestrator.FundamentalsNotFound as e:
        errors.append(f"overview: {e}")

    try:
        fin_env = orchestrator.build_financials(db, symbol)
        _merge(fin_env)
        fin_data = fin_env["data"]
        context["financials"] = {
            "growth_and_margins": fin_data.get("growth_and_margins"),
            "red_flags": fin_data.get("red_flags"),
        }
    except orchestrator.FundamentalsNotFound as e:
        errors.append(f"financials: {e}")

    try:
        val_env = orchestrator.build_valuation(db, symbol)
        _merge(val_env)
        val_data = val_env["data"]
        context["valuation"] = {
            "current": _pick(
                val_data.get("current") or {},
                ["price", "pe_ttm", "pe_forward", "pb", "market_cap", "dividend_yield"],
            ),
            "historical_pe_percentile": (val_data.get("historical") or {}).get("pe"),
        }
    except (orchestrator.FundamentalsNotFound, Exception) as e:
        errors.append(f"valuation: {e}")

    try:
        ear_env = orchestrator.build_earnings(db, symbol)
        _merge(ear_env)
        ear_data = ear_env["data"]
        context["earnings"] = {
            **_pick(ear_data, _EARNINGS_KEYS),
            "recent_eps_surprises": (ear_data.get("eps_surprise_history") or [])[-6:],
            "post_earnings_reactions": ear_data.get("post_earnings_reactions") or [],
        }
    except Exception as e:
        errors.append(f"earnings: {e}")

    try:
        risk_env = orchestrator.build_risks(db, symbol)
        _merge(risk_env)
        context["risks"] = {"items": risk_env["data"].get("items") or []}
    except Exception as e:
        errors.append(f"risks: {e}")

    try:
        context["kline_summary"] = _build_kline_summary(db, symbol)
        sources.append("Yahoo Finance 历史K线（yfinance）")
    except kline_client.KlineError as e:
        errors.append(f"kline: {e}")

    if errors:
        context["_data_errors"] = errors
    return {"context": context, "sources": list(dict.fromkeys(sources)), "errors": errors}


def _build_kline_summary(db: Session, symbol: str) -> dict:
    """日K末 60 根的技术面摘要：区间涨跌、均线关系、MACD 交叉、RSI、量能。"""
    candles = kline_client.get_kline(db, symbol, "1d")
    if not candles:
        raise kline_client.KlineError("K线数据为空")
    last = candles[-1]

    def _pct(n: int) -> Optional[float]:
        if len(candles) <= n:
            return None
        base = candles[-1 - n]["close"]
        return round((last["close"] / base - 1) * 100, 2) if base else None

    ma5, ma20, ma60 = last.get("ma5"), last.get("ma20"), last.get("ma60")
    prev = candles[-2] if len(candles) >= 2 else None
    macd_bullish = None
    if prev is not None and last.get("macdDif") is not None and last.get("macdDea") is not None:
        if prev.get("macdDif") is not None and prev.get("macdDea") is not None:
            macd_bullish = prev["macdDif"] <= prev["macdDea"] and last["macdDif"] > last["macdDea"]

    closes = [c["close"] for c in candles[-25:] if c.get("close")]
    volumes = [c["volume"] for c in candles[-25:] if c.get("volume")]
    return {
        "as_of": last.get("time"),
        "last_close": last.get("close"),
        "change_20d_pct": _pct(20),
        "change_60d_pct": _pct(60),
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "ma_bullish": bool(ma20 and ma60 and last.get("close") and ma20 > ma60 and last["close"] > ma20),
        "ma_bearish": bool(ma20 and ma60 and last.get("close") and ma20 < ma60 and last["close"] < ma20),
        "macd_dif": last.get("macdDif"),
        "macd_dea": last.get("macdDea"),
        "macd_hist": last.get("macdHist"),
        "macd_golden_cross": bool(macd_bullish),
        "rsi14": last.get("rsi"),
        "avg_volume_5d": round(sum(volumes[-5:]) / min(5, len(volumes)), 0) if volumes else None,
        "avg_volume_20d": round(sum(volumes) / len(volumes), 0) if volumes else None,
        "recent_closes": closes[-10:],
    }


def build_system_instruction(strategy: StockStrategy, symbol: str) -> str:
    """把策略（描述 + rules）渲染成 AI 的分析框架指令。"""
    try:
        rules = json.loads(strategy.rules_json or "{}")
    except json.JSONDecodeError:
        rules = {}

    focus_names = {
        "financials": "基本面（营收/利润/ROE/负债等 SEC 财务数据）",
        "valuation": "估值（当前 PE/PB 与历史分位）",
        "kline": "技术面（K线/均线/MACD/RSI/量能）",
        "risks": "风险（财务红旗/估值/持仓集中度）",
    }
    focus = "、".join(focus_names.get(f, f) for f in rules.get("focus") or ["financials", "valuation", "kline", "risks"])

    risk_label = {"low": "低（保守，宁可错过不可做错）", "medium": "中（平衡收益与风险）", "high": "高（激进，容忍较大回撤）"}.get(
        str(rules.get("risk_preference", "medium")), "中"
    )

    sections = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(rules.get("output_sections") or ["策略结论", "核心逻辑", "关键指标依据", "风险点", "分级结论"]))

    return f"""你是一名专业的个股分析助手。用户使用策略「{strategy.name}」来分析股票 {symbol}，你必须严格按该策略的分析框架和风险偏好输出，不得套用通用模板。

【策略说明】{strategy.description or "（无）"}

【策略规则】
- 重点分析范围：{focus}
- 风险偏好：{risk_label}
- 优先关注的关键因子：{'、'.join(rules.get("key_factors") or [])}
- 买入倾向条件：{json.dumps(rules.get("buy_bias") or {}, ensure_ascii=False)}
- 观望（hold）条件：{rules.get("hold_condition") or "信号中性或数据不足时观望"}
- 回避（avoid）条件：{rules.get("avoid_condition") or "风险显著大于收益时回避"}

【输出要求】
1. 严格按以下小节输出 Markdown（用二级标题 ## 加编号和标题）：
{sections}
2. 只依据用户消息里提供的真实数据做整理和解释，禁止编造任何数据里没有的数字或事件；每个论点引用具体指标数值和数据期间；数据不足的小节必须写"数据不足，无法判断"。
3. 明确区分"数据里的事实"和"你的推断"，推断要说明依据。
4. 绝对不使用"必涨""稳赚""保证""确定"这类确定性措辞；不使用"强烈推荐买入"这类话术。
5. 在全文最后（独立代码块，不要和其他内容混在一起）输出分级结论 JSON，严格使用以下格式：
```json
{{"rating": "buy|hold|avoid", "reason": "一句话结论理由（依据本策略框架）", "key_indicators": [{{"name": "指标名", "value": "指标值", "verdict": "对该策略含义"}}]}}
```
rating 只能取 buy / hold / avoid 三者之一。这个 JSON 块必须放在全文最后且独立成块，便于程序解析。
6. 最后加一行：**仅供研究，不构成投资建议**。"""


def extract_rating_block(markdown: str) -> Optional[dict]:
    """从 markdown 末尾提取分级结论 JSON 块。取最后一个解析成功且 rating 合法的块。"""
    if not markdown:
        return None
    for block in reversed(_RATING_BLOCK_RE.findall(markdown)):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("rating") in _RATING_WHITELIST:
            return data
    return None


def extract_rating_fallback(db: Session, system_instruction: str, user_content: str) -> Optional[dict]:
    """glm 结构化兜底：正则提取失败时用强制 JSON 输出再试一次。zhipu key 未配置则跳过。"""
    try:
        api_key, model = get_zhipu_config(db)
    except Exception:
        return None
    if not api_key:
        return None
    try:
        data = generate_structured(
            system_instruction=system_instruction,
            user_content=user_content,
            api_key=api_key,
            model=model,
            temperature=0.1,
        )
        if isinstance(data, dict) and data.get("rating") in _RATING_WHITELIST:
            return data
    except Exception as e:
        logger.warning(f"策略结论 glm 兜底失败: {e}")
    return None
