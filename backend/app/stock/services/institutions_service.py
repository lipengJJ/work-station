"""
13F 机构持仓：实测确认 SEC 的免费接口里没有"按股票反查机构持仓"这回事——13F 是机构自己
按季度报的全持仓明细（一份 13F 里可能有几十上百只股票），EDGAR 按"披露方"（机构的 CIK）
索引，不按"被投公司"索引，AAPL 自己的 submissions.json 里就是没有 13F 条目（已用真实
请求验证过）。要拿到"谁持有 AAPL"这种反查视图，只有两条路：

1. 自己下载 SEC 每季度发布的 13F 结构化数据集（全市场，几百 MB 一份），解析里面的
   Information Table，按 CUSIP 匹配到这支股票——工作量和存储成本对这一版来说太重，
   放到"已知限制"里作为后续扩展方向。
2. 接一个已经做好这层聚合的第三方数据源（Finnhub / FMP 的机构持仓接口，通常是付费层级）。

这一版按第十六节"不伪造实现"的原则来：定义好接口和数据形状，配置了对应 API Key 就真的
去请求，没配置就清楚地返回"未配置数据源"状态，前端据此显示引导，不展示任何编造的机构名字
或持仓数字。
"""
from __future__ import annotations

from typing import Optional

import requests
from loguru import logger
from sqlalchemy.orm import Session

from app.common.services.gemini_config import get_config_value

_FINNHUB_KEY_CONFIG_NAME = "finnhub_api_key"
_FMP_KEY_CONFIG_NAME = "fmp_api_key"
_TIMEOUT = 15


class InstitutionsError(Exception):
    pass


def get_institutional_holdings(db: Session, symbol: str) -> dict:
    finnhub_key = get_config_value(db, _FINNHUB_KEY_CONFIG_NAME)
    fmp_key = get_config_value(db, _FMP_KEY_CONFIG_NAME)

    if not finnhub_key and not fmp_key:
        return {
            "configured": False,
            "provider": None,
            "holdings": [],
            "message": "13F 机构持仓需要配置 Finnhub 或 FMP API Key（系统设置 > API配置），SEC 免费接口不提供按股票反查机构持仓的数据。",
            "caveats": _CAVEATS,
        }

    if fmp_key:
        try:
            return _fetch_fmp(symbol, fmp_key)
        except InstitutionsError as e:
            logger.warning(f"FMP 13F 请求失败，尝试 Finnhub: {e}")

    if finnhub_key:
        try:
            return _fetch_finnhub(symbol, finnhub_key)
        except InstitutionsError as e:
            logger.warning(f"Finnhub 13F 请求失败: {e}")
            return {
                "configured": True, "provider": "finnhub", "holdings": [],
                "message": f"已配置数据源但请求失败：{e}", "caveats": _CAVEATS,
            }

    return {
        "configured": True, "provider": "fmp", "holdings": [],
        "message": "已配置数据源但请求失败，请检查 API Key 是否有效或是否为付费功能。", "caveats": _CAVEATS,
    }


def _fetch_finnhub(symbol: str, api_key: str) -> dict:
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/institutional/ownership",
            params={"symbol": symbol, "token": api_key},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        raise InstitutionsError(f"请求 Finnhub 失败: {e}") from e
    if resp.status_code in (401, 403):
        raise InstitutionsError("Finnhub API Key 无权限访问机构持仓接口（通常是付费功能）")
    if resp.status_code != 200:
        raise InstitutionsError(f"Finnhub 返回状态码 {resp.status_code}")
    data = resp.json()
    ownership = data.get("ownership") or []
    return {
        "configured": True, "provider": "finnhub",
        "holdings": [
            {
                "institution": row.get("investorName") or row.get("name"),
                "report_period": data.get("report") or row.get("date"),
                "shares": row.get("share"),
                "shares_change": row.get("change"),
                "market_value": row.get("value"),
            }
            for row in ownership
        ],
        "message": None, "caveats": _CAVEATS,
    }


def _fetch_fmp(symbol: str, api_key: str) -> dict:
    try:
        resp = requests.get(
            f"https://financialmodelingprep.com/api/v3/institutional-holder/{symbol}",
            params={"apikey": api_key},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        raise InstitutionsError(f"请求 FMP 失败: {e}") from e
    if resp.status_code in (401, 403):
        raise InstitutionsError("FMP API Key 无权限访问机构持仓接口（通常是付费功能）")
    if resp.status_code != 200:
        raise InstitutionsError(f"FMP 返回状态码 {resp.status_code}")
    rows: list[dict] = resp.json() or []
    return {
        "configured": True, "provider": "fmp",
        "holdings": [
            {
                "institution": row.get("holder"),
                "report_period": row.get("dateReported"),
                "shares": row.get("shares"),
                "shares_change": row.get("change"),
                "market_value": row.get("marketValue") if "marketValue" in row else None,
            }
            for row in rows
        ],
        "message": None, "caveats": _CAVEATS,
    }


_CAVEATS = [
    "13F 最长可能滞后报告季度结束后 45 天披露，不代表机构当前实时仓位",
    "13F 通常无法看到完整空头仓位（做空、部分衍生品持仓不强制披露）",
    "市值变化可能来自股价波动，不完全等于机构主动加/减仓",
]
