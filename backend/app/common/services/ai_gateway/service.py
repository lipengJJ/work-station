"""
AI Gateway 的分发入口：按 AIRequest.provider 查注册表（registry.py），把请求交给
对应 provider 的 handler。要接新厂商，在下面 PROVIDER_REGISTRY 区加一条注册即可——
OpenAI 兼容的厂商（DeepSeek/Kimi/通义/智谱开放平台…）直接用
make_openai_compatible_stream(base_url) 工厂函数，一行搞定；非兼容的（Gemini 这种
自有协议）自己实现一个 handler 再注册。

supports_tools=False 的 provider 不支持 Gemini 的 google_search / url_context 工具
（grounding API），分发时清掉，避免把未知字段透传给厂商。

故意不在这里接受 db session 去查 API Key——SSE 生成器实际执行（第一次被迭代）的时机
晚于 FastAPI 依赖的 yield 退出点，Depends(get_db) 的 session 到那时可能已经被关闭
（小红书那边 controller 也是因为这个原因才在流结束后另开一个 SessionLocal 写库）。
调用方在请求处理的同步阶段就该把 api_key 取出来，作为普通参数传进来。
"""
from __future__ import annotations

from typing import Iterator

from app.common.services.ai_gateway.base import EVENT_ERROR, AIRequest
from app.common.services.ai_gateway.gemini_provider import stream_generate
from app.common.services.ai_gateway.openai_compatible_provider import make_openai_compatible_stream
from app.common.services.ai_gateway.registry import ProviderSpec, get_provider, register_provider

# ---------------------------------------------------------------- PROVIDER 注册表 ----
# 新厂商在这里注册。字段含义见 registry.ProviderSpec：
# key/label/description 决定配置页展示；api_key_config/model_config 决定存在 ApiConfig
# 表的哪个 key；model_presets 给前端"快捷选择"；supports_tools 决定是否支持联网搜索等工具。

register_provider(
    ProviderSpec(
        key="gemini",
        label="Gemini（Google）",
        description="Google AI Studio（aistudio.google.com）获取 API Key",
        api_key_config="gemini_api_key",
        model_config="gemini_model",
        thinking_config="gemini_thinking_enabled",
        default_model="gemini-2.0-flash",
        model_presets=(
            ("Gemini 3.5 Flash Lite", "gemini-3.5-flash-lite"),
            ("Gemini 3.6 Flash", "gemini-3.6-flash"),
        ),
        supports_tools=True,
        handler=stream_generate,
    )
)

register_provider(
    ProviderSpec(
        key="deepseek",
        label="DeepSeek",
        description="DeepSeek 官方 API（platform.deepseek.com）获取 API Key",
        api_key_config="deepseek_api_key",
        model_config="deepseek_model",
        thinking_config=None,  # 无独立思考开关：deepseek-reasoner 自带思维链
        default_model="deepseek-chat",
        model_presets=(
            ("DeepSeek V3（deepseek-chat）", "deepseek-chat"),
            ("DeepSeek R1（deepseek-reasoner）", "deepseek-reasoner"),
        ),
        supports_tools=False,
        handler=make_openai_compatible_stream("https://api.deepseek.com"),
    )
)


def stream(request: AIRequest, api_key: str) -> Iterator[dict]:
    spec = get_provider(request.provider)
    if spec is None or spec.handler is None:
        yield {"type": EVENT_ERROR, "message": f"暂不支持的 AI provider：{request.provider}"}
        return

    if not spec.supports_tools and request.tools:
        # 拷贝一个清掉工具的新请求再交给 handler，不修改调用方传入的对象
        request = AIRequest(
            provider=request.provider,
            model=request.model,
            system_instruction=request.system_instruction,
            messages=request.messages,
            tools=[],
            thinking_enabled=request.thinking_enabled,
            request_id=request.request_id,
        )
    yield from spec.handler(request, api_key)
