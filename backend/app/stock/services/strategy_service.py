"""
策略驱动的 AI 个股分析 —— 策略库服务：内置预设 + 用户自定义策略的 CRUD。

预设策略在首次访问列表时幂等 seed（count==0 才插入），不依赖 migration/启动钩子，
避免建表时序问题。预设策略的 rules 不允许修改（保持内置框架），名称/描述允许改。
删除策略时若已有报告引用，直接拒删，避免历史报告失去引用主体。
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.stock.models.stock_strategy import StockStrategy
from app.stock.models.stock_strategy_report import StockStrategyReport

# ------------------------------------------------------------------ 内置预设策略 ----

PRESET_STRATEGIES: list[dict] = [
    {
        "name": "价值投资",
        "description": "以基本面为核心的中长期策略：看重成长质量、盈利能力、估值水平与财务稳健性，只在估值合理且有安全边际时考虑买入。",
        "rules": {
            "focus": ["financials", "valuation", "risks"],
            "risk_preference": "low",
            "key_factors": ["revenue_growth", "margin", "roe", "pe_percentile", "debt", "fcf"],
            "buy_bias": {"pe_max": 25, "margin_min": 20, "roe_min": 15, "pe_percentile_max": 60},
            "hold_condition": "估值合理但缺乏明显安全边际，或财务与估值信号矛盾时观望",
            "avoid_condition": "估值显著高于历史区间、盈利能力恶化或负债率快速上升",
            "output_sections": ["策略结论", "核心逻辑", "关键指标依据", "风险点", "分级结论"],
        },
    },
    {
        "name": "趋势交易",
        "description": "以技术面为核心的中短期策略：跟随均线排列、MACD、RSI 与量能变化，只在趋势明确且量价配合时考虑买入。",
        "rules": {
            "focus": ["kline", "risks"],
            "risk_preference": "high",
            "key_factors": ["ma_trend", "macd", "rsi", "volume", "change_20d"],
            "buy_bias": {"ma_bullish": True, "rsi_max": 60, "macd_bullish": True},
            "hold_condition": "均线纠缠或指标中性、趋势方向不明确时观望",
            "avoid_condition": "均线空头排列、破位下跌或量价背离",
            "output_sections": ["策略结论", "核心逻辑", "关键指标依据", "风险点", "分级结论"],
        },
    },
    {
        "name": "稳健防守",
        "description": "防御型策略：偏好大盘蓝筹、低估值、低波动与稳定分红，以回撤控制优先，追求确定性而不是弹性。",
        "rules": {
            "focus": ["financials", "valuation", "kline", "risks"],
            "risk_preference": "low",
            "key_factors": ["dividend", "volatility", "pe_percentile", "debt", "roe", "rsi"],
            "buy_bias": {"dividend_min": 2, "pe_max": 30, "rsi_max": 45, "pe_percentile_max": 70},
            "hold_condition": "股息与估值尚可但波动加大，或指标信号中性时观望",
            "avoid_condition": "波动率显著放大、估值偏高或基本面转弱",
            "output_sections": ["策略结论", "核心逻辑", "关键指标依据", "风险点", "分级结论"],
        },
    },
]


def _to_dict(strategy: StockStrategy) -> dict:
    return {
        "id": strategy.id,
        "name": strategy.name,
        "description": strategy.description,
        "is_preset": strategy.is_preset,
        "rules": json.loads(strategy.rules_json or "{}"),
        "created_at": strategy.created_at.isoformat() if strategy.created_at else None,
        "updated_at": strategy.updated_at.isoformat() if strategy.updated_at else None,
    }


def seed_if_empty(db: Session) -> None:
    """幂等插入内置预设策略（库为空时）。"""
    if db.query(StockStrategy).count() > 0:
        return
    for preset in PRESET_STRATEGIES:
        db.add(
            StockStrategy(
                name=preset["name"],
                description=preset["description"],
                is_preset=True,
                rules_json=json.dumps(preset["rules"], ensure_ascii=False),
            )
        )
    db.commit()


def list_strategies(db: Session) -> list[dict]:
    seed_if_empty(db)
    rows = db.query(StockStrategy).order_by(StockStrategy.is_preset.desc(), StockStrategy.id.asc()).all()
    return [_to_dict(r) for r in rows]


def get_strategy(db: Session, strategy_id: int) -> StockStrategy | None:
    return db.get(StockStrategy, strategy_id)


def create_strategy(db: Session, name: str, description: str, rules: dict) -> dict:
    row = StockStrategy(
        name=name,
        description=description,
        is_preset=False,
        rules_json=json.dumps(rules, ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_dict(row)


def update_strategy(db: Session, strategy_id: int, name: str, description: str, rules: dict) -> StockStrategy | None:
    row = db.get(StockStrategy, strategy_id)
    if not row:
        return None
    row.name = name
    row.description = description
    if not row.is_preset:
        # 预设策略只允许改名称/描述，rules 保持内置框架
        row.rules_json = json.dumps(rules, ensure_ascii=False)
    db.commit()
    db.refresh(row)
    return row


def delete_strategy(db: Session, strategy_id: int) -> tuple[bool, str]:
    """返回 (是否成功, 失败原因)。有报告引用时拒绝删除。"""
    row = db.get(StockStrategy, strategy_id)
    if not row:
        return False, "策略不存在"
    referenced = (
        db.query(StockStrategyReport).filter(StockStrategyReport.strategy_id == strategy_id).first()
    )
    if referenced:
        return False, "该策略已有分析报告引用，不能删除（可以改个新名字继续用）"
    db.delete(row)
    db.commit()
    return True, ""
