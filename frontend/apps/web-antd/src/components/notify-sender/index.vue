<script lang="ts" setup>
import type { NotifyApi } from '#/api/core/notify';

import { onMounted, ref, watch } from 'vue';

import { useRouter } from 'vue-router';

import { Button, Form, FormItem, Input, message, Modal } from 'ant-design-vue';

import { getNotifyChannelsApi, manualNotifySendApi } from '#/api/core/notify';

const TextArea = Input.TextArea;

// 可复用「发送通知」弹窗：任意模块按钮唤起，自动查询已启用通道供选择并发送。
// 用法：<NotifySenderModal v-model:open="state.open" :context="'任务中心'" />
const open = defineModel<boolean>('open', { default: false });

const props = withDefaults(
  defineProps<{
    /** 来源模块名，展示在弹窗头部（如 '任务中心'） */
    context?: string;
    /** 预填标题 */
    defaultTitle?: string;
    /** 预填内容 */
    defaultContent?: string;
  }>(),
  {
    context: '',
    defaultTitle: '',
    defaultContent: '',
  },
);

const emit = defineEmits<{ sent: [] }>();

const router = useRouter();

const loading = ref(false);
const sending = ref(false);
const channels = ref<NotifyApi.ChannelInfo[]>([]);
const selectedChannel = ref('');
const form = ref({ title: '', content: '' });

// 仅列出已启用且已接入的通道
const usableChannels = () => channels.value.filter((c) => c.enabled && !c.not_implemented);

async function fetchChannels() {
  loading.value = true;
  try {
    const data = await getNotifyChannelsApi();
    channels.value = data.channels;
    const usable = usableChannels();
    if (usable.length > 0 && !usable.some((c) => c.channel === selectedChannel.value)) {
      selectedChannel.value = usable[0]!.channel;
    }
  } catch (e: any) {
    message.error(`加载通知通道失败：${e.message}`);
  } finally {
    loading.value = false;
  }
}

watch(open, (val) => {
  if (val) {
    form.value.title = props.defaultTitle;
    form.value.content = props.defaultContent;
    fetchChannels();
  }
});

onMounted(() => {
  if (open.value) {
    fetchChannels();
  }
});

async function submitSend() {
  if (!selectedChannel.value) {
    message.error('请选择接收通道');
    return;
  }
  if (!form.value.content.trim()) {
    message.error('请填写发送内容');
    return;
  }
  sending.value = true;
  try {
    const result = await manualNotifySendApi({
      channel: selectedChannel.value,
      title: form.value.title.trim() || '手动通知',
      content: form.value.content,
    });
    if (!result.success) {
      message.error(`发送失败：${result.message}`);
      return;
    }
    message.success('已发送');
    emit('sent');
    open.value = false;
  } catch (e: any) {
    message.error(`发送失败：${e.message}`);
  } finally {
    sending.value = false;
  }
}

function goConfig() {
  open.value = false;
  router.push('/settings/notify');
}
</script>

<template>
  <Modal v-model:open="open" :title="'发送通知'" :footer="null" width="520px">
    <div class="nts-desc">
      {{ context ? `来自 · ${context}` : '选择接收通道，发送内容将按通道格式自动适配' }}
    </div>

    <div v-if="loading" class="nts-empty">加载中…</div>

    <!-- 无可用通道：空态引导 -->
    <div v-else-if="usableChannels().length === 0" class="nts-empty-state">
      <div class="nts-empty-icon">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 8v4M12 16h.01" />
        </svg>
      </div>
      <p class="nts-empty-title">还没有可用的通知通道</p>
      <p class="nts-empty-text">请先在「系统设置 → 消息通知」中配置并启用至少一个通道</p>
      <Button type="primary" size="small" class="nts-btn" @click="goConfig">去配置</Button>
    </div>

    <!-- 正常表单 -->
    <template v-else>
      <Form layout="vertical">
        <FormItem label="接收通道（仅列出已启用的通道）">
          <div class="nts-channels">
            <label
              v-for="ch in usableChannels()"
              :key="ch.channel"
              class="nts-channel-option"
              :class="{ 'nts-channel-option--active': selectedChannel === ch.channel }"
            >
              <input v-model="selectedChannel" type="radio" :value="ch.channel" class="nts-radio" />
              <span class="nts-channel-label">{{ ch.label }}</span>
              <span v-for="cap in ch.capabilities" :key="cap" class="nts-cap">
                {{ cap === 'mention_all' ? '@所有人' : cap === 'markdown' ? 'Markdown' : cap === 'text' ? '文本' : cap }}
              </span>
            </label>
          </div>
        </FormItem>
        <FormItem label="标题">
          <Input v-model:value="form.title" placeholder="通知标题（Server酱 作为消息标题）" />
        </FormItem>
        <FormItem label="内容（支持 Markdown）">
          <TextArea v-model:value="form.content" :rows="4" placeholder="要发送的消息内容" />
        </FormItem>
        <div class="nts-actions">
          <Button class="nts-btn" @click="open = false">取消</Button>
          <Button type="primary" :loading="sending" class="nts-btn" @click="submitSend">
            发送
          </Button>
        </div>
      </Form>
    </template>
  </Modal>
</template>

<style scoped>
.nts-desc {
  margin-bottom: 14px;
  padding: 9px 12px;
  border-radius: 8px;
  font-size: 12.5px;
  color: var(--nt-text-2, #6b7280);
  background: var(--nt-bg-soft, #f7f8fa);
  border: 1px solid var(--nt-border, rgba(23, 33, 48, 0.08));
}

.nts-channels {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.nts-channel-option {
  display: flex;
  align-items: center;
  gap: 9px;
  border: 1px solid var(--nt-border, rgba(23, 33, 48, 0.14));
  border-radius: 10px;
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color 0.2s;
}

.nts-channel-option--active {
  border-color: var(--nt-primary, #4f6ef7);
  background: color-mix(in srgb, var(--nt-primary, #4f6ef7) 6%, transparent);
}

.nts-radio {
  accent-color: var(--nt-primary, #4f6ef7);
  margin: 0;
}

.nts-channel-label {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--nt-text, #1f2733);
}

.nts-cap {
  font-size: 11px;
  color: var(--nt-text-3, #9ca3af);
  background: var(--nt-bg-soft, #f7f8fa);
  border: 1px solid var(--nt-border, rgba(23, 33, 48, 0.08));
  border-radius: 999px;
  padding: 0 7px;
}

.nts-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.nts-btn {
  border-radius: 8px;
  font-size: 12.5px;
  height: 32px;
  padding-inline: 14px;
}

.nts-empty {
  padding: 24px 12px;
  text-align: center;
  color: var(--nt-text-3, #9ca3af);
  font-size: 12.5px;
}

.nts-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 26px 16px 22px;
  text-align: center;
}

.nts-empty-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: var(--nt-bg-soft, #f7f8fa);
  color: var(--nt-text-3, #9ca3af);
  margin-bottom: 4px;
}

.nts-empty-title {
  margin: 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--nt-text, #1f2733);
}

.nts-empty-text {
  margin: 2px 0 12px;
  font-size: 12px;
  color: var(--nt-text-2, #6b7280);
}
</style>
