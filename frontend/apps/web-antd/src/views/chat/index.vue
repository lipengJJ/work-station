<script lang="ts" setup>
import type { ChatApi } from '#/api/core/chat';

import { nextTick, onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Avatar,
  Button,
  Card,
  Empty,
  Form,
  FormItem,
  Input,
  message,
  Modal,
  Spin,
} from 'ant-design-vue';

import {
  clearChatMessagesApi,
  getChatConfigApi,
  listChatMessagesApi,
  setChatConfigApi,
  streamChatApi,
} from '#/api/core/chat';

const TextArea = Input.TextArea;
const PasswordInput = Input.Password;

const DEFAULT_MODEL = 'gemini-2.0-flash';

const loading = ref(true);
const config = ref<ChatApi.Config>({ configured: false, model: DEFAULT_MODEL });

const setupForm = reactive({ api_key: '', model: DEFAULT_MODEL });
const setupSaving = ref(false);
const setupModalOpen = ref(false);

const messages = ref<ChatApi.Message[]>([]);
const inputText = ref('');
const sending = ref(false);
const scrollRef = ref<HTMLElement>();

async function loadConfig() {
  config.value = await getChatConfigApi();
  setupForm.model = config.value.model || DEFAULT_MODEL;
}

async function loadMessages() {
  messages.value = await listChatMessagesApi();
  await scrollToBottom();
}

async function scrollToBottom() {
  await nextTick();
  const el = scrollRef.value;
  if (el) el.scrollTop = el.scrollHeight;
}

async function saveSetup() {
  const apiKey = setupForm.api_key.trim();
  if (!config.value.configured && !apiKey) {
    message.error('请填写 Gemini API Key');
    return;
  }
  setupSaving.value = true;
  try {
    config.value = await setChatConfigApi({
      api_key: apiKey || undefined,
      model: setupForm.model.trim() || DEFAULT_MODEL,
    });
    setupModalOpen.value = false;
    setupForm.api_key = '';
    message.success('已保存');
    if (messages.value.length === 0) {
      await loadMessages();
    }
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    setupSaving.value = false;
  }
}

function openSetupModal() {
  setupForm.api_key = '';
  setupForm.model = config.value.model || DEFAULT_MODEL;
  setupModalOpen.value = true;
}

async function sendMessage() {
  const content = inputText.value.trim();
  if (!content || sending.value) return;
  if (!config.value.configured) {
    message.error('请先配置 Gemini API Key');
    return;
  }

  inputText.value = '';
  messages.value.push({
    id: -Date.now(),
    role: 'user',
    content,
    created_at: new Date().toISOString(),
  });
  const assistantMsg: ChatApi.Message = {
    id: -Date.now() - 1,
    role: 'assistant',
    content: '',
    created_at: new Date().toISOString(),
  };
  messages.value.push(assistantMsg);
  await scrollToBottom();

  sending.value = true;
  try {
    await streamChatApi(content, {
      onDelta: (delta) => {
        assistantMsg.content += delta;
        scrollToBottom();
      },
      onError: (err) => {
        message.error(err);
        assistantMsg.content += `\n\n[出错了：${err}]`;
      },
      onEnd: () => {
        sending.value = false;
      },
    });
  } catch (e: any) {
    message.error(`发送失败：${e.message}`);
    sending.value = false;
  }
}

function handleEnter(e: KeyboardEvent) {
  if (e.shiftKey) return;
  e.preventDefault();
  sendMessage();
}

function clearConversation() {
  Modal.confirm({
    title: '确定清空当前对话吗？',
    content: '历史消息会被永久删除，此操作不可恢复。',
    okType: 'danger',
    onOk: async () => {
      try {
        await clearChatMessagesApi();
        messages.value = [];
        message.success('已清空');
      } catch (e: any) {
        message.error(`清空失败：${e.message}`);
      }
    },
  });
}

onMounted(async () => {
  try {
    await loadConfig();
    if (config.value.configured) {
      await loadMessages();
    }
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <Page :auto-content-height="true">
    <Spin :spinning="loading">
      <Card v-if="!loading && !config.configured" title="配置 Gemini API Key">
        <Empty description="首次使用需要配置 Gemini API Key 才能开始对话" />
        <Form layout="vertical" style="max-width: 480px; margin: 16px auto 0">
          <FormItem label="Gemini API Key">
            <PasswordInput
              v-model:value="setupForm.api_key"
              placeholder="从 Google AI Studio 获取的 API Key"
            />
          </FormItem>
          <FormItem label="模型" extra="不确定的话保持默认即可，之后可以在这里重新修改">
            <Input v-model:value="setupForm.model" :placeholder="DEFAULT_MODEL" />
          </FormItem>
          <Button type="primary" block :loading="setupSaving" @click="saveSetup">保存并开始</Button>
        </Form>
      </Card>

      <div v-else-if="!loading" style="display: flex; flex-direction: column; height: 100%">
        <div style="display: flex; align-items: center; margin-bottom: 12px; gap: 8px">
          <span style="font-size: 16px; font-weight: 500">AI 助手</span>
          <span style="color: rgba(0, 0, 0, 0.45); font-size: 12px">{{ config.model }}</span>
          <span style="flex: 1"></span>
          <Button size="small" @click="openSetupModal">模型设置</Button>
          <Button size="small" danger @click="clearConversation">清空对话</Button>
        </div>

        <div
          ref="scrollRef"
          style="flex: 1; overflow-y: auto; padding: 8px 4px; min-height: 0"
        >
          <Empty v-if="!messages.length" description="发条消息开始对话吧" style="margin-top: 64px" />
          <div
            v-for="msg in messages"
            :key="msg.id"
            style="display: flex; margin-bottom: 16px; gap: 8px"
            :style="{ flexDirection: msg.role === 'user' ? 'row-reverse' : 'row' }"
          >
            <Avatar :style="{ backgroundColor: msg.role === 'user' ? '#1677ff' : '#8c8c8c' }">
              {{ msg.role === 'user' ? '我' : 'AI' }}
            </Avatar>
            <div
              style="max-width: 70%; padding: 8px 12px; border-radius: 8px; white-space: pre-wrap; word-break: break-word"
              :style="{
                backgroundColor: msg.role === 'user' ? '#1677ff' : '#f5f5f5',
                color: msg.role === 'user' ? '#fff' : 'inherit',
              }"
            >
              {{ msg.content || (sending && msg.role === 'assistant' ? '思考中…' : '') }}
            </div>
          </div>
        </div>

        <div style="display: flex; gap: 8px; padding-top: 8px">
          <TextArea
            v-model:value="inputText"
            :auto-size="{ minRows: 1, maxRows: 6 }"
            placeholder="输入消息，Enter 发送，Shift+Enter 换行"
            :disabled="sending"
            @keydown.enter="handleEnter"
          />
          <Button type="primary" :loading="sending" @click="sendMessage">发送</Button>
        </div>
      </div>
    </Spin>

    <Modal v-model:open="setupModalOpen" title="模型设置" :footer="null" width="480px">
      <Form layout="vertical">
        <FormItem label="Gemini API Key" extra="留空表示不修改已保存的 Key">
          <PasswordInput v-model:value="setupForm.api_key" placeholder="重新输入以更换 Key" />
        </FormItem>
        <FormItem label="模型">
          <Input v-model:value="setupForm.model" :placeholder="DEFAULT_MODEL" />
        </FormItem>
        <Button type="primary" block :loading="setupSaving" @click="saveSetup">保存</Button>
      </Form>
    </Modal>
  </Page>
</template>
