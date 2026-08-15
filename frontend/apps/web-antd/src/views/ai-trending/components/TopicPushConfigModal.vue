<script lang="ts" setup>
import type { AiTrendingApi } from '#/api/core/ai-trending';

import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';

import { reactive, ref, watch } from 'vue';

import { Alert, Button, message, Modal, Select, Switch, TimePicker } from 'ant-design-vue';

import {
  getTopicPushConfigApi,
  updateTopicPushConfigApi,
} from '#/api/core/ai-trending';

const props = defineProps<{
  open: boolean;
  topicId: number;
  topicName: string;
}>();

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void;
  (e: 'saved'): void;
}>();

const CHANNEL_OPTIONS = [
  { value: 'wecom', label: '企业微信' },
  { value: 'dingtalk', label: '钉钉' },
  { value: 'feishu', label: '飞书' },
  { value: 'email', label: '邮件' },
];

const FREQUENCY_OPTIONS = [
  { value: 'daily', label: '每天' },
  { value: 'hourly', label: '每小时（即将支持）', disabled: true },
];

const loading = ref(false);
const saving = ref(false);
const form = reactive<AiTrendingApi.TopicPushConfig>({
  enabled: false,
  channel: 'wecom',
  frequency: 'daily',
  time: '09:00',
});
const timeValue = ref<Dayjs>(dayjs('09:00', 'HH:mm'));

watch(
  () => props.open,
  (open) => {
    if (!open) return;
    void loadConfig();
  },
);

async function loadConfig() {
  loading.value = true;
  try {
    const cfg = await getTopicPushConfigApi(props.topicId);
    form.enabled = cfg.enabled;
    form.channel = cfg.channel;
    form.frequency = cfg.frequency;
    form.time = cfg.time;
    timeValue.value = dayjs(cfg.time, 'HH:mm');
  } catch (e: any) {
    message.error(e?.message || '推送配置加载失败');
  } finally {
    loading.value = false;
  }
}

function onTimeChange(value: Dayjs | string | null) {
  if (typeof value === 'string') {
    form.time = value || '09:00';
  } else {
    form.time = value ? value.format('HH:mm') : '09:00';
  }
}

async function save() {
  saving.value = true;
  try {
    const saved = await updateTopicPushConfigApi(props.topicId, {
      ...form,
      time: timeValue.value.format('HH:mm'),
    });
    Object.assign(form, saved);
    message.success('推送配置已保存');
    emit('update:open', false);
    emit('saved');
  } catch (e: any) {
    message.error(e?.message || '保存失败');
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Modal
    :open="open"
    :title="`推送配置 - ${topicName}`"
    width="520px"
    :footer="null"
    @cancel="emit('update:open', false)"
  >
    <div class="flex flex-col gap-4 py-2">
      <!-- 总开关 -->
      <div class="flex items-center justify-between gap-3">
        <div class="text-sm text-[hsl(var(--foreground))]">开启主题推送</div>
        <Switch v-model:checked="form.enabled" />
      </div>

      <!-- 推送方式 -->
      <div>
        <div class="mb-1 text-xs text-[hsl(var(--muted-foreground))]">推送方式</div>
        <Select v-model:value="form.channel" :options="CHANNEL_OPTIONS" class="w-full" />
      </div>

      <!-- 频率 + 时间 -->
      <div class="grid grid-cols-2 gap-3">
        <div>
          <div class="mb-1 text-xs text-[hsl(var(--muted-foreground))]">推送频率</div>
          <Select v-model:value="form.frequency" :options="FREQUENCY_OPTIONS" class="w-full" />
        </div>
        <div>
          <div class="mb-1 text-xs text-[hsl(var(--muted-foreground))]">推送时间</div>
          <TimePicker
            v-model:value="timeValue"
            format="HH:mm"
            :minute-step="5"
            class="w-full"
            @change="onTimeChange"
          />
        </div>
      </div>

      <!-- 仅保存提示 -->
      <Alert type="info" show-icon>
        <template #message>
          <span class="text-xs">
            仅保存配置，推送通道由机器人模块接入（实际发送功能开发中）。
          </span>
        </template>
      </Alert>

      <div class="flex justify-end gap-2">
        <Button @click="emit('update:open', false)">取消</Button>
        <Button type="primary" :loading="saving" @click="save">保存</Button>
      </div>
    </div>
  </Modal>
</template>
