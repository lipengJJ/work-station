"""权重公式（榜位 + 出现频次 + 高位次数）单测。"""
from __future__ import annotations

from app.hotlist.services.ranking import DEFAULT_WEIGHT_CONFIG, calculate_weight, decay_factor


def test_calculate_weight_no_ranks_is_zero():
    assert calculate_weight([], count=0) == 0.0


def test_calculate_weight_ignores_off_list_zeros():
    # rank=0 表示脱榜，参与计算时应被忽略
    assert calculate_weight([0, 0], count=1) == 0.0


def test_calculate_weight_top_rank_scores_higher_than_low_rank():
    top = calculate_weight([1], count=1)
    low = calculate_weight([10], count=1)
    assert top > low


def test_calculate_weight_higher_frequency_scores_higher():
    once = calculate_weight([5], count=1)
    often = calculate_weight([5], count=10)
    assert often > once


def test_calculate_weight_matches_manual_formula():
    ranks = [1, 2, 3]
    count = 3
    threshold = 5
    rank_score_sum = sum(11 - min(r, 10) for r in ranks)
    n = len(ranks)
    rank_weight = (rank_score_sum / n) * 10
    frequency_weight = min(count, 10) * 10
    hotness_weight = (sum(1 for r in ranks if r <= threshold) / n) * 100
    expected = round(
        rank_weight * DEFAULT_WEIGHT_CONFIG["RANK_WEIGHT"]
        + frequency_weight * DEFAULT_WEIGHT_CONFIG["FREQUENCY_WEIGHT"]
        + hotness_weight * DEFAULT_WEIGHT_CONFIG["HOTNESS_WEIGHT"],
        2,
    )
    assert calculate_weight(ranks, count, rank_threshold=threshold) == expected


def test_calculate_weight_applies_decay_multiplier():
    base = calculate_weight([1], count=1, decay=1.0)
    decayed = calculate_weight([1], count=1, decay=0.5)
    assert decayed == round(base * 0.5, 2)


def test_decay_factor_zero_half_life_means_no_decay():
    assert decay_factor(0, hours_elapsed=1000) == 1.0
    assert decay_factor(-1, hours_elapsed=1000) == 1.0


def test_decay_factor_halves_at_half_life():
    assert decay_factor(24, hours_elapsed=24) == 0.5


def test_decay_factor_decreases_over_time():
    assert decay_factor(24, hours_elapsed=48) < decay_factor(24, hours_elapsed=24)
