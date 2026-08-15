<script lang="ts" setup>
import type { XhsApi } from '#/api/core/xhs';

import { computed, reactive, ref, watch } from 'vue';

import {
  Button,
  Col,
  Form,
  FormItem,
  Input,
  InputNumber,
  message,
  Modal,
  Row,
  Select,
  Switch,
  Tag,
} from 'ant-design-vue';

import { createXhsCollectTaskApi } from '#/api/core/xhs';

import {
  defaultTaskForm,
  NOTE_RANGE_OPTIONS,
  NOTE_TIME_OPTIONS,
  NOTE_TYPE_OPTIONS,
  SORT_OPTIONS,
} from './xhs-collect';

// "新建采集任务"弹窗，独立采集任务页已下线，笔记管理页直接用这个共享组件新建/
// 查看采集进度，不用单独维护一份表单。tasks 传入调用方当前拿到的任务列表，
// 只用来算"常用关键词"建议，不会被这个组件修改。

const props = defineProps<{ open: boolean; tasks: XhsApi.CollectTask[] }>();
const emit = defineEmits<{
  created: [XhsApi.CollectTask];
  'update:open': [boolean];
}>();

const taskForm = reactive(defaultTaskForm());
const submitting = ref(false);

const recentKeywords = computed(() => {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const t of props.tasks) {
    if (!t.keyword || seen.has(t.keyword)) continue;
    seen.add(t.keyword);
    result.push(t.keyword);
    if (result.length >= 8) break;
  }
  return result;
});

function isTaskFormDirty() {
  const d = defaultTaskForm();
  return (
    taskForm.keyword.trim() !== '' ||
    taskForm.require_num !== d.require_num ||
    taskForm.sort_type_choice !== d.sort_type_choice ||
    taskForm.note_type !== d.note_type ||
    taskForm.note_time !== d.note_time ||
    taskForm.note_range !== d.note_range ||
    taskForm.fetch_comments !== d.fetch_comments ||
    taskForm.download_video !== d.download_video
  );
}

// 每次打开都重置成一份新表单，不带上一次残留的内容
watch(
  () => props.open,
  (open) => {
    if (open) Object.assign(taskForm, defaultTaskForm());
  },
);

function resetTaskForm() {
  Object.assign(taskForm, defaultTaskForm());
}

function close() {
  emit('update:open', false);
}

function handleCancel() {
  if (isTaskFormDirty()) {
    Modal.confirm({
      title: '放弃当前填写的内容？',
      content: '关闭后本次未提交的采集设置将丢失。',
      okType: 'danger',
      okText: '放弃',
      cancelText: '继续填写',
      onOk: close,
    });
    return;
  }
  close();
}

const taskFormSummary = computed(() => {
  const parts: string[] = [];
  parts.push(`采集 ${taskForm.require_num} 篇`);
  const noteTime = NOTE_TIME_OPTIONS.find((o) => o.value === taskForm.note_time)?.label;
  if (noteTime && noteTime !== '不限') parts.push(`发布于${noteTime}`);
  const noteType = NOTE_TYPE_OPTIONS.find((o) => o.value === taskForm.note_type)?.label;
  if (noteType && noteType !== '不限') parts.push(noteType);
  if (taskForm.fetch_comments) parts.push('含评论');
  return parts.join(' · ');
});

async function submitTask() {
  if (!taskForm.keyword.trim()) {
    message.error('请输入关键词');
    return;
  }
  submitting.value = true;
  try {
    const created = await createXhsCollectTaskApi({ ...taskForm, keyword: taskForm.keyword.trim() });
    message.success('任务已创建，可以在下方查看进度');
    close();
    emit('created', created);
  } catch (e: any) {
    message.error(`创建失败：${e.message}`);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Modal
    :open="open"
    title="新建采集任务"
    width="720px"
    :confirm-loading="submitting"
    ok-text="创建任务"
    cancel-text="取消"
    @ok="submitTask"
    @cancel="handleCancel"
  >
    <Form layout="vertical" @submit.prevent="submitTask">
      <div class="mb-1 text-xs font-bold text-[hsl(var(--muted-foreground))]">基础信息</div>
      <FormItem label="关键词" required>
        <Input v-model:value="taskForm.keyword" placeholder="例如：普吉岛酒店推荐" />
      </FormItem>
      <FormItem v-if="recentKeywords.length" label="常用关键词">
        <div class="flex flex-wrap gap-1.5">
          <Tag
            v-for="kw in recentKeywords"
            :key="kw"
            class="cursor-pointer"
            @click="taskForm.keyword = kw"
          >
            {{ kw }}
          </Tag>
        </div>
      </FormItem>

      <div class="mt-4 mb-1 text-xs font-bold text-[hsl(var(--muted-foreground))]">采集范围</div>
      <Row :gutter="12">
        <Col :span="12">
          <FormItem label="采集数量">
            <InputNumber v-model:value="taskForm.require_num" :min="1" :max="1000" style="width: 100%" />
          </FormItem>
        </Col>
        <Col :span="12">
          <FormItem label="结果排序">
            <Select v-model:value="taskForm.sort_type_choice" :options="SORT_OPTIONS" />
          </FormItem>
        </Col>
        <Col :span="12">
          <FormItem label="内容类型">
            <Select v-model:value="taskForm.note_type" :options="NOTE_TYPE_OPTIONS" />
          </FormItem>
        </Col>
        <Col :span="12">
          <FormItem label="发布时间">
            <Select v-model:value="taskForm.note_time" :options="NOTE_TIME_OPTIONS" />
          </FormItem>
        </Col>
        <Col :span="12">
          <FormItem label="笔记范围">
            <Select v-model:value="taskForm.note_range" :options="NOTE_RANGE_OPTIONS" />
          </FormItem>
        </Col>
      </Row>

      <div class="mt-2 mb-3 rounded-lg border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-2 text-xs text-[hsl(var(--muted-foreground))]">
        点赞 / 收藏范围过滤：需要爬虫和后端支持结果内互动量过滤后才能开放，当前版本暂不提供，避免展示不生效的假筛选项。
      </div>

      <div class="mb-1 text-xs font-bold text-[hsl(var(--muted-foreground))]">评论采集</div>
      <FormItem>
        <Switch v-model:checked="taskForm.fetch_comments" /> 同时抓取评论
      </FormItem>
      <FormItem v-if="taskForm.fetch_comments" label="每篇评论上限（留空 = 不限制）">
        <InputNumber
          :value="taskForm.max_comments_per_note ?? undefined"
          :min="1"
          style="width: 100%"
          @update:value="(v) => (taskForm.max_comments_per_note = v == null ? null : Number(v))"
        />
      </FormItem>

      <div class="mt-4 mb-1 text-xs font-bold text-[hsl(var(--muted-foreground))]">素材下载</div>
      <FormItem>
        <Switch v-model:checked="taskForm.download_video" /> 下载视频
        <div class="mt-1 text-[11px] leading-relaxed text-[hsl(var(--muted-foreground))]">
          默认不下载（视频体积大，只保留播放地址）；图片素材始终会保存到本地，勾选后视频一并下载。
        </div>
      </FormItem>
    </Form>

    <template #footer>
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <Button size="small" @click="resetTaskForm">重置</Button>
          <span class="text-xs text-[hsl(var(--muted-foreground))]">{{ taskFormSummary }}</span>
        </div>
        <div class="flex items-center gap-2">
          <Button @click="handleCancel">取消</Button>
          <Button type="primary" :loading="submitting" @click="submitTask">创建任务</Button>
        </div>
      </div>
    </template>
  </Modal>
</template>
