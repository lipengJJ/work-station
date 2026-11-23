<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { reactive, ref, watch } from 'vue';

import { Form, FormItem, Input, InputNumber, message, Modal } from 'ant-design-vue';

import { createHotlistSourceApi } from '#/api/core/hotlist';

const open = defineModel<boolean>('open', { default: false });

const emit = defineEmits<{ changed: [source: HotlistApi.Source] }>();

const form = reactive({
  id: '',
  name: '',
  url: '',
  expected_domain: '',
  interval_hours: 0.5,
});
const saving = ref(false);

function resetForm() {
  form.id = '';
  form.name = '';
  form.url = '';
  form.expected_domain = '';
  form.interval_hours = 0.5;
}

// 弹窗每次重新打开都是「新建」场景，进来前把上一次的残留清空
watch(open, (v) => {
  if (v) resetForm();
});

async function submit() {
  if (!form.id.trim() || !form.name.trim() || !form.url.trim()) {
    message.warning('请填写完整');
    return;
  }
  saving.value = true;
  try {
    const created = await createHotlistSourceApi({
      id: form.id.trim(),
      name: form.name.trim(),
      adapter: 'rss',
      adapter_params: { url: form.url.trim() },
      expected_domain: form.expected_domain.trim(),
      interval_hours: form.interval_hours || 0.5,
    });
    message.success('已创建');
    open.value = false;
    emit('changed', created);
  } catch (e: any) {
    message.error(`创建失败：${e.response?.data?.detail || e.message}`);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Modal v-model:open="open" title="新建 RSS 源" :footer="null" width="440px">
    <Form layout="vertical">
      <FormItem label="源 id（唯一，英文/数字/短横线）">
        <Input v-model:value="form.id" placeholder="例如 my-blog" />
      </FormItem>
      <FormItem label="显示名">
        <Input v-model:value="form.name" placeholder="源显示名" />
      </FormItem>
      <FormItem label="Feed 地址">
        <Input v-model:value="form.url" placeholder="https://example.com/feed.xml" />
      </FormItem>
      <FormItem label="期望域名（可选，留空跳过域名安全校验）">
        <Input v-model:value="form.expected_domain" placeholder="例如 example.com" />
      </FormItem>
      <FormItem label="抓取间隔（小时）">
        <InputNumber v-model:value="form.interval_hours" :min="0.1" :step="0.5" style="width: 100%" />
      </FormItem>
      <div class="flex justify-end gap-2">
        <button class="rounded-full border border-border px-4 py-1.5 text-xs" @click="open = false">取消</button>
        <button
          :disabled="saving"
          class="rounded-full bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
          @click="submit"
        >
          创建
        </button>
      </div>
    </Form>
  </Modal>
</template>
