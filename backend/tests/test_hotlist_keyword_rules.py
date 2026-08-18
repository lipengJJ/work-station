"""频率词 DSL 解析与匹配的单测：这部分是移植 TrendRadar 逻辑里最该测的纯函数
（无 IO、回归价值高）。覆盖普通词 OR / 必须词 AND / 排除词 NOT / 正则 / 别名 /
@限量 / [GLOBAL_FILTER] 七种语法。
"""
from __future__ import annotations

import pytest

from app.hotlist.services.keyword_rules import (
    InvalidRegexError,
    _load_word_list,
    _parse_word,
    _word_matches,
    compile_word_regex,
    match_groups,
    matches_word_groups,
    parse_frequency_text,
    validate_words_for_storage,
)


# ------------------------------------------------------------- _parse_word ----
def test_parse_word_plain():
    parsed = _parse_word("京东")
    assert parsed == {"word": "京东", "is_regex": False, "pattern": None, "display_name": None}


def test_parse_word_with_alias():
    parsed = _parse_word("OpenAI => OAI")
    assert parsed["word"] == "OpenAI"
    assert parsed["display_name"] == "OAI"
    assert parsed["is_regex"] is False


def test_parse_word_regex():
    parsed = _parse_word("/京东|刘强东/")
    assert parsed["is_regex"] is True
    assert parsed["word"] == "京东|刘强东"
    assert parsed["pattern"] is not None


def test_parse_word_regex_with_alias():
    parsed = _parse_word("/京东|刘强东/ => 京东系")
    assert parsed["is_regex"] is True
    assert parsed["display_name"] == "京东系"


def test_parse_word_invalid_regex_degrades_to_plain():
    # 原版行为：正则语法错误时静默降级为普通子串（controller 层会先校验拦掉，这里只保证不崩）
    parsed = _parse_word("/(unclosed/")
    assert parsed["is_regex"] is False
    assert parsed["word"] == "/(unclosed/"


# ------------------------------------------------------------ _word_matches ----
def test_word_matches_plain_substring():
    assert _word_matches({"word": "京东", "is_regex": False, "pattern": None}, "今日京东热销")
    assert not _word_matches({"word": "阿里", "is_regex": False, "pattern": None}, "今日京东热销")


def test_word_matches_regex():
    import re

    word = {"word": "京东|刘强东", "is_regex": True, "pattern": re.compile("京东|刘强东", re.IGNORECASE)}
    assert _word_matches(word, "刘强东发声")
    assert not _word_matches(word, "马云发声")


def test_word_matches_backward_compat_string():
    assert _word_matches("京东", "今日京东热销")


# -------------------------------------------------------- matches_word_groups ----
def _group(normal=None, required=None, exclude=None, max_count=0, rule_id=None):
    def _words(items):
        return [_parse_word(w) for w in (items or [])]

    return {
        "rule_id": rule_id,
        "required": _words(required),
        "normal": _words(normal),
        "exclude": _words(exclude),
        "group_key": "test",
        "display_name": "测试组",
        "max_count": max_count,
    }


def test_match_groups_returns_matching_rule_ids():
    groups = [
        _group(rule_id=1, normal=["京东"]),
        _group(rule_id=2, normal=["招聘"]),
        _group(rule_id=3, normal=["阿里"]),
    ]
    assert match_groups("京东双十一招聘信息", groups, []) == [1, 2]


def test_match_groups_respects_global_filters():
    groups = [_group(rule_id=1, normal=["京东"])]
    assert match_groups("京东（广告）", groups, ["广告"]) == []


def test_match_groups_no_match_returns_empty():
    groups = [_group(rule_id=1, normal=["京东"])]
    assert match_groups("阿里发布新品", groups, []) == []


def test_matches_normal_words_or():
    groups = [_group(normal=["京东", "阿里"])]
    assert matches_word_groups("京东今日大促", groups, [], [])
    assert matches_word_groups("阿里发布新品", groups, [], [])
    assert not matches_word_groups("腾讯游戏上线", groups, [], [])


def test_matches_required_words_and():
    groups = [_group(required=["AI", "融资"])]
    assert matches_word_groups("某 AI 公司完成融资", groups, [], [])
    assert not matches_word_groups("某 AI 公司发布新品", groups, [], [])  # 缺「融资」


def test_matches_exclude_words_scoped_to_group():
    groups = [_group(normal=["京东"], exclude=["招聘"])]
    assert matches_word_groups("京东双十一大促", groups, [], [])
    assert not matches_word_groups("京东招聘内推", groups, [], [])


def test_matches_exclude_does_not_leak_to_other_groups():
    """刻意验证的行为差异点：本组的排除词不影响别的组（区别于 TrendRadar 原版的全局 ! 语义）。"""
    groups = [
        _group(normal=["京东"], exclude=["招聘"]),
        _group(normal=["招聘"]),  # 另一组专门收集招聘类新闻，不该被上面那组的排除词波及
    ]
    assert matches_word_groups("字节跳动招聘内推", groups, [], [])


def test_matches_required_and_normal_combined():
    groups = [_group(required=["AI"], normal=["融资", "上市"])]
    assert matches_word_groups("AI 公司完成融资", groups, [], [])
    assert matches_word_groups("AI 公司成功上市", groups, [], [])
    assert not matches_word_groups("AI 公司发新品", groups, [], [])
    assert not matches_word_groups("传统行业完成融资", groups, [], [])  # 缺必须词 AI


def test_matches_global_filters_take_priority():
    groups = [_group(normal=["京东"])]
    assert not matches_word_groups("京东（广告）今日大促", groups, [], ["广告"])


def test_matches_no_groups_matches_everything_unless_globally_filtered():
    assert matches_word_groups("随便什么标题", [], [], [])
    assert not matches_word_groups("随便什么标题（广告）", [], [], ["广告"])


def test_matches_regex_group():
    groups = [_group(normal=["/京东|刘强东/"])]
    assert matches_word_groups("刘强东深夜发文", groups, [], [])
    assert not matches_word_groups("马云深夜发文", groups, [], [])


# ------------------------------------------------------------ 正则安全校验 ----
def test_compile_word_regex_valid():
    pattern = compile_word_regex("京东|刘强东")
    assert pattern.search("刘强东")


def test_compile_word_regex_invalid_raises():
    with pytest.raises(InvalidRegexError):
        compile_word_regex("(unclosed")


def test_compile_word_regex_length_cap():
    with pytest.raises(InvalidRegexError):
        compile_word_regex("a" * 201)


def test_validate_words_for_storage_raises_on_bad_regex():
    words = [{"word": "京东", "is_regex": False}, {"word": "(bad", "is_regex": True}]
    with pytest.raises(InvalidRegexError):
        validate_words_for_storage(words)


def test_validate_words_for_storage_ok():
    words = [{"word": "京东", "is_regex": False}, {"word": "京东|刘强东", "is_regex": True}]
    validate_words_for_storage(words)  # 不抛即通过


# ------------------------------------------------------------- parse_frequency_text ----
def test_parse_frequency_text_basic_groups():
    text = "京东\n阿里\n\n腾讯\n字节"
    groups, global_filters = parse_frequency_text(text)
    assert len(groups) == 2
    assert global_filters == []
    assert [w["word"] for w in groups[0]["normal_words"]] == ["京东", "阿里"]


def test_parse_frequency_text_required_and_exclude_and_limit():
    text = "+AI\n融资\n!广告\n@5"
    groups, _ = parse_frequency_text(text)
    assert len(groups) == 1
    g = groups[0]
    assert [w["word"] for w in g["required_words"]] == ["AI"]
    assert [w["word"] for w in g["normal_words"]] == ["融资"]
    assert [w["word"] for w in g["exclude_words"]] == ["广告"]
    assert g["max_count"] == 5


def test_parse_frequency_text_group_alias():
    text = "[大模型]\nGPT\nClaude"
    groups, _ = parse_frequency_text(text)
    assert groups[0]["display_name"] == "大模型"


def test_parse_frequency_text_global_filter_section():
    text = "京东\n阿里\n\n[GLOBAL_FILTER]\n广告\n推广"
    groups, global_filters = parse_frequency_text(text)
    assert len(groups) == 1
    assert global_filters == ["广告", "推广"]


def test_parse_frequency_text_display_name_fallback_to_word_alias():
    text = "OpenAI => OAI\nClaude"
    groups, _ = parse_frequency_text(text)
    assert groups[0]["display_name"] == "OAI / Claude"


def test_parse_frequency_text_regex_line():
    text = "/京东|刘强东/ => 京东系"
    groups, _ = parse_frequency_text(text)
    word = groups[0]["normal_words"][0]
    assert word["is_regex"] is True
    assert word["display_name"] == "京东系"


def test_parse_frequency_text_end_to_end_matches():
    """七种语法一次性验证：普通词 OR、+必须词 AND、!排除词 NOT、@限量、/正则/、=>别名、GLOBAL_FILTER。

    走完整落库路径（json.dumps 存库格式 → _load_word_list 重新编译正则），
    和 load_rules(db) 实际读出来的形状一致，而不是直接拿 parse_frequency_text
    的存库中间产物喂给 matches_word_groups（那没有 compiled pattern）。
    """
    import json

    text = "[大模型]\n+AI\n/融资|上市/\n!招聘\n@3\n\n[GLOBAL_FILTER]\n广告"
    groups, global_filters = parse_frequency_text(text)
    word_groups = [
        {
            "required": _load_word_list(json.dumps(groups[0]["required_words"])),
            "normal": _load_word_list(json.dumps(groups[0]["normal_words"])),
            "exclude": _load_word_list(json.dumps(groups[0]["exclude_words"])),
            "group_key": "test",
            "display_name": groups[0]["display_name"],
            "max_count": groups[0]["max_count"],
        }
    ]
    assert matches_word_groups("AI 公司完成融资", word_groups, [], global_filters)
    assert matches_word_groups("AI 公司成功上市", word_groups, [], global_filters)
    assert not matches_word_groups("AI 公司春季招聘", word_groups, [], global_filters)  # 排除词命中
    assert not matches_word_groups("传统企业完成融资", word_groups, [], global_filters)  # 缺必须词
    assert not matches_word_groups("AI 公司融资（广告）", word_groups, [], global_filters)  # 全局过滤
    assert groups[0]["max_count"] == 3
