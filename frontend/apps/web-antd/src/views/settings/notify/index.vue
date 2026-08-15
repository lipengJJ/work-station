<script lang="ts" setup>
import type { NotifyApi } from '#/api/core/notify';

import { computed, onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Alert,
  Button,
  Form,
  FormItem,
  Input,
  message,
  Modal,
  Radio,
  Switch,
  Table,
  Tag,
} from 'ant-design-vue';
import dayjs from 'dayjs';

import {
  getNotifyChannelsApi,
  getNotifyConfigApi,
  listNotifyLogsApi,
  manualNotifySendApi,
  saveNotifyConfigApi,
  testNotifySendApi,
} from '#/api/core/notify';

const TextArea = Input.TextArea;

// -------------------------------------------------------------- 通道列表 ----

const channelsLoading = ref(true);
const channels = ref<NotifyApi.ChannelInfo[]>([]);

const enabledCount = computed(() => channels.value.filter((c) => c.enabled).length);
const configuredCount = computed(() => channels.value.filter((c) => c.configured).length);

async function fetchChannels() {
  channelsLoading.value = true;
  try {
    const data = await getNotifyChannelsApi();
    channels.value = data.channels;
  } catch (e: any) {
    message.error(`加载通知通道失败：${e.message}`);
  } finally {
    channelsLoading.value = false;
  }
}

const CHANNEL_CHIP_LABEL = { wecom_webhook: '企业微信', serverchan: 'Server酱', pushplus: 'PushPlus' };

function channelLabel(ch: string) {
  return (CHANNEL_CHIP_LABEL as Record<string, string>)[ch] || ch;
}

// ------------------------------------------------------------ 启用开关 ----

const toggling = ref<string | null>(null);

/** 卡片上的启用开关：切换后自动保存该通道配置（保留已有字段值）。 */
async function toggleEnabled(ch: NotifyApi.ChannelInfo, enabled: boolean) {
  toggling.value = ch.channel;
  try {
    const cfg = await getNotifyConfigApi(ch.channel);
    await saveNotifyConfigApi(ch.channel, {
      webhook_url: cfg.webhook_url,
      sendkey: cfg.sendkey,
      token: cfg.token,
      enabled,
      mention_all: cfg.mention_all,
    });
    message.success(`${ch.label}已${enabled ? '启用' : '停用'}`);
    await fetchChannels();
  } catch (e: any) {
    message.error(`操作失败：${e.message}`);
  } finally {
    toggling.value = null;
  }
}

// ------------------------------------------------------------ 配置弹窗 ----

const modalOpen = ref(false);
const modalLoading = ref(false);
const modalSaving = ref(false);
const modalTesting = ref(false);
const modalChannel = ref<NotifyApi.ChannelInfo | null>(null);
const modalForm = reactive<Record<string, any>>({});
const modalTestResult = ref<NotifyApi.SendResult | null>(null);

async function openConfigModal(ch: NotifyApi.ChannelInfo) {
  modalChannel.value = ch;
  modalTestResult.value = null;
  modalOpen.value = true;
  modalLoading.value = true;
  try {
    const cfg = await getNotifyConfigApi(ch.channel);
    // 按 fields 定义初始化表单：switch 默认 false，其余默认 ''
    for (const field of ch.fields) {
      modalForm[field.key] =
        field.type === 'switch' ? Boolean((cfg as any)[field.key]) : (cfg as any)[field.key] ?? '';
    }
  } catch (e: any) {
    message.error(`加载配置失败：${e.message}`);
  } finally {
    modalLoading.value = false;
  }
}

function buildModalPayload(ch: NotifyApi.ChannelInfo) {
  const payload: any = { webhook_url: '', sendkey: '', token: '', mention_all: false, enabled: false };
  for (const field of ch.fields) {
    if (field.type === 'switch') {
      payload[field.key] = Boolean(modalForm[field.key]);
    } else {
      payload[field.key] = String(modalForm[field.key] ?? '').trim();
    }
  }
  return payload;
}

async function saveModalConfig() {
  if (!modalChannel.value) return;
  const ch = modalChannel.value;
  // 校验必填：非 switch 字段为空则提示
  for (const field of ch.fields) {
    if (field.type !== 'switch' && !String(modalForm[field.key] ?? '').trim()) {
      message.error(`请填写${field.label}`);
      return;
    }
  }
  modalSaving.value = true;
  try {
    await saveNotifyConfigApi(ch.channel, buildModalPayload(ch));
    message.success('配置已保存');
    await fetchChannels();
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    modalSaving.value = false;
  }
}

async function testFromModal() {
  if (!modalChannel.value) return;
  const ch = modalChannel.value;
  modalTesting.value = true;
  modalTestResult.value = null;
  try {
    // 与旧行为一致：先保存当前表单，再触发测试（避免发到旧配置）
    await saveNotifyConfigApi(ch.channel, buildModalPayload(ch));
    const result = await testNotifySendApi(ch.channel);
    modalTestResult.value = result;
    if (!result.success) {
      message.error(`测试发送失败：${result.message}`);
    } else {
      message.success(`测试消息已发送（${ch.label}），请检查微信`);
    }
    await fetchChannels();
    await fetchLogs(1);
  } catch (e: any) {
    message.error(`测试发送失败：${e.message}`);
  } finally {
    modalTesting.value = false;
  }
}

// -------------------------------------------------------------- 发送记录 ----

const logsLoading = ref(false);
const logs = ref<NotifyApi.NotificationLog[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(10);

async function fetchLogs(targetPage = page.value) {
  logsLoading.value = true;
  try {
    const data = await listNotifyLogsApi(targetPage, pageSize.value);
    logs.value = data.items;
    total.value = data.total;
    page.value = data.page;
  } catch (e: any) {
    message.error(`加载发送记录失败：${e.message}`);
  } finally {
    logsLoading.value = false;
  }
}

function onTableChange(pagination: { current?: number; pageSize?: number }) {
  pageSize.value = pagination.pageSize ?? pageSize.value;
  fetchLogs(pagination.current ?? 1);
}

function formatTime(value: null | string) {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-';
}

function orDash(value: null | string) {
  return value ?? '-';
}

const columns = [
  { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 170 },
  { title: '通道', dataIndex: 'channel', key: 'channel', width: 120 },
  { title: '标题', dataIndex: 'title', key: 'title', width: 200 },
  { title: '状态', dataIndex: 'status', key: 'status', width: 90 },
  {
    title: '错误信息',
    dataIndex: 'error_msg',
    key: 'error_msg',
    customRender: ({ text }: { text: null | string }) => orDash(text),
  },
];

const pagination = computed(() => ({
  current: page.value,
  pageSize: pageSize.value,
  total: total.value,
  showSizeChanger: false,
  showTotal: (t: number) => `共 ${t} 条`,
}));

// -------------------------------------------------------------- 手动发送 ----

const manualOpen = ref(false);
const manualSending = ref(false);
const manualForm = reactive({
  channel: '',
  title: '手动通知',
  content: '',
  msgtype: 'text',
});

const manualChannelOptions = computed(() =>
  channels.value
    .filter((c) => c.enabled && !c.not_implemented)
    .map((c) => ({ label: c.label, value: c.channel })),
);

function openManualSend() {
  const options = manualChannelOptions.value;
  if (options.length === 0) {
    message.warning('尚无启用的通知通道，请先在通道列表中配置并启用');
    return;
  }
  manualForm.channel = manualForm.channel || options[0]!.value;
  manualOpen.value = true;
}

async function submitManualSend() {
  if (!manualForm.channel) {
    message.error('请选择接收通道');
    return;
  }
  if (!manualForm.content.trim()) {
    message.error('请填写发送内容');
    return;
  }
  manualSending.value = true;
  try {
    const result = await manualNotifySendApi({
      channel: manualForm.channel,
      title: manualForm.title.trim() || '手动通知',
      content: manualForm.content,
      msgtype: manualForm.msgtype,
    });
    if (!result.success) {
      message.error(`发送失败：${result.message}`);
    } else {
      message.success('已发送');
      manualOpen.value = false;
    }
    await fetchLogs(1);
  } catch (e: any) {
    message.error(`发送失败：${e.message}`);
  } finally {
    manualSending.value = false;
  }
}

// ---------------------------------------------------------------- 初始化 ----

onMounted(() => {
  fetchChannels();
  fetchLogs(1);
});
</script>

<template>
  <Page :auto-content-height="false">
    <div class="nt-page">
      <!-- ============================ 页面头部 ============================ -->
      <div class="nt-header">
        <div class="nt-header-main">
          <div class="nt-header-title">
            <h2>消息通知</h2>
            <div class="nt-header-badge">{{ configuredCount }} 个通道 · {{ enabledCount }} 个已启用</div>
          </div>
          <p>任务完成 / 失败时自动推送 · 多通道可同时启用，配置一次全局生效</p>
        </div>
        <Button class="nt-btn" @click="openManualSend">手动发送</Button>
      </div>

      <!-- ============================ 通道列表（等高卡片） ============================ -->
      <div v-if="channelsLoading" class="nt-empty">加载中…</div>
      <div v-else class="nt-channel-list">
        <div
          v-for="ch in channels"
          :key="ch.channel"
          class="nt-channel-card"
          :class="{ 'nt-channel-card--plain': !ch.configured }"
        >
          <div class="nt-channel-icon" :class="{ 'nt-channel-icon--muted': !ch.configured }">
            <svg
              v-if="ch.icon === 'message-circle'"
              width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
            >
              <path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7a8.5 8.5 0 1 1 16.1-3.8z" />
            </svg>
            <svg
              v-else-if="ch.icon === 'send'"
              width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
            >
              <path d="M22 2 11 13" />
              <path d="M22 2 15 22l-4-9-9-4z" />
            </svg>
            <svg
              v-else
              width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
            >
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.73 21a2 2 0 0 1-3.46 0" />
            </svg>
          </div>

          <div class="nt-channel-body">
            <div class="nt-channel-name-row">
              <span class="nt-channel-name">{{ ch.label }}</span>
              <span v-if="ch.not_implemented" class="nt-chip nt-chip--muted">未接入</span>
              <span v-else-if="ch.enabled" class="nt-chip nt-chip--success">已启用</span>
              <span v-else-if="ch.configured" class="nt-chip">已配置</span>
              <span v-else class="nt-chip nt-chip--muted">未配置</span>
            </div>
            <p class="nt-channel-desc" :title="ch.description">{{ ch.description }}</p>
          </div>

          <div class="nt-channel-actions">
            <Button size="small" class="nt-mini-btn" @click="openConfigModal(ch)">
              {{ ch.configured || ch.not_implemented ? '配置' : '去配置' }}
            </Button>
            <Button
              v-if="ch.configured && !ch.not_implemented"
              size="small"
              class="nt-mini-btn"
              @click="testNotifySendApi(ch.channel).then((r) => (r.success ? message.success('测试消息已发送，请检查微信') : message.error(`测试发送失败：${r.message}`)))"
            >
              测试
            </Button>
            <Switch
              v-if="!ch.not_implemented"
              :checked="ch.enabled"
              :loading="toggling === ch.channel"
              size="small"
              @change="(v) => toggleEnabled(ch, Boolean(v))"
            />
          </div>
        </div>
      </div>

      <!-- ============================ 发送记录 ============================ -->
      <div class="nt-card">
        <div class="nt-card-head">
          <div class="nt-card-head-left">
            <span class="nt-module-icon" style="background: rgba(107, 114, 128, 0.14); color: hsl(var(--muted-foreground))">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <path d="M14 2v6h6" />
                <path d="M8 13h8M8 17h5" />
              </svg>
            </span>
            <div class="nt-card-head-text">
              <div class="nt-card-title">发送记录</div>
              <div class="nt-card-desc">最近的通知发送历史，失败可查看错误原因</div>
            </div>
          </div>
        </div>
        <Table
          row-key="id"
          :loading="logsLoading"
          :data-source="logs"
          :columns="columns"
          :pagination="pagination"
          :scroll="{ x: 800 }"
          @change="onTableChange"
        >
          <template #bodyCell="{ column, text }">
            <Tag v-if="column.key === 'status'" :color="text === 'success' ? 'success' : 'error'">
              {{ text === 'success' ? '成功' : '失败' }}
            </Tag>
            <span v-else-if="column.key === 'created_at'" class="nt-time">
              {{ formatTime(text as string) }}
            </span>
            <span v-else-if="column.key === 'channel'" class="nt-channel-tag">
              {{ channelLabel(text as string) }}
            </span>
          </template>
        </Table>
      </div>
    </div>

    <!-- ============================ 配置弹窗（数据驱动） ============================ -->
    <Modal
      v-model:open="modalOpen"
      :title="modalChannel?.label"
      :footer="null"
      width="520px"
    >
      <div v-if="modalLoading" class="nt-empty">加载中…</div>
      <template v-else-if="modalChannel">
        <div v-if="modalChannel.not_implemented" class="nt-modal-desc">
          {{ modalChannel.label }} 为预留通道，暂未接入发送能力，敬请期待。
        </div>
        <Form v-else layout="vertical">
          <FormItem v-for="field in modalChannel.fields" :key="field.key" :label="field.label">
            <template v-if="field.type === 'switch'">
              <Switch v-model:checked="modalForm[field.key]" />
            </template>
            <template v-else-if="field.type === 'textarea'">
              <TextArea
                v-model:value="modalForm[field.key]"
                :rows="2"
                :class="{ 'nt-mono-input': field.mono }"
                :placeholder="field.placeholder || ''"
              />
            </template>
            <template v-else-if="field.type === 'password'">
              <Input.Password
                v-model:value="modalForm[field.key]"
                :class="{ 'nt-mono-input': field.mono }"
                :placeholder="field.placeholder || ''"
              />
            </template>
            <template v-else>
              <Input
                v-model:value="modalForm[field.key]"
                :class="{ 'nt-mono-input': field.mono }"
                :placeholder="field.placeholder || ''"
              />
            </template>
            <div v-if="field.extra" class="nt-field-extra">{{ field.extra }}</div>
          </FormItem>

          <div class="nt-actions">
            <Button type="primary" :loading="modalSaving" class="nt-btn" @click="saveModalConfig">
              保存配置
            </Button>
            <Button :loading="modalTesting" class="nt-btn" @click="testFromModal">
              测试发送
            </Button>
          </div>
          <Alert
            v-if="modalTestResult"
            :type="modalTestResult.success ? 'success' : 'error'"
            :message="modalTestResult.success ? '测试消息已发送' : '测试发送失败'"
            :description="modalTestResult.message"
            show-icon
            class="nt-alert"
          />
        </Form>
      </template>
    </Modal>

    <!-- ============================ 手动发送弹窗 ============================ -->
    <Modal v-model:open="manualOpen" title="手动发送" :footer="null" width="480px">
      <div class="nt-modal-desc">自定义内容推送到选中的启用通道，正文支持 Markdown。</div>
      <Form layout="vertical">
        <FormItem label="接收通道">
          <Radio.Group v-model:value="manualForm.channel">
            <Radio v-for="opt in manualChannelOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </Radio>
          </Radio.Group>
        </FormItem>
        <FormItem label="标题（Server酱 通道作为消息标题）">
          <Input v-model:value="manualForm.title" placeholder="手动通知" />
        </FormItem>
        <FormItem label="内容">
          <TextArea
            v-model:value="manualForm.content"
            :rows="5"
            placeholder="要发送的消息内容（markdown 类型支持 # 标题、**加粗** 等语法）"
          />
        </FormItem>
        <Button type="primary" block :loading="manualSending" @click="submitManualSend">
          发送
        </Button>
      </Form>
    </Modal>
  </Page>
</template>

<style>
/* ================= 主题变量（全局定义，供页面与 Modal 弹窗共用） ================= */
:root {
  --nt-bg: #ffffff;
  --nt-bg-soft: #f7f8fa;
  --nt-border: rgba(23, 33, 48, 0.08);
  --nt-border-strong: rgba(23, 33, 48, 0.14);
  --nt-text: #1f2733;
  --nt-text-2: #6b7280;
  --nt-text-3: #9ca3af;
  --nt-hover: rgba(23, 33, 48, 0.045);
  --nt-shadow: 0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 3px rgba(16, 24, 40, 0.07);
  --nt-shadow-lg: 0 4px 12px rgba(16, 24, 40, 0.08), 0 2px 4px rgba(16, 24, 40, 0.05);
  --nt-primary: #4f6ef7;
}

:root.dark,
body.dark {
  --nt-bg: #191c24;
  --nt-bg-soft: #1e222c;
  --nt-border: rgba(255, 255, 255, 0.08);
  --nt-border-strong: rgba(255, 255, 255, 0.14);
  --nt-text: #e6e9f0;
  --nt-text-2: #98a0b3;
  --nt-text-3: #6b7280;
  --nt-hover: rgba(255, 255, 255, 0.05);
  --nt-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
  --nt-shadow-lg: 0 4px 14px rgba(0, 0, 0, 0.4);
}
</style>

<style scoped>
.nt-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  /* 与其他设置页保持一致：全宽贴左（不居中、不缩窄），避免宽屏下两侧留白 */
  width: 100%;
  padding: 4px 2px 24px;
  color: var(--nt-text);
}

/* ================= 页面头部 ================= */
.nt-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.nt-header-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.nt-header-title h2 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.2px;
  line-height: 1.3;
}

.nt-header-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 9px;
  border-radius: 999px;
  color: var(--nt-primary);
  background: color-mix(in srgb, var(--nt-primary) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--nt-primary) 25%, transparent);
}

.nt-header-main p {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--nt-text-2);
}

/* ================= 通道列表（等高卡片） ================= */
.nt-channel-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 折叠态固定高度 68px：外观/长短/高度完全一致 */
.nt-channel-card {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 68px;
  box-sizing: border-box;
  padding: 16px;
  background: var(--nt-bg);
  border: 1px solid var(--nt-border-strong);
  border-radius: 12px;
  box-shadow: var(--nt-shadow);
  transition: border-color 0.2s, box-shadow 0.2s;
}

.nt-channel-card:hover {
  border-color: var(--nt-border-strong);
  box-shadow: var(--nt-shadow-lg);
}

.nt-channel-card--plain {
  border-style: dashed;
  border-color: var(--nt-border-strong);
  box-shadow: none;
}

.nt-channel-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--nt-primary) 12%, transparent);
  color: var(--nt-primary);
}

.nt-channel-icon--muted {
  background: var(--nt-bg-soft);
  color: var(--nt-text-3);
}

.nt-channel-body {
  flex: 1;
  min-width: 0;
}

.nt-channel-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.nt-channel-name {
  font-size: 13.5px;
  font-weight: 500;
  color: var(--nt-text);
}

.nt-chip {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--nt-bg-soft);
  border: 1px solid var(--nt-border);
  color: var(--nt-text-2);
}

.nt-chip--success {
  color: #10b981;
  background: color-mix(in srgb, #10b981 12%, transparent);
  border-color: color-mix(in srgb, #10b981 25%, transparent);
}

.nt-chip--muted {
  color: var(--nt-text-3);
}

/* 描述固定单行 + 省略号：保证卡片等高 */
.nt-channel-desc {
  margin: 3px 0 0;
  font-size: 12px;
  color: var(--nt-text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nt-channel-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.nt-mini-btn {
  font-size: 12px;
  height: 28px;
  border-radius: 8px;
  padding-inline: 12px;
}

/* ================= 卡片（记录区） ================= */
.nt-card {
  background: var(--nt-bg);
  border: 1px solid var(--nt-border);
  border-radius: 14px;
  box-shadow: var(--nt-shadow);
  transition: border-color 0.2s, box-shadow 0.2s;
  overflow: hidden;
}

.nt-card:hover {
  border-color: var(--nt-border-strong);
  box-shadow: var(--nt-shadow-lg);
}

.nt-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 15px 16px 12px;
  border-bottom: 1px dashed var(--nt-border);
}

.nt-card-head-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.nt-module-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: rgba(79, 110, 247, 0.12);
  color: var(--nt-primary);
}

.nt-card-head-text {
  min-width: 0;
}

.nt-card-title {
  font-size: 14px;
  font-weight: 600;
}

.nt-card-desc {
  margin-top: 3px;
  font-size: 12px;
  color: var(--nt-text-2);
}

.nt-card .ant-form {
  padding: 16px;
}

/* ================= 表单/弹窗 ================= */
.nt-mono-input {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.nt-field-extra {
  margin-top: 4px;
  font-size: 12px;
  color: var(--nt-text-3);
}

.nt-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.nt-btn {
  border-radius: 8px;
  height: 34px;
  padding-inline: 16px;
  font-weight: 500;
}

.nt-alert {
  margin-top: 14px;
}

/* ================= 发送记录 ================= */
.nt-time {
  font-variant-numeric: tabular-nums;
  font-size: 12.5px;
}

.nt-channel-tag {
  font-size: 12px;
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--nt-bg-soft);
  border: 1px solid var(--nt-border);
  color: var(--nt-text-2);
}

.nt-empty {
  padding: 26px 12px;
  text-align: center;
  color: var(--nt-text-3);
  font-size: 12.5px;
}

/* ================= 手动发送弹窗 ================= */
.nt-modal-desc {
  margin-bottom: 14px;
  padding: 9px 12px;
  border-radius: 8px;
  font-size: 12.5px;
  color: var(--nt-text-2);
  background: var(--nt-bg-soft);
  border: 1px solid var(--nt-border);
}
</style>
