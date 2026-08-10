"""
把 SEC XBRL Company Facts 的原始事实（成千上万条按 concept 分组的时间点数值）整理成
季度/年度的标准财务指标序列，并在此基础上算增长率、利润率和几个专业研究关注的"预警信号"。

SEC 的原始事实里，同一个 concept（比如营收）在一份 10-Q 里经常同时出现"当季"和
"本财年累计"两条记录，还可能因为后续更正被重复披露。这里用 XBRL 的 frame 字段区分：
frame 形如 "CY2026Q1" 的是 SEC 自己按日历季度对齐算出来的离散单季度值，"CY2026" 是年度值，
"CY2026Q1I" 是某个时点的资产负债表快照（instant，没有 start，只有 end）——只挑带 frame 的
条目，同一个 end 日期出现多次时留 filed 最晚的那条（覆盖掉更早的、后来被修正过的数字）。
不是所有公司都用同一个 XBRL 标签报同一个科目，所以每个指标配了几个常见备选标签，按优先级
第一个有数据的用哪个。
"""
from __future__ import annotations

import re
from typing import Optional

_DURATION_CONCEPTS: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfServices"],
    "gross_profit": ["GrossProfit"],
    "rnd_expense": ["ResearchAndDevelopmentExpense"],
    "sga_expense": ["SellingGeneralAndAdministrativeExpense"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "eps_basic": ["EarningsPerShareBasic"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "dep_amort": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet", "DepreciationAndAmortization"],
}

# EPS 和加权平均股数是"period 内的平均值"，不是能跨期累加的流量指标——Q1+Q2+Q3+Q4 的加权
# 股数加起来完全不等于全年加权股数，用"年度-累计"去反推第四季度在数学上就是错的（实测出现过
# 反推出负数股数这种明显荒谬的结果）。这几个指标只用 SEC 自己打了干净 frame 标签的离散
# 季度值，宁可某些季度缺数据，也不能算出一个错误但看起来"有值"的数字。
_NON_ADDITIVE_METRICS = {"eps_diluted", "eps_basic", "diluted_shares"}

_INSTANT_CONCEPTS: dict[str, list[str]] = {
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "stockholders_equity": ["StockholdersEquity"],
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "long_term_debt": ["LongTermDebtNoncurrent"],
    "short_term_debt": ["LongTermDebtCurrent", "ShortTermBorrowings"],
    "shares_outstanding": ["CommonStockSharesOutstanding"],
    "receivables": ["AccountsReceivableNetCurrent"],
    "inventory": ["InventoryNet"],
}

_QUARTER_FRAME_RE = re.compile(r"^CY\d{4}Q[1-4]$")
_ANNUAL_FRAME_RE = re.compile(r"^CY\d{4}$")
_INSTANT_FRAME_RE = re.compile(r"^CY\d{4}Q[1-4]I$")


class FinancialsError(Exception):
    pass


def _first_available_concept(gaap: dict, names: list[str]) -> Optional[dict]:
    for name in names:
        concept = gaap.get(name)
        if concept and concept.get("units"):
            return concept
    return None


def _dedupe_latest_filed(entries: list[dict], frame_re: re.Pattern) -> dict[str, dict]:
    points: dict[str, dict] = {}
    for e in entries:
        frame = e.get("frame", "")
        if not frame_re.match(frame):
            continue
        key = e["end"]
        existing = points.get(key)
        if not existing or e.get("filed", "") >= existing.get("filed", ""):
            points[key] = e
    return points


def _derive_quarterly_from_cumulative(entries: list[dict], annual_entries: list[dict]) -> dict[str, dict]:
    """
    现金流量表科目（经营现金流、资本开支等）在 10-Q 里几乎都是"本财年累计"披露，只有
    第一季度的累计值恰好等于单季度值、能拿到干净的 frame 标签；Q2/Q3 的单季度值 SEC
    不会帮你算，要自己拿累计值做差分：Q2 = 累计(Q2) - 累计(Q1)，Q3 = 累计(Q3) - 累计(Q2)，
    Q4 = 年度(10-K) - 累计(Q3)。

    分组绝对不能用 XBRL 的 fy/fp 字段——SEC 对"本季新披露的数字"和"本季 10-Q 里作为对比
    列出的上年同期数字"经常打上同一个 fy/fp（实测 AAPL 一份 fy=2026/fp=Q1 的 10-Q 里同时有
    2024-12-28 结束的上年同期数据和 2025-12-27 结束的本期数据，fy/fp 完全一样），按 fy/fp
    分组会把两个不同财年的数字错误地拼到一起。改成按 start（财年起点，是具体日期，不会有
    歧义）分组，同一组内按 duration 从短到长排序得到 Q1/Q2/Q3 累计值，Q4 用 start 日期
    完全相同的年度（10-K）条目去匹配，全程只用日期比较，不依赖任何厂商自己打的标签。
    """
    cumulative_by_start: dict[str, dict[str, dict]] = {}
    for e in entries:
        if e.get("fp") not in ("Q1", "Q2", "Q3"):
            continue
        start, end = e.get("start"), e.get("end")
        if not start or not end:
            continue
        bucket = cumulative_by_start.setdefault(start, {})
        existing = bucket.get(end)
        if not existing or e.get("filed", "") >= existing.get("filed", ""):
            bucket[end] = e

    annual_by_start: dict[str, dict] = {}
    for e in annual_entries:
        start = e.get("start")
        if not start:
            continue
        existing = annual_by_start.get(start)
        if not existing or e.get("filed", "") >= existing.get("filed", ""):
            annual_by_start[start] = e

    derived: dict[str, dict] = {}
    for start, by_end in cumulative_by_start.items():
        ordered = sorted(by_end.values(), key=lambda e: e["end"])  # 同一财年起点，end 越晚 = 累计跨度越长
        if len(ordered) < 1:
            continue
        q1 = ordered[0]
        derived[q1["end"]] = {"end": q1["end"], "val": q1["val"], "filed": q1["filed"]}
        prev = q1
        for cur in ordered[1:]:
            derived[cur["end"]] = {"end": cur["end"], "val": cur["val"] - prev["val"], "filed": cur["filed"]}
            prev = cur
        fy_total = annual_by_start.get(start)
        if fy_total:
            derived[fy_total["end"]] = {"end": fy_total["end"], "val": fy_total["val"] - prev["val"], "filed": fy_total["filed"]}
    return derived


def _extract_duration_points(concept: dict, allow_cumulative_derivation: bool) -> tuple[list[dict], list[dict]]:
    """返回 (季度点位列表, 年度点位列表)，按 end 日期升序。季度优先用 SEC 的 frame 标签
    （更权威），frame 没覆盖到的日期，对"可累加"的流量指标用累计值差分补上
    （allow_cumulative_derivation=False 的科目——EPS、加权股数——不做这个补全，见上面注释）。"""
    unit_key = next(iter(concept["units"]), None)
    if not unit_key:
        return [], []
    entries = concept["units"][unit_key]
    quarterly = _dedupe_latest_filed(entries, _QUARTER_FRAME_RE)
    annual = _dedupe_latest_filed(entries, _ANNUAL_FRAME_RE)

    if allow_cumulative_derivation:
        annual_entries_with_start = [e for e in entries if _ANNUAL_FRAME_RE.match(e.get("frame", "")) and e.get("start")]
        for end, point in _derive_quarterly_from_cumulative(entries, annual_entries_with_start).items():
            quarterly.setdefault(end, point)

    return [quarterly[k] for k in sorted(quarterly)], [annual[k] for k in sorted(annual)]


def _extract_instant_points(concept: dict) -> list[dict]:
    unit_key = next(iter(concept["units"]), None)
    if not unit_key:
        return []
    points = _dedupe_latest_filed(concept["units"][unit_key], _INSTANT_FRAME_RE)
    return [points[k] for k in sorted(points)]


def extract_all_series(company_facts: dict) -> dict:
    """
    返回 {"quarterly": {metric: [{end, val, fy, fp, form, filed, accn}, ...]},
          "annual": {metric: [...]},
          "instant": {metric: [...]}}
    某个指标这家公司完全没披露过就是空列表，前端/后续计算要按"暂无数据"处理，不能当 0。
    """
    gaap = (company_facts.get("facts") or {}).get("us-gaap") or {}

    quarterly: dict[str, list[dict]] = {}
    annual: dict[str, list[dict]] = {}
    for metric, concept_names in _DURATION_CONCEPTS.items():
        concept = _first_available_concept(gaap, concept_names)
        if not concept:
            quarterly[metric] = []
            annual[metric] = []
            continue
        q, a = _extract_duration_points(concept, allow_cumulative_derivation=metric not in _NON_ADDITIVE_METRICS)
        quarterly[metric] = q
        annual[metric] = a

    instant: dict[str, list[dict]] = {}
    for metric, concept_names in _INSTANT_CONCEPTS.items():
        concept = _first_available_concept(gaap, concept_names)
        instant[metric] = _extract_instant_points(concept) if concept else []

    return {"quarterly": quarterly, "annual": annual, "instant": instant}


# ------------------------------------------------------------------ 派生计算 ----

def _values(points: list[dict]) -> list[float]:
    return [p["val"] for p in points]


def _yoy_growth(points: list[dict], periods_back: int) -> Optional[float]:
    """periods_back=4 用于季度同比，=1 用于年度同比。"""
    if len(points) <= periods_back:
        return None
    latest = points[-1]["val"]
    base = points[-1 - periods_back]["val"]
    if not base:
        return None
    return round((latest - base) / abs(base) * 100, 2)


def build_growth_and_margins(series: dict) -> dict:
    q = series["quarterly"]
    a = series["annual"]

    def margin_series(numerator: list[dict], denominator: list[dict]) -> list[dict]:
        denom_by_end = {p["end"]: p["val"] for p in denominator}
        out = []
        for p in numerator:
            d = denom_by_end.get(p["end"])
            if d:
                out.append({"end": p["end"], "val": round(p["val"] / d * 100, 2)})
        return out

    return {
        "quarterly": {
            "revenue_yoy": [
                {"end": q["revenue"][i]["end"], "val": g}
                for i in range(4, len(q["revenue"]))
                if (g := _yoy_growth(q["revenue"][: i + 1], 4)) is not None
            ],
            "net_income_yoy": [
                {"end": q["net_income"][i]["end"], "val": g}
                for i in range(4, len(q["net_income"]))
                if (g := _yoy_growth(q["net_income"][: i + 1], 4)) is not None
            ],
            "gross_margin": margin_series(q["gross_profit"], q["revenue"]),
            "operating_margin": margin_series(q["operating_income"], q["revenue"]),
            "net_margin": margin_series(q["net_income"], q["revenue"]),
            "free_cash_flow": [
                {"end": ocf["end"], "val": ocf["val"] - capex}
                for ocf in q["operating_cash_flow"]
                if (capex := next((c["val"] for c in q["capex"] if c["end"] == ocf["end"]), None)) is not None
            ],
        },
        "annual": {
            "revenue_yoy": [
                {"end": a["revenue"][i]["end"], "val": g}
                for i in range(1, len(a["revenue"]))
                if (g := _yoy_growth(a["revenue"][: i + 1], 1)) is not None
            ],
            "net_income_yoy": [
                {"end": a["net_income"][i]["end"], "val": g}
                for i in range(1, len(a["net_income"]))
                if (g := _yoy_growth(a["net_income"][: i + 1], 1)) is not None
            ],
            "gross_margin": margin_series(a["gross_profit"], a["revenue"]),
            "operating_margin": margin_series(a["operating_income"], a["revenue"]),
            "net_margin": margin_series(a["net_income"], a["revenue"]),
            "free_cash_flow": [
                {"end": ocf["end"], "val": ocf["val"] - capex}
                for ocf in a["operating_cash_flow"]
                if (capex := next((c["val"] for c in a["capex"] if c["end"] == ocf["end"]), None)) is not None
            ],
        },
    }


def build_red_flags(series: dict, growth: dict) -> list[dict]:
    """
    每一项都注明"使用的数据"和判断依据，不是简单打个标签——和风险模块（risk_service）
    共用同一套计算结果，这里只负责把原始序列翻译成"是/否/数据不足"的结论。
    """
    flags: list[dict] = []
    q = series["quarterly"]

    def latest_two(vals: list[dict]) -> Optional[tuple[float, float]]:
        if len(vals) < 2:
            return None
        return vals[-2]["val"], vals[-1]["val"]

    # 1. 营收增速加速/减速
    rev_yoy = growth["quarterly"]["revenue_yoy"]
    pair = latest_two(rev_yoy)
    if pair:
        prev, latest = pair
        flags.append(
            {
                "key": "revenue_growth_trend",
                "title": "营收增速趋势",
                "result": "加速" if latest > prev else ("减速" if latest < prev else "持平"),
                "detail": f"最近季度营收同比 {latest}%，上一季度同比 {prev}%",
            }
        )
    else:
        flags.append({"key": "revenue_growth_trend", "title": "营收增速趋势", "result": "数据不足", "detail": "季度同比数据不足两期"})

    # 2. 利润增速是否跟上营收
    ni_yoy = growth["quarterly"]["net_income_yoy"]
    if rev_yoy and ni_yoy:
        rev_latest = rev_yoy[-1]["val"]
        ni_latest = next((x["val"] for x in ni_yoy if x["end"] == rev_yoy[-1]["end"]), None)
        if ni_latest is not None:
            flags.append(
                {
                    "key": "profit_vs_revenue",
                    "title": "利润增速是否跟上营收",
                    "result": "是" if ni_latest >= rev_latest else "否",
                    "detail": f"最近季度净利润同比 {ni_latest}% vs 营收同比 {rev_latest}%",
                }
            )
        else:
            flags.append({"key": "profit_vs_revenue", "title": "利润增速是否跟上营收", "result": "数据不足", "detail": "净利润同比数据缺失"})
    else:
        flags.append({"key": "profit_vs_revenue", "title": "利润增速是否跟上营收", "result": "数据不足", "detail": "营收或净利润同比数据不足"})

    # 3. 毛利率是否持续改善（最近4个季度环比是否多数上升）
    gm = growth["quarterly"]["gross_margin"]
    if len(gm) >= 4:
        recent = gm[-4:]
        deltas = [recent[i]["val"] - recent[i - 1]["val"] for i in range(1, len(recent))]
        improving = sum(1 for d in deltas if d > 0)
        flags.append(
            {
                "key": "gross_margin_trend",
                "title": "毛利率是否持续改善",
                "result": "改善" if improving >= 2 else ("恶化" if improving == 0 else "波动"),
                "detail": f"最近4个季度毛利率: {[r['val'] for r in recent]}",
            }
        )
    else:
        flags.append({"key": "gross_margin_trend", "title": "毛利率是否持续改善", "result": "数据不足", "detail": "毛利率季度数据不足4期"})

    # 4. 净利润和自由现金流是否背离
    fcf = growth["quarterly"]["free_cash_flow"]
    if len(fcf) >= 5 and len(q["net_income"]) >= 5:
        fcf_yoy = _yoy_growth(fcf, 4)
        ni_yoy_latest = _yoy_growth(q["net_income"], 4)
        if fcf_yoy is not None and ni_yoy_latest is not None:
            diverged = (fcf_yoy < 0 < ni_yoy_latest) or (ni_yoy_latest < 0 < fcf_yoy) or abs(fcf_yoy - ni_yoy_latest) > 30
            flags.append(
                {
                    "key": "ni_fcf_divergence",
                    "title": "净利润与自由现金流是否背离",
                    "result": "背离" if diverged else "同向",
                    "detail": f"净利润同比 {ni_yoy_latest}% vs 自由现金流同比 {fcf_yoy}%",
                }
            )
        else:
            flags.append({"key": "ni_fcf_divergence", "title": "净利润与自由现金流是否背离", "result": "数据不足", "detail": "自由现金流或净利润同比无法计算"})
    else:
        flags.append({"key": "ni_fcf_divergence", "title": "净利润与自由现金流是否背离", "result": "数据不足", "detail": "自由现金流季度数据不足5期"})

    # 5/6. 应收账款、库存增速 vs 收入增速
    instant = series["instant"]
    for metric, label, key in [("receivables", "应收账款", "receivables_vs_revenue"), ("inventory", "库存", "inventory_vs_revenue")]:
        pts = instant.get(metric, [])
        rev_q = q["revenue"]
        if len(pts) >= 5 and len(rev_q) >= 5:
            metric_yoy = _yoy_growth(pts, 4)
            rev_yoy_latest = _yoy_growth(rev_q, 4)
            if metric_yoy is not None and rev_yoy_latest is not None:
                flags.append(
                    {
                        "key": key,
                        "title": f"{label}增速是否显著高于收入",
                        "result": "是" if metric_yoy - rev_yoy_latest > 15 else "否",
                        "detail": f"{label}同比 {metric_yoy}% vs 营收同比 {rev_yoy_latest}%",
                    }
                )
            else:
                flags.append({"key": key, "title": f"{label}增速是否显著高于收入", "result": "数据不足", "detail": "同比无法计算"})
        else:
            flags.append({"key": key, "title": f"{label}增速是否显著高于收入", "result": "数据不足", "detail": f"{label}季度数据不足5期"})

    # 7. 股本是否持续被稀释
    shares = q["diluted_shares"]
    if len(shares) >= 5:
        shares_yoy = _yoy_growth(shares, 4)
        if shares_yoy is not None:
            flags.append(
                {
                    "key": "share_dilution",
                    "title": "股本是否持续被稀释",
                    "result": "是" if shares_yoy > 1 else "否",
                    "detail": f"稀释后加权股数同比 {shares_yoy}%",
                }
            )
        else:
            flags.append({"key": "share_dilution", "title": "股本是否持续被稀释", "result": "数据不足", "detail": "同比无法计算"})
    else:
        flags.append({"key": "share_dilution", "title": "股本是否持续被稀释", "result": "数据不足", "detail": "股数季度数据不足5期"})

    # 8. 债务是否快速上升
    lt_debt = instant.get("long_term_debt", [])
    st_debt = instant.get("short_term_debt", [])
    if lt_debt:
        debt_by_end: dict[str, float] = {}
        for p in lt_debt:
            debt_by_end[p["end"]] = debt_by_end.get(p["end"], 0) + p["val"]
        for p in st_debt:
            debt_by_end[p["end"]] = debt_by_end.get(p["end"], 0) + p["val"]
        debt_points = [{"end": k, "val": v} for k, v in sorted(debt_by_end.items())]
        if len(debt_points) >= 5:
            debt_yoy = _yoy_growth(debt_points, 4)
            if debt_yoy is not None:
                flags.append(
                    {
                        "key": "debt_growth",
                        "title": "债务是否快速上升",
                        "result": "是" if debt_yoy > 20 else "否",
                        "detail": f"有息负债（短期+长期）同比 {debt_yoy}%",
                    }
                )
            else:
                flags.append({"key": "debt_growth", "title": "债务是否快速上升", "result": "数据不足", "detail": "同比无法计算"})
        else:
            flags.append({"key": "debt_growth", "title": "债务是否快速上升", "result": "数据不足", "detail": "债务季度数据不足5期"})
    else:
        flags.append({"key": "debt_growth", "title": "债务是否快速上升", "result": "数据不足", "detail": "未披露长期负债科目"})

    return flags
