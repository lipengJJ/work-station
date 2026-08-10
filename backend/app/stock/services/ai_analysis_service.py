"""
AI 综合研判：复用已有的 app/common/services/gemini_client.py（chat 功能已经在用的同一个
Gemini REST 客户端）和 app/common/services/gemini_config.py（同一份系统设置里配置的 Key/模型）。

Prompt 把前面各个 service 已经算好的真实数据（财务趋势、估值分位、预警信号、财报
surprise、SEC 8-K 事件、风险项）整理成一段结构化上下文喂给模型，明确要求：只依据给定
数据做整理和解释，不要凭空编数字；区分事实和推断；标注数据来源和期间；不用"必涨""稳赚"
这类确定性措辞；数据不够就直接说数据不足。模型的产出是一段 Markdown 文本，按前端约定的
10 个小节标题输出，前端直接用 markdown-it 渲染（和 xhs AI 分析页是同一个渲染方式），
不强求模型返回严格 JSON——财经评论这种自然语言内容让 LLM 硬套 JSON 格式反而更容易出错。
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.common.services import gemini_client
from app.common.services.gemini_config import get_gemini_config

_SECTION_HEADERS = [
    "公司当前基本面结论", "看多证据", "看空证据", "财报预期和实际结果", "市场可能已经反映的信息",
    "尚未被充分定价的潜在催化剂", "未来需要关注的日期和事件", "关键风险", "三种情景（悲观/基准/乐观）", "结论失效条件",
]


class AiAnalysisError(Exception):
    pass


def _build_prompt(symbol: str, context: dict) -> str:
    context_json = json.dumps(context, ensure_ascii=False, default=str, indent=2)
    sections = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(_SECTION_HEADERS))
    return f"""你是一名严谨的美股基本面研究助手，只负责整理、解释和对比下面提供的真实数据，
不允许凭空预测股价，不允许编造任何数据里没有的数字或事件。

标的：{symbol}

以下是从 SEC EDGAR（XBRL 财务数据、8-K 等原始披露文件）和 Yahoo Finance（实时行情、
分析师一致预期、历史估值）拉取并计算好的真实数据，JSON 格式：

```json
{context_json}
```

请严格按以下 10 个小节输出 Markdown（用二级标题 ## 加编号和标题，比如 "## 1. 公司当前基本面结论"）：
{sections}

硬性要求：
- 每个论点都要引用上面 JSON 里的具体指标、数值和数据期间（比如"最近季度营收同比 X%（截至 YYYY-MM-DD）"），不要空泛地说"表现良好"
- 明确标注每个数据点的来源（SEC EDGAR / Yahoo Finance）
- 清楚区分"这是数据里的事实"还是"这是你的推断"，推断要说明依据
- 绝对不使用"必涨""稳赚""保证""确定"这类确定性措辞
- 如果某个小节需要的数据在给定 JSON 里没有，必须直接写"数据不足，无法判断"，不能编造
- 三种情景（第9节）要说明各自的关键假设，不是空口下结论
- 最后必须加一行：**仅供研究，不构成投资建议**
"""


def generate_ai_analysis(db: Session, symbol: str, context: dict) -> dict:
    api_key, model, thinking_enabled = get_gemini_config(db)
    if not api_key:
        raise AiAnalysisError("尚未配置 Gemini API Key，请先在系统设置 > API配置 里填写 gemini_api_key")

    prompt = _build_prompt(symbol, context)
    messages = [{"role": "user", "content": prompt}]

    chunks = []
    try:
        for chunk in gemini_client.stream_chat(api_key, model, messages, thinking_enabled=thinking_enabled):
            chunks.append(chunk)
    except gemini_client.GeminiError as e:
        raise AiAnalysisError(str(e)) from e

    text = "".join(chunks).strip()
    if not text:
        raise AiAnalysisError("Gemini 返回了空结果，请稍后重试")

    return {"symbol": symbol, "model": model, "markdown": text}
