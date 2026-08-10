"""
AI Gateway 的统一请求/事件形状（设计文档 5.5 节）。业务方（目前只有 Skill Runtime）拼出
一个 AIRequest 交给 service.stream()，不用关心具体走哪个厂商的 REST 格式；service 内部
按 provider 分发，目前只有 gemini_provider 一种实现。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AIRequest:
    provider: str
    model: str
    system_instruction: str
    messages: list[dict]  # [{"role": "user"|"assistant", "content": "..."}, ...]
    tools: list[str] = field(default_factory=list)  # 取值："google_search" | "url_context"
    thinking_enabled: bool = False
    request_id: str = ""


# 统一 SSE 事件类型，controller 层把这些原样透传给前端（见设计文档 5.5 节）
EVENT_STARTED = "started"
EVENT_DELTA = "delta"
EVENT_CITATION = "citation"
EVENT_USAGE = "usage"
EVENT_COMPLETED = "completed"
EVENT_ERROR = "error"


class AIGatewayError(Exception):
    """Provider 请求失败（HTTP 错误、超时、厂商返回的错误信息）时统一抛出的异常。"""
