"""
通用 OpenAI 兼容 chat completions provider：DeepSeek、Kimi（Moonshot）、通义千问、
智谱 GLM 开放平台等国内厂商都提供 OpenAI 兼容的 /chat/completions 流式接口，行为
几乎一致——差别只在 base_url 和模型名。想接新的这类厂商时，在 service.py 里用
make_openai_compatible_stream(base_url) 注册一条 ProviderSpec 即可，不用再写
provider 代码。

与 gemini_provider 的差异：
- OpenAI 兼容接口没有 Gemini 的 grounding（googleSearch/urlContext），请求里不能带
  tools——调用方（Skill Runtime）可能已经解析出了 google_search 等工具名，由
  ai_gateway/service.py 在分发前按 ProviderSpec.supports_tools 清掉；
- 没有 thinkingConfig 开关：推理模型（如 deepseek-reasoner）自带思维链
  （reasoning_content），这里不解析展示，只透传 content 文本增量；
- 支持 stream_options.include_usage，最后一个 chunk 带 usage 统计。
"""
from __future__ import annotations

import json
from typing import Callable, Iterator

import requests

from app.common.services.ai_gateway.base import (
    EVENT_COMPLETED,
    EVENT_DELTA,
    EVENT_ERROR,
    EVENT_STARTED,
    EVENT_USAGE,
    AIGatewayError,
    AIRequest,
)

_TIMEOUT = (10, 300)  # 同 gemini：连接超时短一点，读超时放宽到 5 分钟（长上下文首 token 慢）


def _to_openai_messages(request: AIRequest) -> list[dict]:
    messages: list[dict] = []
    if request.system_instruction:
        messages.append({"role": "system", "content": request.system_instruction})
    messages.extend({"role": m["role"], "content": m["content"]} for m in request.messages)
    return messages


def make_openai_compatible_stream(base_url: str) -> Callable[[AIRequest, str], Iterator[dict]]:
    """
    工厂函数：绑定厂商的 base_url，返回一个标准 provider handler
    (request, api_key) -> Iterator[统一事件]。
    """

    def stream(request: AIRequest, api_key: str) -> Iterator[dict]:
        yield {"type": EVENT_STARTED}

        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": request.model,
            "messages": _to_openai_messages(request),
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        usage: dict | None = None
        finish_reason: str | None = None

        try:
            with requests.post(url, headers=headers, json=body, stream=True, timeout=_TIMEOUT) as resp:
                if resp.status_code != 200:
                    try:
                        detail = resp.json().get("error", {}).get("message", resp.text)
                    except ValueError:
                        detail = resp.text
                    raise AIGatewayError(f"{base_url} 请求失败（{resp.status_code}）：{detail}")

                for raw_bytes in resp.iter_lines():
                    if raw_bytes is None:
                        continue
                    line = raw_bytes.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta") or {}
                        text = delta.get("content")
                        if text:
                            yield {"type": EVENT_DELTA, "text": text}
                        finish_reason = choices[0].get("finish_reason") or finish_reason
                    if chunk.get("usage"):
                        usage = chunk["usage"]
        except requests.RequestException as e:
            yield {"type": EVENT_ERROR, "message": f"请求 {base_url} 失败：{e}"}
            return
        except AIGatewayError as e:
            yield {"type": EVENT_ERROR, "message": str(e)}
            return

        if usage:
            yield {
                "type": EVENT_USAGE,
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                },
            }
        yield {"type": EVENT_COMPLETED, "finish_reason": finish_reason}

    return stream
