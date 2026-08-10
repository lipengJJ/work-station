"""
Gemini 对话客户端：直接走官方 REST API（generativelanguage.googleapis.com），
不引入 google-generativeai SDK——项目里已经在用 requests 做类似的事（xhs 那边），
一个 REST 客户端就够了，没必要多一个依赖。
"""
import json
from typing import Iterator

import requests

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
# (连接超时, 读超时)：流式请求下 requests 的 timeout 是"两个 chunk 之间的静默时长"，
# 不是总时长。之前是单个数字 60，笔记数量多（比如小红书 AI 分析一次带 200 篇笔记的
# 上下文）+ 复杂生成任务时，Gemini 在吐出第一个 token 前的思考/排队时间很容易超过
# 60 秒，导致 ReadTimeout——不是代码错误，是超时给得太短。连接超时保持短一点，
# 网络本身不通的时候能快速失败，读超时放宽到 5 分钟。
_TIMEOUT = (10, 300)


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


def stream_chat(api_key: str, model: str, messages: list, thinking_enabled: bool = False) -> Iterator[str]:
    """
    流式请求 Gemini，逐块 yield 文本增量。messages 是按时间顺序排列的
    [{"role": "user"|"assistant", "content": "..."}, ...] 历史（含本轮最新一条 user 消息）。

    thinking_enabled=True 时带上 thinkingConfig（thinkingBudget=-1 让模型自己决定思考量），
    不设 includeThoughts，思考过程不会作为单独的 thought part 返回——只是让模型在生成最终
    回复前多"想一步"，不改变这里解析返回内容的逻辑。不是所有模型都支持这个参数，模型不支持
    的话 Gemini 会返回 4xx，走下面的错误处理分支正常报错，不会导致这个函数本身出问题。
    """
    url = f"{_BASE_URL}/models/{model}:streamGenerateContent"
    params = {"key": api_key, "alt": "sse"}
    body: dict = {"contents": _to_gemini_contents(messages)}
    if thinking_enabled:
        body["generationConfig"] = {"thinkingConfig": {"thinkingBudget": -1}}

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
