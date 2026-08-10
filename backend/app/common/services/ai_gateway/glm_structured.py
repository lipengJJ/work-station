"""
智谱 GLM 结构化输出调用（OpenAI 兼容 chat completions 接口）：笔记结构化预处理
专用，替代之前调用 Gemini 做这个任务——GLM-4-Flash 官方长期免费，中文/社交媒体
文本理解通常比通用模型更贴合小红书这类内容，这个抽取任务本身也不需要很强的推理
能力，不需要 Gemini 那种更贵/更慢的模型。

GLM 的 JSON 模式（response_format: json_object）只保证输出是合法 JSON，不像
Gemini 的 responseSchema 能强制字段结构——所以字段约束写进 system prompt 里
（见 note_structurer.py 的 _SYSTEM_PROMPT），输出后同样要走 note_structurer.py
里的 _validate() 兜底校验，不能假设模型一定守规矩。
"""
from __future__ import annotations

import json

import requests

_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
_TIMEOUT = (10, 60)  # 抽取任务输出很短，不需要像流式生成那样给很长的读超时


class GlmStructuredError(Exception):
    pass


def generate_structured(
    system_instruction: str,
    user_content: str,
    api_key: str,
    model: str,
    temperature: float = 0.1,
) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }

    try:
        resp = requests.post(_BASE_URL, headers=headers, json=body, timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise GlmStructuredError(f"请求智谱 GLM 失败：{e}") from e

    if resp.status_code != 200:
        try:
            detail = resp.json().get("error", {}).get("message", resp.text)
        except ValueError:
            detail = resp.text
        raise GlmStructuredError(f"智谱 GLM 请求失败（{resp.status_code}）：{detail}")

    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise GlmStructuredError(f"智谱 GLM 返回结构异常：{e}") from e
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise GlmStructuredError(f"智谱 GLM 输出不是合法 JSON：{e}") from e
