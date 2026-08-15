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

function configByName(name: string) {
  return configs.value.find((c) => c.name === name);
}

// 三个固定配置项的"已配置"状态（有值即已配置）
const xhsConfigured = computed(() => !!configByName('xhs_cookie')?.value);
const zhipuConfigured = computed(() => !!configByName('zhipu_api_key')?.value);

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

// -------------------------------------------------------------- 固定配置更新弹窗 ----
// 小红书 token / 数据处理模型：输入框默认留空（留空=不修改），不回显任何已有值，
// 只显示上次更新时间；保存后仅刷新行内状态点。

const updateModalOpen = ref(false);
const updateTarget = ref<'xhs' | 'zhipu'>('xhs');
const updateForm = reactive({ value: '', zhipu_model: '' });
const updateUpdatedAt = ref<string | null>(null);
const updateSaving = ref(false);

const UPDATE_META: Record<
  'xhs' | 'zhipu',
  { title: string; desc: string; keyPlaceholder: string }
> = {
  xhs: {
    title: '更新小红书 token',
    desc: '采集与追踪任务所需的登录态凭证。留空则不修改。',
    keyPlaceholder: '粘贴新的小红书登录态 cookie（留空则不修改）',
  },
  zhipu: {
    title: '更新数据处理模型',
    desc: '采集笔记时的结构化预处理（智谱 GLM）。留空则不修改。',
    keyPlaceholder: '粘贴新的智谱 API Key（留空则不修改）',
  },
};

function openUpdateModal(target: 'xhs' | 'zhipu') {
  updateTarget.value = target;
  updateForm.value = '';
  updateForm.zhipu_model = '';
  const cfg = configByName(target === 'xhs' ? 'xhs_cookie' : 'zhipu_api_key');
  updateUpdatedAt.value = cfg?.updated_at
    ? new Date(cfg.updated_at).toLocaleString('zh-CN', { hour12: false })
    : null;
  updateModalOpen.value = true;
}

async function submitUpdate() {
  const value = updateForm.value.trim();
  const model = updateForm.zhipu_model.trim();
  if (updateTarget.value === 'xhs') {
    if (!value) {
      message.warning('没有输入新值，无需更新');
      return;
    }
  } else if (!value && !model) {
    message.warning('没有输入新值，无需更新');
    return;
  }
  updateSaving.value = true;
  try {
    if (updateTarget.value === 'xhs') {
      await upsertApiConfigApi({
        name: 'xhs_cookie',
        value: value || undefined,
        description: '小红书登录态 cookie',
      });
    } else {
      await upsertApiConfigApi({
        name: 'zhipu_api_key',
        value: value || undefined,
        description: '智谱开放平台 API Key',
      });
      if (model) {
        await upsertApiConfigApi({ name: 'zhipu_model', value: model, description: '结构化预处理用的模型' });
      }
    }
    message.success('已保存');
    updateModalOpen.value = false;
    await fetchConfigs();
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    updateSaving.value = false;
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
      </div>

      <!-- ============================ AI 助手模型 Banner ============================ -->
      <!-- AI 模型：与下方配置项同一等高卡片格式 -->
      <div v-if="!modelConfigLoading" class="ac-item ac-ai-item">
        <span class="ac-status-dot" :class="modelConfig.configured ? 'ok' : 'no'" :title="modelConfig.configured ? '已配置' : '未配置'" />
        <div class="ac-ai-icon">
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z" />
            <path d="M19 15l.9 2.4L22.3 18.3l-2.4.9L19 21.6l-.9-2.4-2.4-.9 2.4-.9L19 15z" opacity="0.7" />
          </svg>
        </div>
        <div class="ac-item-info">
          <span class="ac-item-name">AI 模型 · {{ modelProviderLabel }}</span>
          <span class="ac-item-desc">用于小红书 AI 分析与 Skill 分析</span>
        </div>
        <div class="ac-item-actions">
          <Button type="text" size="small" class="ac-update-btn" @click="openModelModal">更新</Button>
        </div>
      </div>
      <div v-else class="ac-item ac-ai-item ac-ai-loading">加载中…</div>

      <!-- ============================ 固定配置列表（小红书 token / 数据处理模型） ============================ -->
      <div class="ac-grid">
        <!-- 小红书 token -->
        <div class="ac-item">
          <span class="ac-status-dot" :class="xhsConfigured ? 'ok' : 'no'" :title="xhsConfigured ? '已配置' : '未配置'" />
          <span class="ac-module-icon" style="background: color-mix(in srgb, #ff2442 12%, transparent); color: #ff2442">
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
              <path d="M9 18V6l10-2v11" /><path d="M9 11l10-2" />
            </svg>
          </span>
          <div class="ac-item-info">
            <span class="ac-item-name">小红书 token</span>
            <span class="ac-item-desc">采集与追踪任务所需的登录态凭证</span>
          </div>
          <div class="ac-item-actions">
            <Button type="text" size="small" class="ac-update-btn" @click="openUpdateModal('xhs')">更新</Button>
          </div>
        </div>

        <!-- 数据处理模型 -->
        <div class="ac-item">
          <span class="ac-status-dot" :class="zhipuConfigured ? 'ok' : 'no'" :title="zhipuConfigured ? '已配置' : '未配置'" />
          <span class="ac-module-icon" style="background: color-mix(in srgb, #f59e0b 12%, transparent); color: #f59e0b">
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
              <rect x="4" y="4" width="7" height="7" rx="1.5" /><rect x="13" y="4" width="7" height="7" rx="1.5" /><rect x="4" y="13" width="7" height="7" rx="1.5" /><rect x="13" y="13" width="7" height="7" rx="1.5" />
            </svg>
          </span>
          <div class="ac-item-info">
            <span class="ac-item-name">数据处理模型</span>
            <span class="ac-item-desc">采集笔记时的结构化预处理，与 AI 模型独立配置</span>
          </div>
          <div class="ac-item-actions">
            <Button type="text" size="small" class="ac-update-btn" @click="openUpdateModal('zhipu')">更新</Button>
          </div>
        </div>
      </div>

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
    <!-- ============================ 更新弹窗（小红书 token / 数据处理模型） ============================ -->
    <Modal v-model:open="updateModalOpen" :title="UPDATE_META[updateTarget].title" :footer="null" width="520px">
      <div class="ac-model-modal-desc">{{ UPDATE_META[updateTarget].desc }}</div>
      <Form layout="vertical">
        <FormItem label="凭证值">
          <Input.Password
            v-model:value="updateForm.value"
            class="ac-mono-input"
            :placeholder="UPDATE_META[updateTarget].keyPlaceholder"
          />
        </FormItem>
        <FormItem v-if="updateTarget === 'zhipu'" label="模型（可选）">
          <Input
            v-model:value="updateForm.zhipu_model"
            class="ac-mono-input"
            placeholder="如 glm-4-flash（留空则不修改）"
          />
        </FormItem>
        <div v-if="updateUpdatedAt" class="ac-form-hint" style="margin-bottom: 12px">
          上次更新时间：{{ updateUpdatedAt }}
        </div>
        <div class="ac-modal-actions">
          <Button @click="updateModalOpen = false">取消</Button>
          <Button type="primary" :loading="updateSaving" @click="submitUpdate">保存</Button>
        </div>
      </Form>
    </Modal>
    </div>
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

.ac-update-btn {
  border-radius: 8px !important;
  color: var(--ac-text-2, hsl(var(--muted-foreground))) !important;
  border: 1px solid var(--ac-border-strong, hsl(var(--border))) !important;
  background: var(--ac-bg-soft, hsl(var(--muted))) !important;
}
.ac-update-btn:hover {
  color: var(--ac-text, hsl(var(--foreground))) !important;
  border-color: var(--ac-primary, #4f6ef7) !important;
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
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: hsl(var(--muted-foreground));
  opacity: 0.45;
  margin: 0 5px;
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
