"""
小红书笔记结构化预处理 · 规则清洗与低质内容过滤，对应《小红书笔记结构化预处理-技术方案.md》
3.2 节，不花钱、跑在 LLM 提炼之前：

1. clean()：去掉表情符号/话题标签/@用户/夸张标点/求关注类口水话，给后面 LLM 提炼喂
   更干净的输入（方案里说实测能降 25-40% 字符数，且不损失实质信息）。
2. is_low_content()：识别"求攻略/求推荐"这类没有实质内容的笔记。采集阶段命中的笔记
   直接从 parsed_notes 里剔除，不消耗后续的媒体下载、LLM 提炼、AI 分析 token——
   用户明确要求"这种数据才采集的时候就可以过滤，不用采集了"，不是等分析阶段再过滤。
"""
from __future__ import annotations

import re

_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\u2190-\u21FF\uFE0F]"
)
_NOISE_PATTERNS = [
    re.compile(r"#\S+"),
    re.compile(r"@\S+"),
    re.compile(r"(求关注|点赞收藏|姐妹们冲|码住|不踩雷|谁懂啊|绝了)+"),
    re.compile(r"[!！]{2,}"),
    re.compile(r"[?？]{2,}"),
    re.compile(r"[~～]{2,}"),
    re.compile(r"\.{3,}"),
]

# 求助/求攻略类关键词。只有"清洗后正文很短" + "命中这些关键词"同时成立才判定为低质——
# 单独命中关键词不够，避免误杀"标题带'求'字但正文其实写得很详细"的正常攻略笔记。
_LOW_CONTENT_KEYWORDS = re.compile(
    "求推荐|求攻略|求安利|求教|在线等|跪求|有没有姐妹|有没有人知道|求助|求带|"
    "蹲一个|坐等|求link|求链接|谁知道|求问|来个"
)

MIN_CONTENT_CHARS = 40  # 清洗后正文短于这个长度，基本不可能有实质信息，再看是否命中关键词
HARD_MIN_CONTENT_CHARS = 10  # 短到这个程度，不管有没有命中关键词都判定为低质


def clean(text: str) -> tuple[str, list[str]]:
    """返回 (清洗后正文, 提取出的话题标签)。话题标签本身是有用信息，先摘出来再删除。"""
    text = text or ""
    tags = re.findall(r"#(\S+)", text)
    text = _EMOJI_RE.sub("", text)
    for pattern in _NOISE_PATTERNS:
        text = pattern.sub(" ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text, tags


def is_low_content(title: str, desc: str) -> bool:
    cleaned_desc, _tags = clean(desc or "")
    if len(cleaned_desc) < HARD_MIN_CONTENT_CHARS:
        return True
    if len(cleaned_desc) < MIN_CONTENT_CHARS:
        combined = f"{title or ''} {desc or ''}"
        if _LOW_CONTENT_KEYWORDS.search(combined):
            return True
    return False
