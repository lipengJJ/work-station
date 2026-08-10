"""
把 financials_service 的预警信号、valuation_service 的历史分位、以及最近 8-K 里的
管理层/审计相关事件，翻译成结构化风险项。每一项都带"用了什么数据、触发原因、最近变化、
数据来源、失效条件"——不是打个红黄绿标签就完事。

有几类风险（客户集中度、供应链、诉讼监管、空头拥挤、宏观敏感性）免费数据源里没有结构化
数据可以支撑，明确标"数据不足"，不编。
"""
from __future__ import annotations

_LEVEL_HIGH, _LEVEL_MEDIUM, _LEVEL_LOW, _LEVEL_UNKNOWN = "high", "medium", "low", "unknown"


def _flag_by_key(flags: list[dict], key: str) -> dict | None:
    return next((f for f in flags if f["key"] == key), None)


def _recent_8k_categories(filings: list[dict], categories: set[str], lookback: int = 12) -> list[dict]:
    hits = []
    for f in filings:
        if f["category"] != "8-K":
            continue
        matched = set(f.get("event_categories") or []) & categories
        if matched:
            hits.append({"filed_at": f["filed_at"], "url": f["url"], "matched": sorted(matched)})
        if len(hits) >= lookback:
            break
    return hits


def build_risk_items(red_flags: list[dict], valuation: dict, snapshot: dict, filings: list[dict]) -> list[dict]:
    items: list[dict] = []

    # 1. 估值风险：历史 PE 分位
    pe = valuation.get("pe") or {}
    if pe.get("percentile") is not None:
        pct = pe["percentile"]
        level = _LEVEL_HIGH if pct >= 85 else (_LEVEL_MEDIUM if pct >= 60 else _LEVEL_LOW)
        items.append(
            {
                "key": "valuation_risk", "title": "估值风险", "level": level,
                "trigger": f"当前 TTM PE 处于近 5 年历史 {pct} 分位",
                "data_used": "SEC XBRL 季度财务 + 历史股价推导的 TTM PE 序列",
                "recent_change": f"当前 PE {pe.get('current')}，历史中位数 {pe.get('median')}",
                "source": "SEC EDGAR XBRL + Yahoo Finance 历史股价",
                "invalidation": "PE 回落到历史中位数以下，或盈利增长显著加速消化估值",
            }
        )
    else:
        items.append(_insufficient("valuation_risk", "估值风险", "历史 TTM PE 序列数据不足"))

    # 2. 增长放缓
    growth = _flag_by_key(red_flags, "revenue_growth_trend")
    if growth and growth["result"] != "数据不足":
        level = _LEVEL_HIGH if growth["result"] == "减速" else _LEVEL_LOW
        items.append(
            {
                "key": "growth_slowdown", "title": "增长放缓", "level": level,
                "trigger": growth["detail"], "data_used": "SEC XBRL 季度营收同比序列",
                "recent_change": growth["result"], "source": "SEC EDGAR XBRL Company Facts",
                "invalidation": "连续两个季度营收同比增速回升",
            }
        )
    else:
        items.append(_insufficient("growth_slowdown", "增长放缓", "季度营收同比数据不足"))

    # 3. 利润率下降
    margin = _flag_by_key(red_flags, "gross_margin_trend")
    if margin and margin["result"] != "数据不足":
        level = _LEVEL_HIGH if margin["result"] == "恶化" else _LEVEL_LOW
        items.append(
            {
                "key": "margin_decline", "title": "利润率下降", "level": level,
                "trigger": margin["detail"], "data_used": "SEC XBRL 季度毛利率序列",
                "recent_change": margin["result"], "source": "SEC EDGAR XBRL Company Facts",
                "invalidation": "毛利率连续两个季度环比改善",
            }
        )
    else:
        items.append(_insufficient("margin_decline", "利润率下降", "季度毛利率数据不足"))

    # 4. 现金流恶化
    fcf = _flag_by_key(red_flags, "ni_fcf_divergence")
    if fcf and fcf["result"] != "数据不足":
        level = _LEVEL_HIGH if fcf["result"] == "背离" else _LEVEL_LOW
        items.append(
            {
                "key": "cashflow_deterioration", "title": "现金流恶化", "level": level,
                "trigger": fcf["detail"], "data_used": "SEC XBRL 经营现金流、资本开支序列",
                "recent_change": fcf["result"], "source": "SEC EDGAR XBRL Company Facts",
                "invalidation": "自由现金流同比重新跟上净利润同比增速",
            }
        )
    else:
        items.append(_insufficient("cashflow_deterioration", "现金流恶化", "自由现金流同比数据不足"))

    # 5/6. 应收账款、库存异常
    for key, title in [("receivables_vs_revenue", "应收账款异常"), ("inventory_vs_revenue", "库存异常")]:
        flag = _flag_by_key(red_flags, key)
        if flag and flag["result"] != "数据不足":
            level = _LEVEL_HIGH if flag["result"] == "是" else _LEVEL_LOW
            items.append(
                {
                    "key": key, "title": title, "level": level,
                    "trigger": flag["detail"], "data_used": "SEC XBRL 资产负债表 + 营收序列",
                    "recent_change": flag["result"], "source": "SEC EDGAR XBRL Company Facts",
                    "invalidation": "同比增速回落到与营收增速相近水平",
                }
            )
        else:
            items.append(_insufficient(key, title, "相关季度数据不足"))

    # 7. 高负债 + 8. 再融资和股本稀释
    debt_flag = _flag_by_key(red_flags, "debt_growth")
    debt_to_equity = snapshot.get("debt_to_equity")
    if debt_to_equity is not None:
        level = _LEVEL_HIGH if debt_to_equity > 150 else (_LEVEL_MEDIUM if debt_to_equity > 80 else _LEVEL_LOW)
        items.append(
            {
                "key": "high_leverage", "title": "高负债", "level": level,
                "trigger": f"负债权益比 {debt_to_equity}" + (f"，{debt_flag['detail']}" if debt_flag and debt_flag['result']!='数据不足' else ""),
                "data_used": "yfinance 快照 debtToEquity + SEC 有息负债序列",
                "recent_change": debt_flag["result"] if debt_flag else "数据不足",
                "source": "Yahoo Finance + SEC EDGAR XBRL",
                "invalidation": "负债权益比或有息负债同比增速明显回落",
            }
        )
    else:
        items.append(_insufficient("high_leverage", "高负债", "负债权益比数据不足"))

    dilution_flag = _flag_by_key(red_flags, "share_dilution")
    if dilution_flag and dilution_flag["result"] != "数据不足":
        level = _LEVEL_MEDIUM if dilution_flag["result"] == "是" else _LEVEL_LOW
        items.append(
            {
                "key": "dilution_refinancing", "title": "再融资和股本稀释", "level": level,
                "trigger": dilution_flag["detail"], "data_used": "SEC XBRL 稀释后加权股数序列",
                "recent_change": dilution_flag["result"], "source": "SEC EDGAR XBRL Company Facts",
                "invalidation": "稀释后股数同比转为持平或下降（回购生效）",
            }
        )
    else:
        items.append(_insufficient("dilution_refinancing", "再融资和股本稀释", "加权股数同比数据不足"))

    # 9. 管理层变动（最近 8-K Item 5.02）
    mgmt_hits = _recent_8k_categories(filings, {"管理层变动"})
    items.append(
        {
            "key": "management_change", "title": "管理层变动", "level": _LEVEL_MEDIUM if mgmt_hits else _LEVEL_LOW,
            "trigger": f"最近 {len(mgmt_hits)} 份 8-K 涉及董事/高管变动 (Item 5.02)" if mgmt_hits else "近期没有相关 8-K",
            "data_used": "SEC 8-K Item 5.02 分类", "recent_change": [h["filed_at"] for h in mgmt_hits[:5]],
            "source": "SEC EDGAR 8-K", "invalidation": "不适用，需持续跟踪新增披露",
        }
    )

    # 10. 审计和财务重述（8-K Item 4.01/4.02）
    audit_hits = _recent_8k_categories(filings, {"会计师变更", "财务重述"})
    items.append(
        {
            "key": "audit_restatement", "title": "审计和财务重述", "level": _LEVEL_HIGH if audit_hits else _LEVEL_LOW,
            "trigger": f"最近 {len(audit_hits)} 份 8-K 涉及会计师变更或财务重述 (Item 4.01/4.02)" if audit_hits else "近期没有相关 8-K",
            "data_used": "SEC 8-K Item 4.01/4.02 分类", "recent_change": [h["filed_at"] for h in audit_hits[:5]],
            "source": "SEC EDGAR 8-K", "invalidation": "不适用，需持续跟踪新增披露",
        }
    )

    # 11~15：免费数据源覆盖不到的
    for key, title, needs in [
        ("customer_concentration", "客户集中度", "10-K 客户集中度披露文本（需要额外的文档解析/NLP，本版未接入）"),
        ("supply_chain", "供应链风险", "供应链结构化数据（需要第三方数据源）"),
        ("litigation_regulatory", "法律诉讼和监管风险", "诉讼跟踪数据源（需要 Finnhub/FMP 或专门法律数据库）"),
        ("short_interest_crowding", "空头拥挤", "做空比例数据（需要 Finnhub/FMP 等付费数据源）"),
        ("macro_sensitivity", "宏观敏感性", "系统性因子暴露分析（需要额外的量化模型）"),
    ]:
        items.append(
            {
                "key": key, "title": title, "level": _LEVEL_UNKNOWN,
                "trigger": "数据不足，暂无法自动评估", "data_used": None, "recent_change": None,
                "source": None, "invalidation": None, "needs_data_source": needs,
            }
        )

    return items


def _insufficient(key: str, title: str, reason: str) -> dict:
    return {
        "key": key, "title": title, "level": _LEVEL_UNKNOWN,
        "trigger": f"数据不足：{reason}", "data_used": None, "recent_change": None,
        "source": "SEC EDGAR XBRL Company Facts", "invalidation": None,
    }
