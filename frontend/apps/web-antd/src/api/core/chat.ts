import { requestClient } from '#/api/request';

// 独立聊天页已下线，这里只保留小红书 AI 分析页"模型设置"和系统设置 API 配置页
// "AI 模型"卡共用的读取/保存配置接口（同一份 ApiConfig 表）。
// 厂商列表、预设模型等元数据由后端 AI Gateway 注册表下发（GET /chat/config 的
// providers 字段）——前端不硬编码厂商，后端注册新模型/新厂商，前端自动出现。
export namespace ChatApi {
  export interface ProviderMeta {
    key: string;
    label: string;
    description: string;
    supports_thinking: boolean;
    default_model: string;
    presets: Array<{ label: string; value: string }>;
  }

  export interface Config {
    provider: string;
    configured: boolean;
    model: string;
    thinking_enabled: boolean;
    providers: ProviderMeta[];
  }

  export interface ConfigIn {
    // 厂商 key（不传 = 保持当前）
    provider?: string;
    // 留空 = 不修改已保存的 key，只更新模型
    api_key?: string;
    model?: string;
    thinking_enabled?: boolean;
  }
}

// 后端注册表没下发时的兜底预设（正常不会走到，老后端接口没有 providers 字段时用）
const FALLBACK_PRESETS: ChatApi.ProviderMeta[] = [
  {
    key: 'gemini',
    label: 'Gemini（Google）',
    description: 'Google AI Studio（aistudio.google.com）获取 API Key',
    supports_thinking: true,
    default_model: 'gemini-2.0-flash',
    presets: [
      { label: 'Gemini 3.5 Flash Lite', value: 'gemini-3.5-flash-lite' },
      { label: 'Gemini 3.6 Flash', value: 'gemini-3.6-flash' },
    ],
  },
  {
    key: 'deepseek',
    label: 'DeepSeek',
    description: 'DeepSeek 官方 API（platform.deepseek.com）获取 API Key',
    supports_thinking: false,
    default_model: 'deepseek-chat',
    presets: [
      { label: 'DeepSeek V3（deepseek-chat）', value: 'deepseek-chat' },
      { label: 'DeepSeek R1（deepseek-reasoner）', value: 'deepseek-reasoner' },
    ],
  },
];

export async function getChatConfigApi() {
  const config = await requestClient.get<ChatApi.Config>('/chat/config');
  if (!config.providers?.length) {
    config.providers = FALLBACK_PRESETS;
  }
  return config;
}

export async function setChatConfigApi(body: ChatApi.ConfigIn) {
  return requestClient.put<ChatApi.Config>('/chat/config', body);
}
