"""
Gemini 对话客户端：直接走官方 REST API（generativelanguage.googleapis.com），
不引入 google-generativeai SDK——项目里已经在用 requests 做类似的事（xhs 那边），
一个 REST 客户端就够了，没必要多一个依赖。
"""
import json
from typing import Iterator

import requests

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_TIMEOUT = 60


class GeminiError(Exception):
    pass


def _to_gemini_contents(messages: list) -> list:
    # Gemini 管助手角色叫 "model" 不是 "assistant"
    return [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in messages
    ]


def stream_chat(api_key: str, model: str, messages: list) -> Iterator[str]:
    """
    流式请求 Gemini，逐块 yield 文本增量。messages 是按时间顺序排列的
    [{"role": "user"|"assistant", "content": "..."}, ...] 历史（含本轮最新一条 user 消息）。
    """
    url = f"{_BASE_URL}/models/{model}:streamGenerateContent"
    params = {"key": api_key, "alt": "sse"}
    body = {"contents": _to_gemini_contents(messages)}

    with requests.post(url, params=params, json=body, stream=True, timeout=_TIMEOUT) as resp:
        if resp.status_code != 200:
            try:
                detail = resp.json().get("error", {}).get("message", resp.text)
            except ValueError:
                detail = resp.text
            raise GeminiError(f"Gemini API 请求失败（{resp.status_code}）：{detail}")

        data_lines: list = []
        # 不用 iter_lines(decode_unicode=True)：那个走的是 resp.encoding，requests 在响应头
        # 没显式声明 charset 时会按 HTTP 旧规范默认猜成 ISO-8859-1，把 UTF-8 多字节字符
        # （中文）拆成乱码——直接按字节读、自己用 utf-8 解码，不依赖它的猜测。
        for raw_bytes in resp.iter_lines():
            if raw_bytes is None:
                continue
            line = raw_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                # 空行 = 一个 SSE 事件结束
                if data_lines:
                    yield from _extract_text(data_lines)
                    data_lines = []
                continue
            if line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())
        if data_lines:
            yield from _extract_text(data_lines)


def _extract_text(data_lines: list) -> Iterator[str]:
    payload = "".join(data_lines)
    if not payload:
        return
    try:
        chunk = json.loads(payload)
    except json.JSONDecodeError:
        return
    for candidate in chunk.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            text = part.get("text")
            if text:
                yield text
