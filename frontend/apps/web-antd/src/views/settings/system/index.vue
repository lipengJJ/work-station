<script lang="ts" setup>
import type { ChatApi } from '#/api/core/chat';
import type { NotifyApi } from '#/api/core/notify';

import { computed, onMounted, reactive, ref } from 'vue';

import { Button, Drawer, Dropdown, Form, FormItem, Input, message, Modal, Select, Switch } from 'ant-design-vue';
import { Bell, Boxes, KeyRound, MoreHorizontal, Plus, Sparkles } from 'lucide-vue-next';

import { getChatConfigApi, setChatConfigApi } from '#/api/core/chat';
import {
  createNotifyConfigApi,
  deleteNotifyConfigApi,
  getNotifyChannelsApi,
  listNotifyConfigsApi,
  testNotifySendApi,
  updateNotifyConfigApi,
} from '#/api/core/notify';
import XhsTokenManager from '../../xhs/_shared/XhsTokenManager.vue';

// ============================================================ 服务凭证 ----
// AI 模型（复用 chat 配置接口）
const modelConfig = ref<ChatApi.Config>({ provider: 'gemini', configured: false, model: '', thinking_enabled: false, providers: [] });
const modelConfigLoading = ref(true);
const modelModalOpen = ref(false);
const modelForm = reactive({ provider: 'gemini', api_key: '', model: '', thinking_enabled: false });
const modelSaving = ref(false);

// 通用配置（xhs_cookie / zhipu）
const configs = ref<{ name: string; value: string; updated_at: null | string }[]>([]);
function configByName(name: string) {
  return configs.value.find((c) => c.name === name);
}
const xhsConfigured = computed(() => !!configByName('xhs_cookie')?.value);
const zhipuConfigured = computed(() => !!configByName('zhipu_api_key')?.value);

async function fetchConfigs() {
  try {
    const { listApiConfigsApi } = await import('#/api/core/system');
    configs.value = (await listApiConfigsApi()) as { name: string; value: string; updated_at: null | string }[];
  } catch {
    /* ignore */
  }
}

async function fetchModelConfig() {
  modelConfigLoading.value = true;
  try {
    modelConfig.value = await getChatConfigApi();
    modelForm.provider = modelConfig.value.provider;
    modelForm.model = '';
    modelForm.api_key = '';
    modelForm.thinking_enabled = modelConfig.value.thinking_enabled;
  } finally {
    modelConfigLoading.value = false;
  }
}

function openModelModal() {
  modelForm.api_key = '';
  modelForm.model = '';
  modelForm.provider = modelConfig.value.provider;
  modelForm.thinking_enabled = modelConfig.value.thinking_enabled;
  modelModalOpen.value = true;
}

async function submitModelConfig() {
  modelSaving.value = true;
  try {
    await setChatConfigApi({
      provider: modelForm.provider,
      api_key: modelForm.api_key.trim() || undefined,
      model: modelForm.model.trim() || modelConfig.value.model,
      thinking_enabled: modelForm.thinking_enabled,
    });
    message.success('已保存');
    modelModalOpen.value = false;
    fetchModelConfig();
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    modelSaving.value = false;
  }
}

// 数据处理模型（智谱）更新弹窗
const zhipuModalOpen = ref(false);
const zhipuForm = reactive({ value: '', model: '' });
const zhipuUpdatedAt = ref<string | null>(null);
const zhipuSaving = ref(false);

function openZhipuModal() {
  zhipuForm.value = '';
  zhipuForm.model = '';
  const cfg = configByName('zhipu_api_key');
  zhipuUpdatedAt.value = cfg?.updated_at
    ? new Date(cfg.updated_at).toLocaleString('zh-CN', { hour12: false })
    : null;
  zhipuModalOpen.value = true;
}

async function submitZhipu() {
  const value = zhipuForm.value.trim();
  const model = zhipuForm.model.trim();
  if (!value && !model) {
    message.warning('没有输入新值，无需更新');
    return;
  }
  zhipuSaving.value = true;
  try {
    const { upsertApiConfigApi } = await import('#/api/core/system');
    await upsertApiConfigApi({ name: 'zhipu_api_key', value: value || undefined, description: '智谱开放平台 API Key' });
    if (model) {
      await upsertApiConfigApi({ name: 'zhipu_model', value: model, description: '结构化预处理用的模型' });
    }
    message.success('已保存');
    zhipuModalOpen.value = false;
    fetchConfigs();
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    zhipuSaving.value = false;
  }
}

// ============================================================ 消息通知 ----
const notifyConfigs = ref<NotifyApi.NotificationConfig[]>([]);
const channelMeta = ref<Record<string, NotifyApi.ChannelInfo>>({});
const notifyLoading = ref(true);

const CHANNEL_ORDER = ['wecom_webhook', 'serverchan', 'pushplus'];
const CHANNEL_LABEL: Record<string, string> = {
  wecom_webhook: '企业微信群机器人',
  serverchan: 'Server酱',
  pushplus: 'PushPlus',
};

async function loadNotify() {
  notifyLoading.value = true;
  try {
    const [meta, configs] = await Promise.all([getNotifyChannelsApi(), listNotifyConfigsApi()]);
    channelMeta.value = Object.fromEntries(meta.channels.map((c) => [c.channel, c]));
    notifyConfigs.value = configs;
  } catch (e: any) {
    message.error(`加载通知渠道失败：${e.message}`);
  } finally {
    notifyLoading.value = false;
  }
}

function isConfigured(cfg: NotifyApi.NotificationConfig): boolean {
  if (cfg.channel === 'wecom_webhook') return !!cfg.webhook_url;
  if (cfg.channel === 'serverchan') return !!cfg.sendkey;
  return !!cfg.token;
}

function configLabel(cfg: NotifyApi.NotificationConfig): string {
  const base = CHANNEL_LABEL[cfg.channel] || cfg.channel;
  return cfg.remark ? `${base} · ${cfg.remark}` : base;
}

async function toggleNotifyEnabled(cfg: NotifyApi.NotificationConfig, v: boolean) {
  try {
    await updateNotifyConfigApi(cfg.id, {
      channel: cfg.channel,
      remark: cfg.remark,
      webhook_url: cfg.webhook_url,
      sendkey: cfg.sendkey,
      token: cfg.token,
      enabled: v,
      mention_all: cfg.mention_all,
    });
    cfg.enabled = v;
  } catch (e: any) {
    message.error(`操作失败：${e.message}`);
  }
}

async function removeNotifyConfig(cfg: NotifyApi.NotificationConfig) {
  Modal.confirm({
    title: `删除通知渠道「${configLabel(cfg)}」？`,
    content: '删除后该渠道不再接收任务通知。',
    okText: '删除',
    okType: 'danger',
    onOk: async () => {
      await deleteNotifyConfigApi(cfg.id);
      message.success('已删除');
      loadNotify();
    },
  });
}

const testingId = ref<number | null>(null);

async function testNotifyChannel(cfg: NotifyApi.NotificationConfig) {
  testingId.value = cfg.id;
  try {
    const res = await testNotifySendApi(cfg.channel, cfg.remark);
    if (res.total === 0) {
      message.warning('该渠道未配置，无法发送');
    } else if (res.success) {
      message.success(res.message);
    } else {
      message.error(res.message);
    }
  } catch (e: any) {
    message.error(`发送失败：${e.message}`);
  } finally {
    testingId.value = null;
  }
}

// ---------------- 添加/编辑渠道抽屉（两步） ----------------
const drawerOpen = ref(false);
const editingId = ref<number | null>(null);
const drawerStep = ref(0); // 0=选类型 1=填字段
const drawerType = ref('wecom_webhook');
const drawerForm = reactive({ remark: '', webhook_url: '', sendkey: '', token: '', mention_all: false, enabled: true });
const drawerSaving = ref(false);

function openAddDrawer() {
  editingId.value = null;
  drawerStep.value = 0;
  drawerType.value = 'wecom_webhook';
  Object.assign(drawerForm, { remark: '', webhook_url: '', sendkey: '', token: '', mention_all: false, enabled: true });
  drawerOpen.value = true;
}

function openEditDrawer(cfg: NotifyApi.NotificationConfig) {
  editingId.value = cfg.id;
  drawerStep.value = 1;
  drawerType.value = cfg.channel;
  Object.assign(drawerForm, {
    remark: cfg.remark || '',
    webhook_url: cfg.webhook_url || '',
    sendkey: cfg.sendkey || '',
    token: cfg.token || '',
    mention_all: cfg.mention_all,
    enabled: cfg.enabled,
  });
  drawerOpen.value = true;
}

const drawerTitle = computed(() => (editingId.value ? '编辑通知渠道' : '添加通知渠道'));

async function submitDrawer() {
  const body = {
    channel: drawerType.value,
    remark: drawerForm.remark.trim(),
    webhook_url: drawerForm.webhook_url.trim(),
    sendkey: drawerForm.sendkey.trim(),
    token: drawerForm.token.trim(),
    enabled: drawerForm.enabled,
    mention_all: drawerForm.mention_all,
  };
  drawerSaving.value = true;
  try {
    if (editingId.value) {
      await updateNotifyConfigApi(editingId.value, body);
      message.success('已保存');
    } else {
      await createNotifyConfigApi(body);
      message.success('已添加');
    }
    drawerOpen.value = false;
    loadNotify();
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    drawerSaving.value = false;
  }
}

const tokenManagerRef = ref<InstanceType<typeof XhsTokenManager> | null>(null);

onMounted(() => {
  fetchConfigs();
  fetchModelConfig();
  loadNotify();
});
</script>

<template>
  <Page :auto-content-height="true">
    <div class="ss-page">
      <!-- ============================ 页面标题 ============================ -->
      <header class="ss-header">
        <h2>系统设置</h2>
        <p>集中管理服务凭证与通知渠道，保存后全局生效</p>
      </header>

      <!-- ============================ 区块一：服务凭证（固定三行，标题由页面副标题覆盖） ============================ -->
      <section class="ss-section">
        <div class="ss-list">
          <!-- AI 模型 -->
          <div class="ss-row">
            <span class="ss-dot" :class="modelConfig.configured ? 'ok' : 'no'" />
            <span class="ss-icon ss-icon--ai"><Sparkles class="size-5" /></span>
            <div class="ss-main">
              <div class="ss-name-line">
                <span class="ss-name">AI 模型</span>
                <span v-if="!modelConfig.configured" class="ss-pill">未配置</span>
              </div>
              <p class="ss-desc">用于小红书 AI 分析与 Skill 分析</p>
            </div>
            <div class="ss-actions">
              <Button size="small" class="ss-btn ss-update-btn" :auto-insert-space-in-button="false" @click="openModelModal">更新</Button>
            </div>
          </div>

          <!-- 小红书 token -->
          <div class="ss-row">
            <span class="ss-dot" :class="xhsConfigured ? 'ok' : 'no'" />
            <span class="ss-icon ss-icon--xhs"><KeyRound class="size-5" /></span>
            <div class="ss-main">
              <div class="ss-name-line">
                <span class="ss-name">小红书 token</span>
                <span v-if="!xhsConfigured" class="ss-pill">未配置</span>
              </div>
              <p class="ss-desc">采集与追踪任务所需的登录态凭证</p>
            </div>
            <div class="ss-actions">
              <Button size="small" class="ss-btn ss-update-btn" :auto-insert-space-in-button="false" @click="tokenManagerRef?.open()">更新</Button>
            </div>
          </div>

          <!-- 数据处理模型 -->
          <div class="ss-row">
            <span class="ss-dot" :class="zhipuConfigured ? 'ok' : 'no'" />
            <span class="ss-icon ss-icon--zhipu"><Boxes class="size-5" /></span>
            <div class="ss-main">
              <div class="ss-name-line">
                <span class="ss-name">数据处理模型</span>
                <span v-if="!zhipuConfigured" class="ss-pill">未配置</span>
              </div>
              <p class="ss-desc">采集笔记时的结构化预处理，与 AI 模型独立配置</p>
            </div>
            <div class="ss-actions">
              <Button size="small" class="ss-btn ss-update-btn" :auto-insert-space-in-button="false" @click="openZhipuModal">更新</Button>
            </div>
          </div>
        </div>
      </section>

      <!-- ============================ 区块二：消息通知（与凭证同构的行卡片） ============================ -->
      <template v-if="notifyLoading">
        <div class="ss-loading">加载中…</div>
      </template>

      <!-- 未配置任何渠道：单行提示 + 添加 -->
      <template v-else-if="!notifyConfigs.length">
        <div class="ss-row">
          <span class="ss-dot no" />
          <span class="ss-icon ss-icon--notify"><Bell class="size-5" /></span>
          <div class="ss-main">
            <div class="ss-name-line">
              <span class="ss-name">消息通知</span>
              <span class="ss-pill">未配置</span>
            </div>
            <p class="ss-desc">任务完成 / 失败时自动推送，可配置多个渠道</p>
          </div>
          <div class="ss-actions">
            <Button type="primary" size="small" class="ss-add-btn" @click="openAddDrawer">
              <Plus class="mr-1 size-3" />
              添加渠道
            </Button>
          </div>
        </div>
      </template>

      <!-- 已配置渠道：每个一行，结构完全一致 -->
      <template v-else>
        <div v-for="cfg in notifyConfigs" :key="cfg.id" class="ss-row">
          <span class="ss-dot" :class="isConfigured(cfg) && cfg.enabled ? 'ok' : 'no'" :title="isConfigured(cfg) && cfg.enabled ? '已配置且已启用' : '未配置或已停用'" />
          <span class="ss-icon" :class="`ss-icon--${cfg.channel}`">
            <Bell class="size-5" />
          </span>
          <div class="ss-main">
            <div class="ss-name-line">
              <span class="ss-name">{{ configLabel(cfg) }}</span>
              <span v-if="!isConfigured(cfg)" class="ss-pill">未配置</span>
            </div>
            <p class="ss-desc">{{ channelMeta[cfg.channel]?.description || '任务通知推送到该渠道' }}</p>
          </div>
          <div class="ss-actions">
            <Button size="small" class="ss-btn" @click="openEditDrawer(cfg)">编辑</Button>
            <Switch size="small" :checked="cfg.enabled" @change="(v: string | number | boolean) => toggleNotifyEnabled(cfg, Boolean(v))" />
            <Dropdown>
              <Button size="small" type="text" class="!px-1">
                <MoreHorizontal class="size-4" />
              </Button>
              <template #overlay>
                <div class="rounded-lg border border-slate-700/50 bg-slate-900/90 p-1 shadow-xl">
                  <Button size="small" type="text" block class="!text-left" :loading="testingId === cfg.id" @click="testNotifyChannel(cfg)">
                    手动发送
                  </Button>
                  <Button size="small" type="text" danger block class="!text-left" @click="removeNotifyConfig(cfg)">
                    删除
                  </Button>
                </div>
              </template>
            </Dropdown>
          </div>
        </div>

        <!-- 虚线占位：+ 添加渠道 -->
        <div class="ss-row ss-row--dashed" @click="openAddDrawer">
          <span class="ss-add-placeholder">
            <Plus class="mr-1 size-3" />
            添加渠道
          </span>
        </div>
      </template>
    </div>

    <!-- ============================ AI 模型配置弹窗 ============================ -->
    <Modal v-model:open="modelModalOpen" title="AI 模型配置" :footer="null" width="480px">
      <Form layout="vertical">
        <FormItem label="模型厂商">
          <Select
            v-model:value="modelForm.provider"
            style="width: 100%"
            :options="modelConfig.providers.map((p) => ({ label: p.label, value: p.key }))"
          />
        </FormItem>
        <FormItem label="API Key">
          <Input.Password
            v-model:value="modelForm.api_key"
            placeholder="留空则不修改"
          />
        </FormItem>
        <FormItem label="模型">
          <Input v-model:value="modelForm.model" placeholder="留空则不修改" />
        </FormItem>
        <FormItem label="思考模式">
          <Switch v-model:checked="modelForm.thinking_enabled" />
        </FormItem>
        <div class="flex justify-end gap-2">
          <Button @click="modelModalOpen = false">取消</Button>
          <Button type="primary" :loading="modelSaving" @click="submitModelConfig">保存</Button>
        </div>
      </Form>
    </Modal>

    <!-- 小红书 token：三 tab 登录弹窗 -->
    <XhsTokenManager ref="tokenManagerRef" />

    <!-- ============================ 数据处理模型更新弹窗 ============================ -->
    <Modal v-model:open="zhipuModalOpen" title="更新数据处理模型" :footer="null" width="480px">
      <div class="ss-modal-desc">采集笔记时的结构化预处理（智谱 GLM）。留空则不修改。</div>
      <Form layout="vertical">
        <FormItem label="凭证值">
          <Input.Password v-model:value="zhipuForm.value" placeholder="粘贴新的智谱 API Key（留空则不修改）" />
        </FormItem>
        <FormItem label="模型（可选）">
          <Input v-model:value="zhipuForm.model" placeholder="如 glm-4-flash（留空则不修改）" />
        </FormItem>
        <div v-if="zhipuUpdatedAt" class="ss-updated-at">上次更新时间：{{ zhipuUpdatedAt }}</div>
        <div class="flex justify-end gap-2">
          <Button @click="zhipuModalOpen = false">取消</Button>
          <Button type="primary" :loading="zhipuSaving" @click="submitZhipu">保存</Button>
        </div>
      </Form>
    </Modal>

    <!-- ============================ 添加/编辑渠道抽屉 ============================ -->
    <Drawer v-model:open="drawerOpen" :title="drawerTitle" width="440px">
      <!-- 第一步：选类型 -->
      <div v-if="drawerStep === 0" class="flex flex-col gap-3">
        <div
          v-for="key in CHANNEL_ORDER"
          :key="key"
          class="ss-type-card"
          :class="{ active: drawerType === key }"
          @click="drawerType = key"
        >
          <Bell class="size-4 shrink-0" />
          <div class="min-w-0">
            <div class="text-sm font-semibold text-[hsl(var(--foreground))]">{{ CHANNEL_LABEL[key] }}</div>
            <div class="text-xs text-[hsl(var(--muted-foreground))]">{{ channelMeta[key]?.description || '' }}</div>
          </div>
          <span v-if="drawerType === key" class="ml-auto text-[hsl(var(--primary))]">✓</span>
        </div>
        <Button type="primary" class="mt-2" @click="drawerStep = 1">下一步</Button>
      </div>

      <!-- 第二步：填字段 -->
      <Form v-else layout="vertical">
        <FormItem label="备注名（可选）">
          <Input v-model:value="drawerForm.remark" placeholder="如：研发群 / 值班群（同类型多实例时用于区分）" />
        </FormItem>
        <template v-if="drawerType === 'wecom_webhook'">
          <FormItem label="企业微信机器人 Webhook">
            <Input.Password v-model:value="drawerForm.webhook_url" placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..." />
          </FormItem>
          <FormItem label="消息 @所有人">
            <Switch v-model:checked="drawerForm.mention_all" />
          </FormItem>
        </template>
        <template v-else-if="drawerType === 'serverchan'">
          <FormItem label="Server酱 SendKey">
            <Input.Password v-model:value="drawerForm.sendkey" placeholder="sctp..." />
          </FormItem>
        </template>
        <template v-else>
          <FormItem label="PushPlus Token">
            <Input.Password v-model:value="drawerForm.token" placeholder="PushPlus Token" />
          </FormItem>
        </template>
        <FormItem label="启用">
          <Switch v-model:checked="drawerForm.enabled" />
        </FormItem>
        <div class="flex justify-end gap-2">
          <Button @click="drawerStep = 0">上一步</Button>
          <Button type="primary" :loading="drawerSaving" @click="submitDrawer">保存</Button>
        </div>
      </Form>
    </Drawer>
  </Page>
</template>

<style scoped>
/* ==================== 页面容器 ==================== */
.ss-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
  max-width: 1200px;
  margin-left: 0;
  margin-right: auto;
}
/* 页面标题区与下方第一行间距 24px（由 ss-page gap 承担） */
.ss-header h2 {
  font-size: 20px;
  font-weight: 700;
  color: hsl(var(--foreground));
}
.ss-header p {
  margin-top: 4px;
  font-size: 13px;
  color: hsl(var(--muted-foreground));
}
/* ==================== 区块 ==================== */
.ss-section {
  display: flex;
  flex-direction: column;
}
.ss-section + .ss-section {
  gap: 16px; /* 说明文案与下方内容间距 16px */
}
/* 消息通知标题与上方（数据处理模型行）间距 32px */
.ss-section + .ss-section {
  margin-top: 32px;
}

.ss-section-head h3 {
  font-size: 16px;
  font-weight: 600;
  color: hsl(var(--foreground));
}
.ss-section-head p {
  margin-top: 4px;
  font-size: 13px;
  color: hsl(var(--muted-foreground));
}

.ss-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ss-row {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 76px;
  padding: 0 24px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: hsl(var(--card));
  transition: background 0.15s;
}
.ss-row:hover {
  background: hsl(var(--accent));
}
/* 状态点 8px */
.ss-dot {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.ss-dot.ok {
  background: #22c55e;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.15);
}
.ss-dot.no {
  background: hsl(var(--muted-foreground));
  opacity: 0.45;
}
/* 图标容器 40×40，圆角 10px，图标 20×20 居中（gap 12 已由 .ss-row 承担） */
.ss-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  color: #fff;
}
.ss-icon--ai {
  background: color-mix(in srgb, #8b5cf6 85%, #000);
}
.ss-icon--xhs {
  background: #ff2442;
}
.ss-icon--zhipu {
  background: #f59e0b;
}
.ss-icon--wecom_webhook {
  background: #2f9e44;
}
.ss-icon--serverchan {
  background: #1971c2;
}
.ss-icon--pushplus {
  background: #e8590c;
}
/* 文字区：图标右侧 16px 间距 */
.ss-main {
  flex: 1;
  min-width: 0;
  margin-left: 16px;
}
.ss-name-line {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.ss-name {
  font-size: 15px;
  font-weight: 600;
  color: hsl(var(--foreground));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* 未配置 pill：与主标题同基线，padding 2px 8px，12px，圆角 full */
.ss-pill {
  flex-shrink: 0;
  padding: 2px 8px;
  border-radius: 999px;
  background: hsl(var(--muted));
  color: hsl(var(--muted-foreground));
  font-size: 12px;
  line-height: 1.4;
}
/* 说明文案：主标题下方 4px */
.ss-desc {
  margin-top: 4px;
  font-size: 13px;
  color: hsl(var(--muted-foreground));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 操作区：右内边距 24px 由 .ss-row padding 承担 */
.ss-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
/* 更新按钮：高 32px，左右 padding 16px，13px */
.ss-update-btn {
  height: 32px !important;
  padding-left: 16px !important;
  padding-right: 16px !important;
  font-size: 13px !important;
  border-radius: 8px;
  color: hsl(var(--muted-foreground)) !important;
  border: 1px solid hsl(var(--border)) !important;
  background: hsl(var(--muted)) !important;
}
.ss-update-btn:hover {
  color: hsl(var(--foreground)) !important;
  border-color: hsl(var(--primary)) !important;
}
.ss-loading {
  padding: 32px;
  text-align: center;
  color: hsl(var(--muted-foreground));
}
/* 消息通知默认图标色 */
.ss-icon--notify {
  background: #0ea5e9;
}
/* 已配置渠道下方的虚线「+ 添加渠道」占位行 */
.ss-row--dashed {
  justify-content: center;
  border-style: dashed;
  border-color: hsl(var(--border));
  background: transparent;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.ss-row--dashed:hover {
  background: hsl(var(--accent));
  border-color: hsl(var(--primary));
}
.ss-add-placeholder {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 13px;
  color: hsl(var(--muted-foreground));
}
.ss-row--dashed:hover .ss-add-placeholder {
  color: hsl(var(--primary));
}
/* ==================== 空态 ==================== */
.ss-empty {
  padding: 48px 0;
}
.ss-empty :deep(.ant-empty-image) {
  margin-bottom: 16px;
}
.ss-empty :deep(.ant-empty-description) {
  margin-top: 0;
}
.ss-modal-desc {
  margin-bottom: 12px;
  font-size: 13px;
  color: hsl(var(--muted-foreground));
}
.ss-updated-at {
  margin-bottom: 12px;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}
.ss-type-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid hsl(var(--border));
  background: hsl(var(--card));
  cursor: pointer;
  transition: border-color 0.15s;
}
.ss-type-card:hover,
.ss-type-card.active {
  border-color: hsl(var(--primary));
}

/* 768~1200px：说明换行 */
@media (max-width: 1200px) and (min-width: 768px) {
  .ss-desc {
    white-space: normal;
  }
}
/* <768px：竖向堆叠，操作等宽平铺 */
@media (max-width: 767px) {
  .ss-row {
    flex-wrap: wrap;
    padding: 12px 14px;
    row-gap: 8px;
  }
  .ss-main {
    flex: 1 1 calc(100% - 76px);
    margin-left: 12px;
  }
  .ss-actions {
    flex: 1 1 100%;
    justify-content: stretch;
  }
  .ss-actions .ant-btn {
    flex: 1;
  }
  .ss-section-head {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
