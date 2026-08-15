<script lang="ts" setup>
import type { NotifyApi } from '#/api/core/notify';

import { computed, onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { Alert, Button, Form, FormItem, Input, message, Modal, Switch, Table, Tag } from 'ant-design-vue';
import dayjs from 'dayjs';

import {
  getNotifyConfigApi,
  listNotifyLogsApi,
  manualNotifySendApi,
  saveNotifyConfigApi,
  testNotifySendApi,
} from '#/api/core/notify';

const TextArea = Input.TextArea;

// -------------------------------------------------------------- 配置表单 ----

const configLoading = ref(true);
const configSaving = ref(false);
const form = reactive<NotifyApi.NotificationConfigIn>({
  webhook_url: '',
  enabled: false,
  mention_all: false,
});

async function fetchConfig() {
  configLoading.value = true;
  try {
    const config = await getNotifyConfigApi();
    form.webhook_url = config.webhook_url;
    form.enabled = config.enabled;
    form.mention_all = config.mention_all;
  } catch (e: any) {
    message.error(`加载配置失败：${e.message}`);
  } finally {
    configLoading.value = false;
  }
}

async function saveConfig() {
  if (!form.webhook_url.trim()) {
    message.error('请先填写企业微信机器人 Webhook 地址');
    return;
  }
  configSaving.value = true;
  try {
    await saveNotifyConfigApi({
      webhook_url: form.webhook_url.trim(),
      enabled: form.enabled,
      mention_all: form.mention_all,
    });
    message.success('配置已保存');
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    configSaving.value = false;
  }
}

// -------------------------------------------------------------- 测试 / 手动发送 ----

const testing = ref(false);
const testResult = ref<NotifyApi.SendResult | null>(null);

async function testSend() {
  if (!form.webhook_url.trim()) {
    message.error('请先填写 Webhook 地址');
    return;
  }
  testing.value = true;
  testResult.value = null;
  try {
    // 后端测试发送读的是【已保存】配置，先保存当前表单再触发测试，避免发到旧地址/误报未配置
    await saveNotifyConfigApi({
      webhook_url: form.webhook_url.trim(),
      enabled: form.enabled,
      mention_all: form.mention_all,
    });
    testResult.value = await testNotifySendApi();
    if (!testResult.value.success) {
      message.error(`测试发送失败：${testResult.value.message}`);
    } else {
      message.success('测试消息已发送，请检查企业微信');
    }
    await fetchLogs(1);
  } catch (e: any) {
    message.error(`测试发送失败：${e.message}`);
  } finally {
    testing.value = false;
  }
}

const manualOpen = ref(false);
const manualSending = ref(false);
const manualForm = reactive({ title: '手动通知', content: '', msgtype: 'text' });

async function submitManualSend() {
  if (!form.webhook_url.trim()) {
    message.error('请先填写 Webhook 地址');
    return;
  }
  if (!manualForm.content.trim()) {
    message.error('请填写发送内容');
    return;
  }
  manualSending.value = true;
  try {
    // 与测试发送一致：后端读取的是【已保存】配置，先保存当前表单再发送
    await saveNotifyConfigApi({
      webhook_url: form.webhook_url.trim(),
      enabled: form.enabled,
      mention_all: form.mention_all,
    });
    const result = await manualNotifySendApi({
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

onMounted(() => {
  fetchConfig();
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
            <div class="nt-header-badge">企业微信</div>
          </div>
          <p>任务完成 / 失败时自动推送到企业微信群机器人，配置一次全局生效</p>
        </div>
      </div>

      <!-- ============================ 配置卡片 ============================ -->
      <div class="nt-card">
        <div class="nt-card-head">
          <div class="nt-card-head-left">
            <span class="nt-module-icon">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7a8.5 8.5 0 1 1 16.1-3.8z" />
              </svg>
            </span>
            <div class="nt-card-head-text">
              <div class="nt-card-title">企业微信机器人</div>
              <div class="nt-card-desc">在群聊中添加「群机器人」获取 Webhook 地址</div>
            </div>
          </div>
        </div>
        <div v-if="configLoading" class="nt-empty">加载中…</div>
        <Form v-else layout="vertical">
          <FormItem
            label="Webhook 地址"
            :extra="'从企业微信群机器人复制完整地址，如 ' + 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx'"
          >
            <TextArea
              v-model:value="form.webhook_url"
              :rows="2"
              class="nt-mono-input"
              placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key"
            />
          </FormItem>
          <div class="nt-switch-row">
            <div class="nt-switch-item">
              <Switch v-model:checked="form.enabled" />
              <div class="nt-switch-text">
                <b>启用任务通知</b>
                <span>开启后，任务中心的任务完成 / 失败会自动推送</span>
              </div>
            </div>
            <div class="nt-switch-item">
              <Switch v-model:checked="form.mention_all" />
              <div class="nt-switch-text">
                <b>@所有人</b>
                <span>text 消息附带 @all，适合需要强提醒的群</span>
              </div>
            </div>
          </div>
          <div class="nt-actions">
            <Button type="primary" :loading="configSaving" class="nt-btn" @click="saveConfig">
              保存配置
            </Button>
            <Button :loading="testing" class="nt-btn" @click="testSend">
              测试发送
            </Button>
            <Button class="nt-btn" @click="manualOpen = true">手动发送</Button>
          </div>
          <Alert
            v-if="testResult"
            :type="testResult.success ? 'success' : 'error'"
            :message="testResult.success ? '测试消息已发送' : '测试发送失败'"
            :description="testResult.message"
            show-icon
            class="nt-alert"
          />
        </Form>
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
          :scroll="{ x: 720 }"
          @change="onTableChange"
        >
          <template #bodyCell="{ column, text }">
            <Tag v-if="column.key === 'status'" :color="text === 'success' ? 'success' : 'error'">
              {{ text === 'success' ? '成功' : '失败' }}
            </Tag>
            <span v-else-if="column.key === 'created_at'" class="nt-time">
              {{ formatTime(text as string) }}
            </span>
          </template>
        </Table>
      </div>
    </div>

    <!-- ============================ 手动发送弹窗 ============================ -->
    <Modal v-model:open="manualOpen" title="手动发送" :footer="null" width="480px">
      <div class="nt-modal-desc">自定义内容推送到企业微信，支持 text 与 markdown 两种格式。</div>
      <Form layout="vertical">
        <FormItem label="消息类型">
          <div class="nt-msgtype-row">
            <Button
              :type="manualForm.msgtype === 'text' ? 'primary' : 'default'"
              size="small"
              @click="manualForm.msgtype = 'text'"
            >
              text
            </Button>
            <Button
              :type="manualForm.msgtype === 'markdown' ? 'primary' : 'default'"
              size="small"
              @click="manualForm.msgtype = 'markdown'"
            >
              markdown
            </Button>
          </div>
        </FormItem>
        <FormItem label="标题（记录用）">
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
  max-width: 960px;
  margin: 0 auto;
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

/* ================= 卡片 ================= */
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

/* ================= 表单 ================= */
.nt-card .ant-form {
  padding: 16px;
}

.nt-mono-input {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.nt-switch-row {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
}

.nt-switch-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 11px 12px;
  border-radius: 10px;
  background: var(--nt-bg-soft);
  border: 1px solid var(--nt-border);
}

.nt-switch-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12.5px;
  color: var(--nt-text-2);
}

.nt-switch-text b {
  font-size: 13px;
  color: var(--nt-text);
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

.nt-msgtype-row {
  display: flex;
  gap: 8px;
}
</style>
