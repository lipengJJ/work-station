"""频率词 DSL 解析与匹配。

移植自 TrendRadar (https://github.com/sansan0/TrendRadar)
trendradar/core/frequency.py，`_parse_word` / `_word_matches` 逐行照搬，
`matches_word_groups` 在原版基础上加了一处刻意改动，其余保持一致。

改动说明：
  1. 配置输入从文本文件换成数据库行：`load_frequency_words(file)` → `load_rules(db)`，
     返回值保持同样的 `(word_groups, filter_words, global_filters)` 三元组，
     下游 `matches_word_groups()` 一行不用改。
  2. exclude_words（原版的 `!` 过滤词）改为按规则（词组）独立生效，不再是原版那种
     「文件里任意一组写了 !词，全局排除所有组」的行为——那是单文件按行顺序解析产生的
     副作用，数据库按行独立存储后没理由继续保留。`matches_word_groups` 因此多检查一个
     `group["exclude"]`，`filter_words` 参数位保留（签名兼容）但恒为空列表。
  3. 正则来自用户输入，本文件的 `compile_word_regex` 提供长度上限（200 字符）+
     `re.compile` 校验，供 controllers/rules.py 保存规则前调用并返回 400
     （原版是 `except re.error: print warning` 后静默降级成子串匹配，Web 端不该这样）。
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.hotlist.models import HotKeywordRule

MAX_PATTERN_LENGTH = 200


class InvalidRegexError(ValueError):
    """正则校验失败，message 可直接返回给前端（400）。"""


# ------------------------------------------------------- 逐行照搬（TrendRadar）----
def _parse_word(word: str) -> dict[str, Any]:
    """解析单个词，识别是否为正则表达式，支持显示名称（"word => alias" 或 "/pattern/ => alias"）。"""
    display_name = None

    if "=>" in word:
        parts = re.split(r"\s*=>\s*", word, 1)
        word_config = parts[0].strip()
        if len(parts) > 1 and parts[1].strip():
            display_name = parts[1].strip()
    else:
        word_config = word.strip()

    regex_match = re.match(r"^/(.+)/[a-z]*$", word_config)
    if regex_match:
        pattern_str = regex_match.group(1)
        try:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            return {
                "word": pattern_str,
                "is_regex": True,
                "pattern": pattern,
                "display_name": display_name,
            }
        except re.error:
            pass  # 降级为普通子串（原版行为：打 warning 后降级；这里静默，controller 层已强制校验过）

    return {
        "word": word_config,
        "is_regex": False,
        "pattern": None,
        "display_name": display_name,
    }


def _word_matches(word_config: str | dict[str, Any], title_lower: str) -> bool:
    """检查词是否在标题中匹配（word_config 可以是纯字符串或 _parse_word 的产物）。"""
    if isinstance(word_config, str):
        return word_config.lower() in title_lower
    if word_config.get("is_regex") and word_config.get("pattern"):
        return bool(word_config["pattern"].search(title_lower))
    return word_config["word"].lower() in title_lower


def _group_matches(title_lower: str, group: dict[str, Any]) -> bool:
    """单个词组是否匹配（必须词 AND + 普通词 OR + 排除词 NOT），不看全局过滤。"""
    required_words = group["required"]
    normal_words = group["normal"]
    exclude_words = group.get("exclude") or []

    if required_words and not all(
        _word_matches(req, title_lower) for req in required_words
    ):
        return False
    if normal_words and not any(
        _word_matches(normal, title_lower) for normal in normal_words
    ):
        return False
    if exclude_words and any(
        _word_matches(exc, title_lower) for exc in exclude_words
    ):
        return False
    return bool(required_words or normal_words)


def matches_word_groups(
    title: str,
    word_groups: list[dict[str, Any]],
    filter_words: list[Any],
    global_filters: list[str] | None = None,
) -> bool:
    """检查标题是否匹配「至少一个」词组规则。签名与 TrendRadar 原版一致；filter_words
    恒为空列表（见模块头改动说明 2），真正的组内排除词走每个 group 自带的 "exclude" 键。"""
    if not isinstance(title, str):
        title = str(title) if title is not None else ""
    if not title.strip():
        return False

    title_lower = title.lower()

    if global_filters and any(
        g.lower() in title_lower for g in global_filters
    ):
        return False

    if not word_groups:
        return True

    for filter_item in filter_words:
        if _word_matches(filter_item, title_lower):
            return False

    return any(_group_matches(title_lower, group) for group in word_groups)


def match_groups(
    title: str,
    word_groups: list[dict[str, Any]],
    global_filters: list[str] | None = None,
) -> list[int]:
    """返回命中的规则 id 列表（可能同时命中多个词组）。与 matches_word_groups
    （只关心「是否至少命中一个」）不同，crawl_service 记录 HotRuleHit 需要精确知道
    命中了哪几条规则，才能分别写命中记录 / 触发各自的推送配置。"""
    if not isinstance(title, str):
        title = str(title) if title is not None else ""
    if not title.strip():
        return []
    title_lower = title.lower()
    if global_filters and any(
        g.lower() in title_lower for g in global_filters
    ):
        return []
    return [
        group["rule_id"]
        for group in word_groups
        if group.get("rule_id") is not None
        and _group_matches(title_lower, group)
    ]


# ---------------------------------------------------------- 正则安全校验 ----
def compile_word_regex(pattern_str: str) -> re.Pattern:
    """保存规则前的正则校验：长度上限防灾难性回溯 + re.compile 语法校验。
    失败抛 InvalidRegexError（controller 捕获后转 400），不像原版那样静默降级。"""
    if len(pattern_str) > MAX_PATTERN_LENGTH:
        raise InvalidRegexError(f"正则长度超过 {MAX_PATTERN_LENGTH} 字符上限")
    try:
        return re.compile(pattern_str, re.IGNORECASE)
    except re.error as exc:
        raise InvalidRegexError(f"正则语法错误: {exc}") from exc


def validate_words_for_storage(words: list[dict[str, Any]]) -> None:
    """校验一组待存库的词（is_regex=True 的逐个 compile_word_regex），供 controller 调用。"""
    for w in words:
        if w.get("is_regex"):
            compile_word_regex(str(w.get("word", "")))


# ------------------------------------------------------- DB 行 <-> 词典 JSON ----
def _strip_pattern(parsed: dict[str, Any]) -> dict[str, Any]:
    """compiled pattern 不能 json 序列化，落库前剔除；is_regex=True 时靠 word 字段
    （正则源串）在加载时重新编译。"""
    return {
        "word": parsed["word"],
        "is_regex": parsed.get("is_regex", False),
        "display_name": parsed.get("display_name"),
    }


def parse_word_for_storage(line: str) -> dict[str, Any]:
    """文本一行 → 落库用的词典（校验正则，非法直接抛 InvalidRegexError）。"""
    parsed = _parse_word(line)
    if parsed.get("is_regex"):
        compile_word_regex(parsed["word"])
    return _strip_pattern(parsed)


def _load_word_list(json_text: str) -> list[dict[str, Any]]:
    """JSON 字符串 → 词典列表，is_regex=True 的词重新编译 pattern（供 _word_matches 用）。
    正则编译失败时降级为子串匹配（防止历史脏数据把整条规则匹配打挂），不抛错。"""
    try:
        raw = json.loads(json_text or "[]")
    except (ValueError, TypeError):
        return []
    words: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            words.append(
                {
                    "word": item,
                    "is_regex": False,
                    "pattern": None,
                    "display_name": None,
                }
            )
            continue
        if not isinstance(item, dict) or not item.get("word"):
            continue
        entry = {
            "word": item["word"],
            "is_regex": bool(item.get("is_regex")),
            "pattern": None,
            "display_name": item.get("display_name"),
        }
        if entry["is_regex"]:
            try:
                entry["pattern"] = re.compile(entry["word"], re.IGNORECASE)
            except re.error:
                entry["is_regex"] = False
        words.append(entry)
    return words


# --------------------------------------------------------------- 加载入口 ----
def load_rules(
    db: Session, topic_id: int | None = None
) -> tuple[list[dict[str, Any]], list[Any], list[str]]:
    """从 hot_keyword_rules 表加载启用中的规则。返回
    (word_groups, filter_words, global_filters)，
    与 TrendRadar load_frequency_words() 同签名，matches_word_groups() 可以直接复用。

    topic_id 给定 → 只加载该主题的 group 规则 + 全部 global_filter（源范围已由主题的
    hot_topic_sources 决定，规则不再有 source_ids 过滤逻辑）。
    topic_id 为 None → 加载全部启用的 group 规则（榜单摘要等全局场景）。
    """
    rows = (
        db.query(HotKeywordRule)
        .filter(HotKeywordRule.enabled.is_(True))
        .order_by(HotKeywordRule.sort_order.asc(), HotKeywordRule.id.asc())
        .all()
    )

    word_groups: list[dict[str, Any]] = []
    global_filters: list[str] = []

    for row in rows:
        if row.rule_type == "global_filter":
            for w in _load_word_list(row.normal_words):
                global_filters.append(w["word"])
            continue

        if topic_id is not None and row.topic_id != topic_id:
            continue

        normal = _load_word_list(row.normal_words)
        required = _load_word_list(row.required_words)
        exclude = _load_word_list(row.exclude_words)
        if not normal and not required:
            continue

        base_words = normal or required
        word_groups.append(
            {
                "rule_id": row.id,
                "required": required,
                "normal": normal,
                "exclude": exclude,
                "group_key": " ".join(w["word"] for w in base_words),
                "display_name": row.display_name or None,
                "max_count": row.max_count or 0,
            }
        )

    return word_groups, [], global_filters


# ------------------------------------------------------------ 文本 DSL 导入 ----
def parse_frequency_text(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """解析 TrendRadar 格式的频率词文本（用于 POST /rules/import 批量导入）。

    支持：空行分组、[组别名] 作为词组首行、[GLOBAL_FILTER] 区段、
    普通词（OR）、+必须词（AND）、!排除词（NOT，按本组生效）、@N 限量、
    /正则/、"词 => 别名"。返回 (groups, global_filters)：
    groups 是「待创建规则」的字典列表
    （display_name / normal / required / exclude / max_count），
    交给 controller 逐条转成 HotKeywordRule 插入；global_filters 是纯文本列表，
    每条转成一行 rule_type="global_filter" 规则。
    """
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]

    groups: list[dict[str, Any]] = []
    global_filters: list[str] = []
    current_section = "WORD_GROUPS"

    for block in blocks:
        lines = [
            ln.strip()
            for ln in block.split("\n")
            if ln.strip() and not ln.strip().startswith("#")
        ]
        if not lines:
            continue

        if lines[0].startswith("[") and lines[0].endswith("]"):
            section_name = lines[0][1:-1].strip().upper()
            if section_name in ("GLOBAL_FILTER", "WORD_GROUPS"):
                current_section = section_name
                lines = lines[1:]

        if current_section == "GLOBAL_FILTER":
            for line in lines:
                if line.startswith(("!", "+", "@")):
                    continue
                global_filters.append(line)
            continue

        group_alias = None
        if lines and lines[0].startswith("[") and lines[0].endswith("]"):
            potential_alias = lines[0][1:-1].strip()
            if potential_alias.upper() not in ("GLOBAL_FILTER", "WORD_GROUPS"):
                group_alias = potential_alias
                lines = lines[1:]

        normal_words: list[dict[str, Any]] = []
        required_words: list[dict[str, Any]] = []
        exclude_words: list[dict[str, Any]] = []
        max_count = 0

        for line in lines:
            if line.startswith("@"):
                try:
                    count = int(line[1:])
                    if count > 0:
                        max_count = count
                except (ValueError, IndexError):
                    pass
            elif line.startswith("!"):
                exclude_words.append(parse_word_for_storage(line[1:]))
            elif line.startswith("+"):
                required_words.append(parse_word_for_storage(line[1:]))
            else:
                normal_words.append(parse_word_for_storage(line))

        if not normal_words and not required_words:
            continue

        if group_alias:
            display_name = group_alias
        else:
            parts = [
                w.get("display_name") or w["word"]
                for w in (normal_words + required_words)
            ]
            display_name = " / ".join(parts) if parts else ""

        groups.append(
            {
                "display_name": display_name,
                "normal_words": normal_words,
                "required_words": required_words,
                "exclude_words": exclude_words,
                "max_count": max_count,
            }
        )

    return groups, global_filters
