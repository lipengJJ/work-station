"""统一权重公式：把「榜位」这一个信号转成可跨源比较的分数。

移植自 TrendRadar (https://github.com/sansan0/TrendRadar) core/analyzer.py::calculate_news_weight。
中文热榜（decay_half_life_hours=0）恒为纯榜位权重，即 TrendRadar 原本的行为；
arXiv / RSS 等有发布时间的源接入衰减乘数后，一个公式覆盖两类源。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

DEFAULT_WEIGHT_CONFIG: dict[str, float] = {
    "RANK_WEIGHT": 0.6,
    "FREQUENCY_WEIGHT": 0.3,
    "HOTNESS_WEIGHT": 0.1,
}
DEFAULT_RANK_THRESHOLD = 5  # 榜位 <= 该值计入 hotness_weight（高位次数占比）

# 系统设置 > API 配置里可覆盖的三个权重系数（那个页面本来就是任意 name/value 的通用录入界面，
# 不用为这三个 key 改前端代码，直接在页面点「新增配置」填 name=hotlist_rank_weight 等就行）。
WEIGHT_CONFIG_NAMES: dict[str, str] = {
    "RANK_WEIGHT": "hotlist_rank_weight",
    "FREQUENCY_WEIGHT": "hotlist_frequency_weight",
    "HOTNESS_WEIGHT": "hotlist_hotness_weight",
}


def get_weight_config(db: "Session") -> dict[str, float]:
    """从 ApiConfig 读三个权重系数，缺失或非法值时用默认值兜底（单个 key 出问题不影响其余两个）。"""
    from app.common.models import ApiConfig

    config = dict(DEFAULT_WEIGHT_CONFIG)
    rows = (
        db.query(ApiConfig)
        .filter(ApiConfig.name.in_(WEIGHT_CONFIG_NAMES.values()))
        .all()
    )
    values_by_name = {row.name: row.value for row in rows}
    for key, config_name in WEIGHT_CONFIG_NAMES.items():
        raw = values_by_name.get(config_name)
        if raw is None:
            continue
        try:
            config[key] = float(raw)
        except (TypeError, ValueError):
            continue
    return config


def calculate_weight(
    ranks: list[int],
    count: int,
    rank_threshold: int = DEFAULT_RANK_THRESHOLD,
    weight_config: dict[str, float] | None = None,
    decay: float = 1.0,
) -> float:
    """ranks: 该条目历史榜位（0 = 脱榜，计算时忽略）；count: 出现次数（crawl_count）。"""
    weight_config = weight_config or DEFAULT_WEIGHT_CONFIG
    positive_ranks = [r for r in ranks if r > 0]
    if not positive_ranks:
        return 0.0
    n = len(positive_ranks)
    rank_score_sum = sum(11 - min(r, 10) for r in positive_ranks)
    high_rank_count = sum(1 for r in positive_ranks if r <= rank_threshold)

    rank_weight = (rank_score_sum / n) * 10  # 归一到 0~100
    frequency_weight = min(count, 10) * 10
    hotness_weight = (high_rank_count / n) * 100

    base = (
        rank_weight * weight_config["RANK_WEIGHT"]
        + frequency_weight * weight_config["FREQUENCY_WEIGHT"]
        + hotness_weight * weight_config["HOTNESS_WEIGHT"]
    )
    return round(base * decay, 2)


def decay_factor(half_life_hours: float, hours_elapsed: float) -> float:
    """半衰期衰减乘数。half_life_hours <= 0 表示不衰减（中文热榜，靠 stat_date 按天分域，
    本来就没有陈旧问题）；> 0 时用于 arXiv/RSS（24）、HN/GitHub/HF（48）等有发布时间的源。"""
    if half_life_hours <= 0:
        return 1.0
    return 0.5 ** (hours_elapsed / half_life_hours)
