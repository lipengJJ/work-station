"""
Gemini REST 的 AI Gateway 实现：在 app/common/services/gemini_client.py 的基础上扩展
systemInstruction、tools（googleSearch/urlContext，命名映射见设计文档 5.4 节 Permission
Resolver）、以及从响应里解析 usageMetadata/groundingMetadata/finishReason，统一包装成
base.py 定义的事件序列。刻意不改 gemini_client.py 本身——chat 和小红书笔记分析还在用
它的 stream_chat()，两边先并存，后续阶段再迁移调用方（设计文档"Claude 实施约束"第 9 条）。
"""
from __future__ import annotations

import json
from typing import Iterator

import requests

from app.common.services.ai_gateway.base import (
    EVENT_CITATION,
    EVENT_COMPLETED,
    EVENT_DELTA,
    EVENT_ERROR,
    EVENT_STARTED,
    EVENT_USAGE,
    AIGatewayError,
    AIRequest,
)

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_TIMEOUT = (10, 300)  # 同 gemini_client：连接超时给短一点，读超时放宽到 5 分钟

_TOOL_NAME_MAP = {
    "google_search": "googleSearch",
    "url_context": "urlContext",
}


def _to_gemini_contents(messages: list[dict]) -> list[dict]:
    return [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in messages
    ]


def _build_body(request: AIRequest) -> dict:
    body: dict = {
        "contents": _to_gemini_contents(request.messages),
    }
    # 普通路径（小红书笔记分析）system_instruction 传空字符串，空 systemInstruction
    # 部分模型会拒绝，只在非空时才带
    if request.system_instruction:
        body["systemInstruction"] = {"parts": [{"text": request.system_instruction}]}
    tools = [{_TOOL_NAME_MAP[t]: {}} for t in request.tools if t in _TOOL_NAME_MAP]
    if tools:
        body["tools"] = tools
    if request.thinking_enabled:
        body["generationConfig"] = {"thinkingConfig": {"thinkingBudget": -1}}
    return body


def stream_generate(request: AIRequest, api_key: str) -> Iterator[dict]:
    """
    yield 统一事件字典：{"type": "started"|"delta"|"citation"|"usage"|"completed"|"error", ...}。
    调用方（analysis 的 controller）负责把这些事件转成 SSE 格式发给前端，并在结束时用
    completed/usage/citation 里的数据落库。
    """
    yield {"type": EVENT_STARTED}

    url = f"{_BASE_URL}/models/{request.model}:streamGenerateContent"
    params = {"key": api_key, "alt": "sse"}
    body = _build_body(request)

    seen_citation_urls: set[str] = set()
    finish_reason: str | None = None
    usage: dict | None = None

    try:
        with requests.post(url, params=params, json=body, stream=True, timeout=_TIMEOUT) as resp:
            if resp.status_code != 200:
                try:
                    detail = resp.json().get("error", {}).get("message", resp.text)
                except ValueError:
                    detail = resp.text
                raise AIGatewayError(f"Gemini API 请求失败（{resp.status_code}）：{detail}")

            data_lines: list[str] = []
            for raw_bytes in resp.iter_lines():
                if raw_bytes is None:
                    continue
                # 和 gemini_client 一样：手动按 utf-8 解码，不依赖 requests 对响应编码的猜测
                line = raw_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    if data_lines:
                        chunk = _parse_chunk(data_lines)
                        data_lines = []
                        if chunk is None:
                            continue
                        yield from _events_from_chunk(chunk, seen_citation_urls)
                        finish_reason = _finish_reason_from_chunk(chunk) or finish_reason
                        usage = _usage_from_chunk(chunk) or usage
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[len("data:"):].strip())
            if data_lines:
                chunk = _parse_chunk(data_lines)
                if chunk is not None:
                    yield from _events_from_chunk(chunk, seen_citation_urls)
                    finish_reason = _finish_reason_from_chunk(chunk) or finish_reason
                    usage = _usage_from_chunk(chunk) or usage
    except requests.RequestException as e:
        yield {"type": EVENT_ERROR, "message": f"请求 Gemini 失败：{e}"}
        return
    except AIGatewayError as e:
        yield {"type": EVENT_ERROR, "message": str(e)}
        return

    if usage:
        yield {"type": EVENT_USAGE, "usage": usage}
    yield {"type": EVENT_COMPLETED, "finish_reason": finish_reason}


def _parse_chunk(data_lines: list[str]) -> dict | None:
    payload = "".join(data_lines)
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def _events_from_chunk(chunk: dict, seen_citation_urls: set[str]) -> Iterator[dict]:
    new_citations = []
    for candidate in chunk.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            text = part.get("text")
            if text:
                yield {"type": EVENT_DELTA, "text": text}

        grounding = candidate.get("groundingMetadata") or {}
        for gc in grounding.get("groundingChunks", []) or []:
            web = gc.get("web") or {}
            uri = web.get("uri")
            if uri and uri not in seen_citation_urls:
                seen_citation_urls.add(uri)
                new_citations.append({"title": web.get("title") or uri, "url": uri})

    if new_citations:
        yield {"type": EVENT_CITATION, "citations": new_citations}


def _finish_reason_from_chunk(chunk: dict) -> str | None:
    for candidate in chunk.get("candidates", []):
        reason = candidate.get("finishReason")
        if reason:
            return reason
    return None


def _usage_from_chunk(chunk: dict) -> dict | None:
    usage = chunk.get("usageMetadata")
    if not usage:
        return None
    return {
        "prompt_tokens": usage.get("promptTokenCount"),
        "completion_tokens": usage.get("candidatesTokenCount"),
        "total_tokens": usage.get("totalTokenCount"),
    }
