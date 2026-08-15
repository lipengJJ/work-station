<script lang="ts" setup>
import type { ChatApi } from '#/api/core/chat';
import type { SystemApi } from '#/api/core/system';

import { computed, onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Button,
  Empty,
  Form,
  FormItem,
  Input,
  message,
  Modal,
  Radio,
  RadioGroup,
  Select,
  Switch,
  Tag,
} from 'ant-design-vue';

import { getChatConfigApi, setChatConfigApi } from '#/api/core/chat';
import { deleteApiConfigApi, listApiConfigsApi, upsertApiConfigApi } from '#/api/core/system';

const TextArea = Input.TextArea;

// -------------------------------------------------------------- 分类定义 ----
// 按功能模块分组展示。AI 助手（Gemini）用量最大的三个 key
// （gemini_api_key/gemini_model/gemini_thinking_enabled）从通用列表里摘出来，
// 单独做成模型配置卡片 + 弹窗，复用小红书 AI 分析页"模型设置"同一套配置接口。
interface ConfigCategory {
  key: string;
  label: string;
  description: string;
  matchNames: string[];
  icon: string; // 内联 SVG 的 path 内容（24x24 视图，stroke 风格）
  accent: string; // 模块主题色（用于图标底色）
}

const CATEGORIES: ConfigCategory[] = [
  {
    key: 'xhs',
    label: '小红书 token',
    description: '采集/追踪任务需要的登录态凭证',
    matchNames: ['xhs_cookie'],
    icon: '<path d="M9 18V6l10-2v11" /><path d="M9 11l10-2" />',
    accent: '#ff2442',
  },
  {
    key: 'note_structuring',
    label: '数据处理模型',
    description: '采集笔记时的结构化预处理用（智谱 GLM），与 AI 模型独立配置',
    matchNames: ['zhipu_api_key', 'zhipu_model'],
    icon: '<rect x="4" y="4" width="7" height="7" rx="1.5" /><rect x="13" y="4" width="7" height="7" rx="1.5" /><rect x="4" y="13" width="7" height="7" rx="1.5" /><rect x="13" y="13" width="7" height="7" rx="1.5" />',
    accent: '#f59e0b',
  },
];

// 系统固定配置：AI 模型 / 小红书 token / 数据处理模型，前端隐藏删除按钮 + 后端拒绝删除
const FIXED_CONFIG_NAMES = new Set([
  'ai_provider', 'gemini_api_key', 'gemini_model', 'gemini_thinking_enabled',
  'deepseek_api_key', 'deepseek_model',
  'xhs_cookie', 'zhipu_api_key', 'zhipu_model',
]);

// AI 模型（Gemini / DeepSeek）三个 key 及厂商标记从通用列表里摘出来，单独展示
const AI_CONFIG_NAMES = new Set([
  'ai_provider',
  'gemini_api_key',
  'gemini_model',
  'gemini_thinking_enabled',
  'deepseek_api_key',
  'deepseek_model',
]);

// 点建议 Tag 时顺手把说明也填好
const NAME_DESCRIPTIONS: Record<string, string> = {
  finnhub_api_key: 'Finnhub 行情数据 API Key',
  fmp_api_key: 'Financial Modeling Prep API Key',
  massive_api_key: 'Massive 数据源 API Key',
  sec_user_agent: 'SEC EDGAR 请求要求的 User-Agent（邮箱格式）',
  xhs_cookie: '小红书登录态 cookie',
  zhipu_api_key: '智谱开放平台 API Key（open.bigmodel.cn 获取，GLM-4-Flash 免费）',
  zhipu_model: '结构化预处理用的模型，不填默认 glm-4-flash',
};

// -------------------------------------------------------------- 通用配置列表 ----

const configs = ref<SystemApi.ApiConfig[]>([]);
const loading = ref(true);

async function fetchConfigs() {
  loading.value = true;
  try {
    configs.value = await listApiConfigsApi();
  } finally {
    loading.value = false;
  }
}

const categorizedGroups = computed(() =>
  CATEGORIES.map((cat) => ({
    ...cat,
    items: configs.value.filter((c) => cat.matchNames.includes(c.name)),
  })),
);

// 不属于任何已知分类、也不是 AI 助手三个 key 的，归到"其它"
const otherConfigs = computed(() =>
  configs.value.filter(
    (c) => !AI_CONFIG_NAMES.has(c.name) && !CATEGORIES.some((cat) => cat.matchNames.includes(c.name)),
  ),
);

// 顶部统计
const totalCount = computed(() => configs.value.length);
const configuredModules = computed(
  () => categorizedGroups.value.filter((g) => g.items.length > 0).length,
);

function maskValue(value: string) {
  if (!value) return '（空）';
  if (value.length <= 4) return '••••';
  return `${'•'.repeat(Math.min(value.length - 4, 12))}${value.slice(-4)}`;
}

// ------------------------------------------------------------- 值的显隐 / 复制 ----

const visibleMap = reactive<Record<number, boolean>>({});
const copiedId = ref<number | null>(null);
let copyTimer: ReturnType<typeof setTimeout> | null = null;

function toggleVisible(id: number) {
  visibleMap[id] = !visibleMap[id];
}

async function copyValue(config: SystemApi.ApiConfig) {
  try {
    await navigator.clipboard.writeText(config.value || '');
  } catch {
    // 剪贴板不可用时的兜底方案
    const el = document.createElement('textarea');
    el.value = config.value || '';
    document.body.appendChild(el);
    el.select();
    document.execCommand('copy');
    document.body.removeChild(el);
  }
  copiedId.value = config.id;
  if (copyTimer) clearTimeout(copyTimer);
  copyTimer = setTimeout(() => {
    copiedId.value = null;
  }, 1600);
}

// ------------------------------------------------------------- 新增 / 编辑弹窗（通用配置） ----

const modalOpen = ref(false);
const saving = ref(false);
const isEditing = ref(false);
const form = reactive<SystemApi.ApiConfigIn & { categoryKey: string }>({
  name: '',
  value: '',
  description: '',
  categoryKey: 'other',
});
const suggestedNames = ref<string[]>([]);

const categoryOptions = computed(() => [
  ...CATEGORIES.map((c) => ({ label: c.label, value: c.key })),
  { label: '其它（自由填写）', value: 'other' },
]);

function applyCategory(key: string) {
  const cat = CATEGORIES.find((c) => c.key === key);
  if (!cat) {
    suggestedNames.value = [];
    form.name = '';
    form.description = '';
    return;
  }
  suggestedNames.value = cat.matchNames;
  const configuredNames = new Set(configs.value.map((c) => c.name));
  const preselect = cat.matchNames.find((n) => !configuredNames.has(n));
  if (preselect) {
    form.name = preselect;
    form.description = NAME_DESCRIPTIONS[preselect] ?? '';
  }
}

function openCreateModal(category?: ConfigCategory) {
  isEditing.value = false;
  form.value = '';
  form.categoryKey = category?.key ?? 'other';
  applyCategory(form.categoryKey);
  modalOpen.value = true;
}

function openEditModal(config: SystemApi.ApiConfig) {
  isEditing.value = true;
  suggestedNames.value = [];
  form.name = config.name;
  form.value = '';
  form.description = config.description ?? '';
  modalOpen.value = true;
}

async function submitForm() {
  if (!form.name.trim()) {
    message.error('请填写配置项名称');
    return;
  }
  if (!isEditing.value && !form.value?.trim()) {
    message.error('新增配置需要填写值');
    return;
  }
  saving.value = true;
  try {
    await upsertApiConfigApi({
      name: form.name.trim(),
      value: form.value?.trim() || undefined,
      description: form.description?.trim() || undefined,
    });
    message.success('已保存');
    modalOpen.value = false;
    await fetchConfigs();
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    saving.value = false;
  }
}

function removeConfig(config: SystemApi.ApiConfig) {
  Modal.confirm({
    title: `确定删除配置「${config.name}」吗？`,
    content: '依赖这个配置的功能会立即无法使用，此操作不可恢复。',
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: async () => {
      try {
        await deleteApiConfigApi(config.id);
        message.success('已删除');
        await fetchConfigs();
      } catch (e: any) {
        message.error(`删除失败：${e.message}`);
      }
    },
  });
}

// -------------------------------------------------------------- AI 模型配置（注册表驱动） ----
// 厂商列表 / 预设模型 / 思考模式支持全部来自后端注册表下发的 providers 元数据，
// 后端新增厂商注册后，这里自动出现新厂商，无需改代码。

const modelConfig = ref<ChatApi.Config>({
  provider: 'gemini',
  configured: false,
  model: '',
  thinking_enabled: false,
  providers: [],
});
const modelConfigLoading = ref(true);
const modelModalOpen = ref(false);
const modelForm = reactive<{
  provider: string;
  api_key: string;
  model: string;
  thinking_enabled: boolean;
}>({ provider: 'gemini', api_key: '', model: '', thinking_enabled: false });
const modelSaving = ref(false);

// 当前表单所选厂商的元数据（后端注册表下发），不存在时兜底第一个
const currentProviderMeta = computed(
  () =>
    modelConfig.value.providers.find((p) => p.key === modelForm.provider) ??
    modelConfig.value.providers[0],
);
// 当前已保存厂商的元数据（banner 展示用，跟随已保存的配置而非表单）
const savedProviderMeta = computed(
  () =>
    modelConfig.value.providers.find((p) => p.key === modelConfig.value.provider) ??
    modelConfig.value.providers[0],
);
const modelProviderLabel = computed(
  () => savedProviderMeta.value?.label ?? modelConfig.value.provider,
);
// 弹窗表单里所选厂商的 label（切厂商时跟随表单选择，还没保存也算）
const formProviderLabel = computed(
  () => currentProviderMeta.value?.label ?? modelForm.provider,
);
const modelPresets = computed(() => currentProviderMeta.value?.presets ?? []);

async function fetchModelConfig() {
  modelConfigLoading.value = true;
  try {
    modelConfig.value = await getChatConfigApi();
  } catch (e: any) {
    message.error(`加载模型配置失败：${e.message}`);
  } finally {
    modelConfigLoading.value = false;
  }
}

function openModelModal() {
  modelForm.api_key = '';
  modelForm.provider = modelConfig.value.provider;
  modelForm.model = modelConfig.value.model;
  modelForm.thinking_enabled = modelConfig.value.thinking_enabled;
  modelModalOpen.value = true;
}

function changeModelProvider(provider: string) {
  modelForm.provider = provider;
  const meta = modelConfig.value.providers.find((p) => p.key === provider);
  // 切厂商时模型切到该厂商当前已保存的模型；不支持思考模式的厂商关掉开关
  modelForm.model = modelConfig.value.model;
  modelForm.thinking_enabled = meta?.supports_thinking
    ? modelConfig.value.thinking_enabled
    : false;
}

async function submitModelConfig() {
  const apiKey = modelForm.api_key.trim();
  if (!modelConfig.value.configured && !apiKey) {
    message.error(`请填写 ${formProviderLabel.value} API Key`);
    return;
  }
  modelSaving.value = true;
  try {
    modelConfig.value = await setChatConfigApi({
      provider: modelForm.provider,
      api_key: apiKey || undefined,
      model: modelForm.model.trim() || modelConfig.value.model,
      thinking_enabled: modelForm.thinking_enabled,
    });
    modelModalOpen.value = false;
    message.success('已保存');
    fetchConfigs();
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    modelSaving.value = false;
  }
}

onMounted(() => {
  fetchConfigs();
  fetchModelConfig();
});
</script>

<template>
  <Page :auto-content-height="false">
    <div class="ac-page">
      <!-- ============================ 页面头部 ============================ -->
      <div class="ac-header">
        <div class="ac-header-main">
          <div class="ac-header-title">
            <h2>API 配置</h2>
            <div class="ac-header-badge">配置中心</div>
          </div>
          <p>集中管理各业务模块使用的第三方服务凭证与密钥，保存后全局生效</p>
        </div>
        <Button type="primary" class="ac-header-btn" @click="openCreateModal()">
          <template #icon>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
          </template>
          新增配置
        </Button>
      </div>

      <!-- ============================ 统计概览 ============================ -->
      <div class="ac-stats">
        <div class="ac-stat">
          <span class="ac-stat-num">{{ totalCount }}</span>
          <span class="ac-stat-label">配置项</span>
        </div>
        <div class="ac-stat">
          <span class="ac-stat-num">{{ configuredModules }}<em>/{{ CATEGORIES.length }}</em></span>
          <span class="ac-stat-label">已配置模块</span>
        </div>
        <div class="ac-stat">
          <span class="ac-stat-num" :class="{ 'ac-stat-off': !modelConfig.configured }">
            {{ modelConfig.configured ? 'ON' : 'OFF' }}
          </span>
          <span class="ac-stat-label">AI 模型</span>
        </div>
        <div class="ac-stat ac-stat-hint">
          <span class="ac-stat-num">🔒</span>
          <span class="ac-stat-label">密钥仅展示末 4 位，可点击眼睛查看</span>
        </div>
      </div>

      <!-- ============================ AI 助手模型 Banner ============================ -->
      <!-- AI 模型：与下方配置项同一等高卡片格式 -->
      <div v-if="!modelConfigLoading" class="ac-item ac-ai-item">
        <span class="ac-status-dot" :class="modelConfig.configured ? 'ok' : 'no'" :title="modelConfig.configured ? '已配置' : '未配置'">
          <svg v-if="!modelConfig.configured" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
        </span>
        <div class="ac-ai-icon">
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z" />
            <path d="M19 15l.9 2.4L22.3 18.3l-2.4.9L19 21.6l-.9-2.4-2.4-.9 2.4-.9L19 15z" opacity="0.7" />
          </svg>
        </div>
        <div class="ac-item-info">
          <span class="ac-item-name">AI 模型 · {{ modelProviderLabel }}</span>
          <span class="ac-item-desc">
            当前模型 {{ modelConfig.model || '未选择' }}
            <template v-if="savedProviderMeta?.supports_thinking">
              · 思考模式 {{ modelConfig.thinking_enabled ? '已开启' : '未开启' }}
            </template>
            · 小红书 AI 分析 / Skill 分析共用
          </span>
        </div>
        <div class="ac-item-actions">
          <Button type="text" size="small" class="ac-ai-btn" @click="openModelModal">配置</Button>
        </div>
      </div>
      <div v-else class="ac-item ac-ai-item ac-ai-loading">加载中…</div>

      <!-- ============================ 模块分类卡片 ============================ -->
      <div class="ac-grid">
        <div v-for="group in categorizedGroups" :key="group.key" class="ac-card">
          <div class="ac-card-head">
            <div class="ac-card-head-left">
              <span class="ac-module-icon" :style="{ background: `${group.accent}1a`, color: group.accent }">
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" v-html="group.icon" />
              </span>
              <div class="ac-card-head-text">
                <div class="ac-card-title">
                  {{ group.label }}
                  <span class="ac-count" :class="{ empty: group.items.length === 0 }">
                    {{ group.items.length }}
                  </span>
                </div>
                <div class="ac-card-desc">{{ group.description }}</div>
              </div>
            </div>
            <Button type="text" size="small" class="ac-add-mini" @click="openCreateModal(group)">
              <template #icon>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
              </template>
              新增
            </Button>
          </div>

          <div v-if="!loading && group.items.length === 0" class="ac-empty ac-empty--compact">
            <span>暂无配置</span>
          </div>

          <div v-else class="ac-items" :class="{ 'is-loading': loading }">
            <div
              v-for="item in group.items"
              :key="item.id"
              class="ac-item"
              :title="item.description || item.name"
            >
              <span class="ac-status-dot" :class="item.value ? 'ok' : 'no'" :title="item.value ? '已配置' : '未配置'">
                <svg v-if="!item.value" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
              </span>
              <div class="ac-item-info">
                <span class="ac-item-name">{{ item.name }}</span>
                <span v-if="item.description" class="ac-item-desc">{{ item.description }}</span>
              </div>
              <div class="ac-item-value" :title="visibleMap[item.id] ? item.value : '点击眼睛查看明文'">
                <span class="ac-item-value-text">
                  {{ visibleMap[item.id] ? (item.value || '（空）') : maskValue(item.value) }}
                </span>
              </div>
              <div class="ac-item-actions">
                <button
                  class="ac-icon-btn"
                  :class="{ active: visibleMap[item.id] }"
                  :title="visibleMap[item.id] ? '隐藏明文' : '显示明文'"
                  @click="toggleVisible(item.id)"
                >
                  <svg v-if="!visibleMap[item.id]" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                  <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M3 3l18 18" />
                    <path d="M10.6 5.1A10.9 10.9 0 0 1 12 5c6.5 0 10 7 10 7a17.6 17.6 0 0 1-2.9 3.9M6.6 6.6A16.5 16.5 0 0 0 2 12s3.5 7 10 7a10.4 10.4 0 0 0 3.4-.6" />
                  </svg>
                </button>
                <button
                  class="ac-icon-btn"
                  :class="{ copied: copiedId === item.id }"
                  :title="'复制：' + item.value"
                  @click="copyValue(item)"
                >
                  <svg v-if="copiedId !== item.id" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="9" y="9" width="11" height="11" rx="2" />
                    <path d="M5 15V5a2 2 0 0 1 2-2h10" />
                  </svg>
                  <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M4 12.5l5 5L20 6.5" />
                  </svg>
                </button>
                <button class="ac-icon-btn" title="编辑" @click="openEditModal(item)">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 20h9" />
                    <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                  </svg>
                </button>
                <button v-if="!FIXED_CONFIG_NAMES.has(item.name)" class="ac-icon-btn danger" title="删除" @click="removeConfig(item)">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M3 6h18" />
                    <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
                    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                    <path d="M10 11v6M14 11v6" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ============================ 其它（兜底） ============================ -->
      <div v-if="otherConfigs.length > 0" class="ac-card ac-other">
        <div class="ac-card-head">
          <div class="ac-card-head-left">
            <span class="ac-module-icon" style="background: rgba(107, 114, 128, 0.15); color: hsl(var(--muted-foreground))">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
                <ellipse cx="12" cy="5" rx="8" ry="3" />
                <path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
                <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
              </svg>
            </span>
            <div class="ac-card-head-text">
              <div class="ac-card-title">
                其它
                <span class="ac-count">{{ otherConfigs.length }}</span>
              </div>
              <div class="ac-card-desc">未归类到具体模块的配置</div>
            </div>
          </div>
          <Button type="text" size="small" class="ac-add-mini" @click="openCreateModal()">
            <template #icon>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
            </template>
            新增
          </Button>
        </div>
        <div class="ac-items">
          <div v-for="item in otherConfigs" :key="item.id" class="ac-item" :title="item.description || item.name">
            <span class="ac-status-dot" :class="item.value ? 'ok' : 'no'" :title="item.value ? '已配置' : '未配置'">
              <svg v-if="!item.value" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
            </span>
            <div class="ac-item-info">
              <span class="ac-item-name">{{ item.name }}</span>
              <span v-if="item.description" class="ac-item-desc">{{ item.description }}</span>
            </div>
            <div class="ac-item-value" :title="visibleMap[item.id] ? item.value : '点击眼睛查看明文'">
              <span class="ac-item-value-text">
                {{ visibleMap[item.id] ? (item.value || '（空）') : maskValue(item.value) }}
              </span>
            </div>
            <div class="ac-item-actions">
              <button class="ac-icon-btn" :class="{ active: visibleMap[item.id] }" title="显示/隐藏明文" @click="toggleVisible(item.id)">
                <svg v-if="!visibleMap[item.id]" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="3" />
                </svg>
                <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M3 3l18 18" /><path d="M10.6 5.1A10.9 10.9 0 0 1 12 5c6.5 0 10 7 10 7a17.6 17.6 0 0 1-2.9 3.9M6.6 6.6A16.5 16.5 0 0 0 2 12s3.5 7 10 7a10.4 10.4 0 0 0 3.4-.6" />
                </svg>
              </button>
              <button class="ac-icon-btn" :class="{ copied: copiedId === item.id }" title="复制值" @click="copyValue(item)">
                <svg v-if="copiedId !== item.id" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" />
                </svg>
                <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M4 12.5l5 5L20 6.5" />
                </svg>
              </button>
              <button class="ac-icon-btn" title="编辑" @click="openEditModal(item)">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                </svg>
              </button>
              <button class="ac-icon-btn danger" title="删除" @click="removeConfig(item)">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M3 6h18" /><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" /><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" /><path d="M10 11v6M14 11v6" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ============================ 新增 / 编辑弹窗（通用配置） ============================ -->
    <Modal
      v-model:open="modalOpen"
      :title="isEditing ? `编辑配置「${form.name}」` : '新增 API 配置'"
      :ok-text="isEditing ? '保存' : '新增'"
      :confirm-loading="saving"
      ok-type="primary"
      @ok="submitForm"
    >
      <Form layout="vertical">
        <FormItem v-if="!isEditing" label="所属模块">
          <Select
            v-model:value="form.categoryKey"
            :options="categoryOptions"
            style="width: 100%"
            @change="(v: string) => applyCategory(v)"
          />
          <div class="ac-form-hint">选择模块后自动推荐该模块的配置项名称</div>
        </FormItem>
        <FormItem label="配置项名称">
          <Input
            v-model:value="form.name"
            :disabled="isEditing"
            placeholder="例如：fmp_api_key"
            class="ac-mono-input"
          />
          <div v-if="suggestedNames.length" class="ac-suggest">
            <span class="ac-suggest-label">推荐：</span>
            <Tag
              v-for="n in suggestedNames"
              :key="n"
              class="ac-suggest-tag"
              :color="form.name === n ? 'blue' : 'default'"
              @click="
                form.name = n;
                form.description = form.description?.trim() ? form.description : (NAME_DESCRIPTIONS[n] ?? '');
              "
            >
              {{ n }}
            </Tag>
          </div>
        </FormItem>
        <FormItem label="值" :extra="isEditing ? '留空 = 不修改已保存的值' : undefined">
          <TextArea v-model:value="form.value" :rows="2" class="ac-mono-input" placeholder="第三方服务的 key / endpoint" />
        </FormItem>
        <FormItem label="说明">
          <Input v-model:value="form.description" placeholder="给自己看的备注，可留空" />
        </FormItem>
      </Form>
    </Modal>

    <!-- ============================ AI 模型配置弹窗（厂商由注册表下发） ============================ -->
    <Modal v-model:open="modelModalOpen" title="AI 模型配置" :footer="null" width="480px">
      <div class="ac-model-modal-desc">
        小红书 AI 分析、Skill 分析共用这份配置。保存后立即生效，无需重启服务。
      </div>
      <Form layout="vertical">
        <FormItem label="模型厂商">
          <Radio.Group
            :value="modelForm.provider"
            button-style="solid"
            @change="(e) => changeModelProvider(e.target.value as string)"
          >
            <Radio.Button v-for="p in modelConfig.providers" :key="p.key" :value="p.key">
              {{ p.label }}
            </Radio.Button>
          </Radio.Group>
          <div class="ac-form-hint">
            {{ currentProviderMeta?.description }}
          </div>
        </FormItem>
        <FormItem
          :label="`${formProviderLabel} API Key`"
          :extra="modelConfig.configured ? '留空表示不修改已保存的 Key' : undefined"
        >
          <Input.Password
            v-model:value="modelForm.api_key"
            class="ac-mono-input"
            :placeholder="`从 ${formProviderLabel} 官方平台获取 API Key`"
          />
        </FormItem>
        <FormItem label="模型">
          <Input v-model:value="modelForm.model" class="ac-mono-input" :placeholder="currentProviderMeta?.default_model" />
          <div class="ac-suggest">
            <span class="ac-suggest-label">快捷选择：</span>
            <Tag
              v-for="preset in modelPresets"
              :key="preset.value"
              class="ac-suggest-tag"
              :color="modelForm.model === preset.value ? 'blue' : 'default'"
              @click="modelForm.model = preset.value"
            >
              {{ preset.label }}
            </Tag>
          </div>
        </FormItem>
        <FormItem v-if="currentProviderMeta?.supports_thinking" label="思考模式">
          <div class="ac-switch-row">
            <Switch v-model:checked="modelForm.thinking_enabled" />
            <span class="ac-switch-text">{{ modelForm.thinking_enabled ? '启用深度思考，回答更严谨但响应更慢' : '关闭思考模式，响应更快' }}</span>
          </div>
        </FormItem>
        <div v-else class="ac-form-hint" style="margin-bottom: 16px">
          该厂商无独立思考开关，推理模型（如 deepseek-reasoner）自带思维链。
        </div>
        <Button type="primary" block :loading="modelSaving" @click="submitModelConfig">保存</Button>
      </Form>
    </Modal>
  </Page>
</template>

<style>
/* ================= 主题变量（全局定义，供页面与 Modal 弹窗共用） ================= */
:root {
  --ac-bg: #ffffff;
  --ac-bg-soft: #f7f8fa;
  --ac-border: rgba(23, 33, 48, 0.08);
  --ac-border-strong: rgba(23, 33, 48, 0.14);
  --ac-text: #1f2733;
  --ac-text-2: #6b7280;
  --ac-text-3: #9ca3af;
  --ac-hover: rgba(23, 33, 48, 0.045);
  --ac-shadow: 0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 3px rgba(16, 24, 40, 0.07);
  --ac-shadow-lg: 0 4px 12px rgba(16, 24, 40, 0.08), 0 2px 4px rgba(16, 24, 40, 0.05);
  --ac-primary: #4f6ef7;
}

:root.dark,
body.dark {
  --ac-bg: #191c24;
  --ac-bg-soft: #1e222c;
  --ac-border: rgba(255, 255, 255, 0.08);
  --ac-border-strong: rgba(255, 255, 255, 0.14);
  --ac-text: #e6e9f0;
  --ac-text-2: #98a0b3;
  --ac-text-3: #6b7280;
  --ac-hover: rgba(255, 255, 255, 0.05);
  --ac-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
  --ac-shadow-lg: 0 4px 14px rgba(0, 0, 0, 0.4);
}
</style>

<style scoped>
.ac-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  max-width: 1180px;
  margin: 0 auto;
  padding: 4px 2px 24px;
  color: var(--ac-text);
}

/* ================= 页面头部 ================= */
.ac-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.ac-header-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ac-header-title h2 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.2px;
  line-height: 1.3;
}

.ac-header-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 9px;
  border-radius: 999px;
  color: var(--ac-primary);
  background: color-mix(in srgb, var(--ac-primary) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ac-primary) 25%, transparent);
}

.ac-header-main p {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--ac-text-2);
}

.ac-header-btn {
  border-radius: 8px;
  height: 36px;
  padding-inline: 18px;
  font-weight: 500;
  box-shadow: 0 2px 6px rgba(79, 110, 247, 0.35);
}

/* ================= 统计概览 ================= */
.ac-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.ac-stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 13px 16px;
  border-radius: 12px;
  background: var(--ac-bg);
  border: 1px solid var(--ac-border);
  box-shadow: var(--ac-shadow);
  transition: border-color 0.2s, transform 0.2s;
}

.ac-stat:hover {
  border-color: var(--ac-border-strong);
  transform: translateY(-1px);
}

.ac-stat-num {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.ac-stat-num em {
  font-style: normal;
  font-size: 14px;
  font-weight: 500;
  color: var(--ac-text-3);
  margin-left: 2px;
}

.ac-stat-num.ac-stat-off {
  font-size: 15px;
  color: var(--ac-text-3);
}

.ac-stat-label {
  font-size: 12px;
  color: var(--ac-text-2);
}

.ac-stat-hint .ac-stat-label {
  line-height: 1.5;
}

@media (max-width: 900px) {
  .ac-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* ================= AI 助手 Banner ================= */
.ac-ai-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 22px 24px;
  border-radius: 16px;
  overflow: hidden;
  color: #fff;
  background: linear-gradient(118deg, var(--primary) 0%, #6d28d9 52%, #a21caf 100%);
  box-shadow: 0 6px 20px rgba(88, 50, 220, 0.32);
}

.ac-ai-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(34px);
  opacity: 0.5;
  pointer-events: none;
}

.ac-ai-glow-1 {
  width: 220px;
  height: 220px;
  right: -60px;
  top: -90px;
  background: rgba(255, 255, 255, 0.28);
}

.ac-ai-glow-2 {
  width: 160px;
  height: 160px;
  left: 30%;
  bottom: -110px;
  background: rgba(255, 255, 255, 0.16);
}

.ac-ai-icon {
  position: relative;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--ac-primary, #4f6ef7) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--ac-primary, #4f6ef7) 22%, transparent);
  color: var(--ac-primary, #4f6ef7);
  backdrop-filter: blur(4px);
}

.ac-ai-info {
  position: relative;
  min-width: 0;
  flex: 1;
}

.ac-ai-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 700;
}

.ac-ai-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.22);
}

.ac-ai-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.55);
}

.ac-ai-status.on .ac-ai-dot {
  background: #4ade80;
  box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.7);
  animation: ac-breathe 2s ease-out infinite;
}

@keyframes ac-breathe {
  0% { box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.55); }
  70% { box-shadow: 0 0 0 7px rgba(74, 222, 128, 0); }
  100% { box-shadow: 0 0 0 0 rgba(74, 222, 128, 0); }
}

.ac-ai-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.88);
}

.ac-ai-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  opacity: 0.85;
}

.ac-ai-model {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.22);
  padding: 1px 8px;
  border-radius: 6px;
  font-weight: 600;
}

.ac-ai-sep {
  opacity: 0.5;
}

.ac-ai-on {
  color: #bbf7d0;
}

.ac-ai-note {
  margin-top: 8px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.72);
}

.ac-ai-btn {
  position: relative;
  flex-shrink: 0;
  border-radius: 9px;
  height: 36px;
  padding-inline: 20px;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.94);
  color: var(--primary);
  border: none;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.18);
}

.ac-ai-btn:hover {
  background: #fff !important;
  color: #4338ca !important;
}

.ac-ai-loading {
  justify-content: center;
  color: rgba(255, 255, 255, 0.85);
}

@media (max-width: 720px) {
  .ac-ai-card {
    flex-wrap: wrap;
  }
  .ac-ai-btn {
    width: 100%;
  }
}

/* ================= 模块分类卡片 ================= */
.ac-grid {
  /* 与消息通知页通道列表一致：每个模块分组一行一个、等宽（100%），纵向排列 */
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.ac-card {
  background: var(--ac-bg);
  border: 1px solid var(--ac-border);
  border-radius: 14px;
  box-shadow: var(--ac-shadow);
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
  overflow: hidden;
}

.ac-card:hover {
  border-color: var(--ac-border-strong);
  box-shadow: var(--ac-shadow-lg);
  transform: translateY(-1px);
}

.ac-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 15px 16px 12px;
  border-bottom: 1px dashed var(--ac-border);
}

.ac-card-head-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.ac-module-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 10px;
}

.ac-card-head-text {
  min-width: 0;
}

.ac-card-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 14px;
  font-weight: 600;
}

.ac-count {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--ac-primary) 12%, transparent);
  color: var(--ac-primary);
  font-variant-numeric: tabular-nums;
}

.ac-count.empty {
  background: var(--ac-bg-soft);
  color: var(--ac-text-3);
}

.ac-card-desc {
  margin-top: 3px;
  font-size: 12px;
  color: var(--ac-text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ac-add-mini {
  color: var(--ac-text-2);
  border-radius: 7px;
}

.ac-add-mini:hover {
  color: var(--ac-primary) !important;
  background: color-mix(in srgb, var(--ac-primary) 10%, transparent) !important;
}

/* ================= 配置项列表 ================= */
.ac-items {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 8px 0 4px;
}

.ac-items.is-loading {
  opacity: 0.55;
  pointer-events: none;
}

.ac-item {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 68px; /* 等高：与消息通知页通道卡片一致 */
  box-sizing: border-box;
  padding: 0 16px;
  background: var(--ac-bg);
  border: 1px solid var(--ac-border-strong);
  border-radius: 12px;
  box-shadow: var(--ac-shadow);
  transition: border-color 0.2s, box-shadow 0.2s, background 0.15s;
}

.ac-item:hover {
  border-color: var(--ac-border-strong);
  box-shadow: var(--ac-shadow-lg);
  background: var(--ac-bg);
}

.ac-item-info {
  flex: 1.2;
  min-width: 0;
}

.ac-item-name {
  display: block;
  font-size: 12.5px;
  font-weight: 600;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ac-item-desc {
  display: block;
  margin-top: 2px;
  font-size: 11.5px;
  color: var(--ac-text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ac-item-value {
  flex: 1;
  min-width: 0;
  padding: 5px 10px;
  border-radius: 7px;
  background: var(--ac-bg-soft);
  border: 1px solid var(--ac-border);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  color: var(--ac-text-2);
  letter-spacing: 0.5px;
}

.ac-item-value-text {
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ac-item-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.ac-icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 7px;
  background: transparent;
  cursor: pointer;
  color: var(--ac-text-3);
  transition: color 0.15s, background 0.15s, transform 0.1s;
}

.ac-icon-btn:hover {
  color: var(--ac-primary);
  background: color-mix(in srgb, var(--ac-primary) 10%, transparent);
}

.ac-icon-btn:active {
  transform: scale(0.92);
}

.ac-icon-btn.active {
  color: var(--ac-primary);
}

.ac-icon-btn.copied {
  color: #16a34a;
  background: rgba(22, 163, 74, 0.12);
}

.ac-icon-btn.danger:hover {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
}

/* ================= 空状态 ================= */
.ac-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 26px 12px 28px;
  color: var(--ac-text-3);
  font-size: 12.5px;
}

/* 紧凑空状态：单行提示，不占大片空白 */
.ac-empty--compact {
  padding: 9px 4px;
  font-size: 12px;
}

/* 配置状态标识：绿点=已配置 / 红叉=未配置 */
.ac-status-dot {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.ac-status-dot.ok {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.15);
  margin: 0 5px;
}
.ac-status-dot.no {
  width: 16px;
  height: 16px;
  margin: 0 1px;
  color: #f43f5e;
  opacity: 0.85;
}

/* ================= 其它卡片 ================= */
.ac-other {
  border-style: dashed;
}

/* ================= 表单细节 ================= */
.ac-form-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--ac-text-3);
}

.ac-suggest {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 9px;
}

.ac-suggest-label {
  font-size: 12px;
  color: var(--ac-text-3);
}

.ac-suggest-tag {
  cursor: pointer;
  user-select: none;
  margin-inline-end: 0;
}

.ac-mono-input {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.ac-model-modal-desc {
  margin-bottom: 14px;
  padding: 9px 12px;
  border-radius: 8px;
  font-size: 12.5px;
  color: var(--ac-text-2);
  background: var(--ac-bg-soft);
  border: 1px solid var(--ac-border);
}

.ac-switch-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ac-switch-text {
  font-size: 12.5px;
  color: var(--ac-text-2);
}
</style>
