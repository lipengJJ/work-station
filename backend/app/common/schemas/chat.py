from pydantic import BaseModel, Field


class ProviderMeta(BaseModel):
    key: str
    label: str
    description: str
    supports_thinking: bool
    default_model: str
    presets: list[dict] = []


class ChatConfigOut(BaseModel):
    provider: str
    configured: bool
    model: str
    thinking_enabled: bool
    # 所有已注册厂商的元数据，前端用它渲染"厂商切换 + 预设模型"（数据驱动，后端加
    # 新厂商前端不用改代码）
    providers: list[ProviderMeta] = []


class ChatConfigIn(BaseModel):
    # 厂商 key（注册表里的 key，如 gemini / deepseek），留空不切（保持当前）
    provider: str | None = None
    # 留空 = 不修改已保存的 key，只更新模型/思考模式；首次配置时前端会要求必填
    api_key: str | None = Field(None, min_length=10)
    model: str | None = None
    thinking_enabled: bool | None = None
