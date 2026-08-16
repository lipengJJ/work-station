<script lang="ts" setup>
import type { XhsApi } from '#/api/core/xhs';

import { computed, reactive, ref, watch } from 'vue';

import dayjs from 'dayjs';

import { Page } from '@vben/common-ui';

import {
  Alert,
  Button,
  Carousel,
  Col,
  Drawer,
  Dropdown,
  Image,
  Input,
  InputNumber,
  Menu,
  MenuItem,
  message,
  Modal,
  Row,
  Select,
  Switch,
  Tag,
  TimePicker,
  Tooltip,
} from 'ant-design-vue';
import { ArrowLeft, Bell, MoreHorizontal, Plus, Sparkles } from 'lucide-vue-next';

import {
  buildXhsMediaProxyUrl,
  createXhsTrackingTaskApi,
  deleteXhsTrackingHitApi,
  deleteXhsTrackingTaskApi,
  listXhsTrackingHitsApi,
  listXhsTrackingTasksApi,
  runXhsTrackingTaskNowApi,
  updateXhsTrackingTaskApi,
} from '#/api/core/xhs';
import { listNotifyConfigsApi } from '#/api/core/notify';
import { groupNotesByRecency } from '#/utils/note-grouping';

const SORT_OPTIONS = [
  { value: 0, label: '综合排序' },
  { value: 1, label: '最新' },
  { value: 2, label: '最多点赞' },
  { value: 3, label: '最多评论' },
  { value: 4, label: '最多收藏' },
];
const NOTE_TYPE_OPTIONS = [
  { value: 0, label: '不限' },
  { value: 1, label: '视频笔记' },
  { value: 2, label: '普通笔记' },
];
const NOTE_TIME_OPTIONS = [
  { value: 0, label: '不限' },
  { value: 1, label: '一天内' },
  { value: 2, label: '一周内' },
  { value: 3, label: '半年内' },
];
const NOTE_RANGE_OPTIONS = [
  { value: 0, label: '不限' },
  { value: 1, label: '已看过' },
  { value: 2, label: '未看过' },
  { value: 3, label: '已关注' },
];
const FREQUENCY_OPTIONS = [
  { value: 15, label: '每 15 分钟' },
  { value: 30, label: '每 30 分钟' },
  { value: 60, label: '每 1 小时' },
  { value: 180, label: '每 3 小时' },
  { value: 360, label: '每 6 小时' },
  { value: 720, label: '每 12 小时' },
  { value: 1440, label: '每天' },
];

// 后端存的是不带时区偏移的 UTC 字符串，直接按字符串截断展示，不走 new Date() 解析——
// 避免被浏览器当成本地时间再转一遍导致时间对不上。
function formatDateTime(iso: null | string) {
  if (!iso) return '';
  return iso.slice(0, 16).replace('T', ' ');
}
function frequencyLabel(minutes: number) {
  return FREQUENCY_OPTIONS.find((o) => o.value === minutes)?.label ?? `每 ${minutes} 分钟`;
}

// 状态点：已暂停(enabled=false) / 扫描中(running) / 失败(failed) / 运行中(idle 且 enabled)
function statusInfo(task: XhsApi.TrackingTask) {
  if (!task.enabled) return { label: '已暂停', dot: 'bg-slate-500', text: 'text-[hsl(var(--muted-foreground))]' };
  if (task.status === 'running') return { label: '扫描中', dot: 'bg-amber-400 animate-pulse', text: 'text-amber-300' };
  if (task.status === 'failed') return { label: '失败', dot: 'bg-rose-500', text: 'text-rose-400' };
  return { label: '运行中', dot: 'bg-emerald-400', text: 'text-emerald-400' };
}

// ------------------------------------------------------------- 任务列表 ----

const tasks = ref<XhsApi.TrackingTask[]>([]);
const tasksLoading = ref(false);

async function fetchTasks() {
  tasksLoading.value = true;
  try {
    tasks.value = await listXhsTrackingTasksApi();
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    tasksLoading.value = false;
  }
}

function defaultForm(): XhsApi.TrackingTaskParams {
  return {
    name: '',
    keyword: '',
    require_num: 50,
    sort_type_choice: 0,
    note_type: 0,
    note_time: 0,
    note_range: 0,
    must_include: [],
    must_exclude: [],
    interval_minutes: 60,
    enabled: true,
    notify_enabled: false,
    notify_channel_ids: [],
    notify_time_start: '09:00',
    notify_time_end: '22:00',
    notify_frequency: 'realtime',
    notify_only_on_hit: true,
    ai_filter_enabled: false,
    ai_filter_prompt: AI_DEFAULT_PROMPT,
    ai_filter_min_confidence: 0.6,
  };
}

// 可选通知渠道（系统设置已启用）
const notifyChannels = ref<{ id: number; label: string; channel: string }[]>([]);
const notifyChannelsLoading = ref(false);
async function loadNotifyChannels() {
  notifyChannelsLoading.value = true;
  try {
    const configs = await listNotifyConfigsApi();
    const meta: Record<string, string> = {
      wecom_webhook: '企业微信群机器人',
      serverchan: 'Server酱',
      pushplus: 'PushPlus',
    };
    notifyChannels.value = configs
      .filter((c) => c.enabled)
      .map((c) => ({
        id: c.id,
        channel: c.channel,
        remark: c.remark || '',
        label: c.remark ? `${meta[c.channel] || c.channel} · ${c.remark}` : meta[c.channel] || c.channel,
      }));
  } catch {
    notifyChannels.value = [];
  } finally {
    notifyChannelsLoading.value = false;
  }
}

const NOTIFY_FREQ_OPTIONS = [
  { value: 'realtime', label: '实时（每次执行后有新命中立即推送）' },
  { value: '1h', label: '每 1 小时汇总' },
  { value: '6h', label: '每 6 小时汇总' },
  { value: '12h', label: '每 12 小时汇总' },
  { value: 'daily', label: '每天汇总（跟随通知时段起始）' },
];
// 已选但已失效的渠道（被停用/删除）
const invalidChannels = computed(() => {
  if (!form.notify_enabled) return [];
  const validIds = new Set(notifyChannels.value.map((c) => c.id));
  return form.notify_channel_ids.filter((id) => !validIds.has(id));
});
const notifyFreqDesc = computed(() => {
  if (form.notify_frequency === 'realtime') {
    const label = FREQUENCY_OPTIONS.find((o) => o.value === form.interval_minutes)?.label;
    return `任务每执行一次就推送一次，当前执行频率为「${label || '每 ' + form.interval_minutes + ' 分钟'}」`;
  }
  return '多次执行的新命中结果合并为一条消息推送';
});
const notifyFreqWarn = computed(() => {
  if (form.notify_frequency === 'realtime') return '';
  const freqMin: Record<string, number> = { '1h': 60, '6h': 360, '12h': 720, daily: 1440 };
  const nf = freqMin[form.notify_frequency] || 0;
  return nf < form.interval_minutes ? '通知频率高于任务执行频率，实际推送间隔将以执行频率为准' : '';
});
const startDayjs = computed(() => (form.notify_time_start ? dayjs(form.notify_time_start, 'HH:mm') : undefined));
const endDayjs = computed(() => (form.notify_time_end ? dayjs(form.notify_time_end, 'HH:mm') : undefined));

// 不限时段：勾选后时间选择器置灰（start/end 置 null 表示不限）
const unlimitedTime = ref(false);
watch(
  () => unlimitedTime.value,
  (v) => {
    if (v) {
      form.notify_time_start = null;
      form.notify_time_end = null;
    } else {
      form.notify_time_start = form.notify_time_start || '09:00';
      form.notify_time_end = form.notify_time_end || '22:00';
    }
  },
);
// ==================== AI 智能筛选 ====================
const AI_DEFAULT_PROMPT = `你是一个内容筛选助手。请判断下面这条小红书笔记是否符合用户的需求。

用户需求：
在「{{keyword}}」相关的笔记中，找出真正有价值的内容。
（请在此处详细描述你的筛选标准，例如：只要本地个人出售的二手商品，
排除代购、求购、商家广告、无实质内容的引流帖）

笔记内容：
标题：{{note_title}}
正文：{{note_content}}
结构化信息：{{note_structured}}
发布时间：{{note_publish_time}}
互动数据：点赞 {{note_likes}} · 收藏 {{note_collects}} · 评论 {{note_comments}}

判断时请注意：
- 宁可漏过，不要误报
- 无法确定时判定为不符合`;

const AI_SYSTEM_APPEND = `请严格以 JSON 格式返回，不要包含任何其他内容：
{
  "is_match": true 或 false,
  "match_reason": "一句话说明判断理由，20 字以内",
  "confidence": 0 到 1 之间的小数
}`;

const AI_VARIABLES: { key: string; desc: string }[] = [
  { key: 'keyword', desc: '任务的搜索关键词' },
  { key: 'task_name', desc: '任务名称' },
  { key: 'note_title', desc: '笔记标题' },
  { key: 'note_content', desc: '笔记正文' },
  { key: 'note_structured', desc: 'AI 预处理提取的结构化字段（JSON）' },
  { key: 'note_publish_time', desc: '笔记发布时间' },
  { key: 'note_author', desc: '作者昵称' },
  { key: 'note_likes', desc: '点赞数' },
  { key: 'note_collects', desc: '收藏数' },
  { key: 'note_comments', desc: '评论数' },
  { key: 'note_url', desc: '笔记链接' },
];

const AI_CONFIDENCE_OPTIONS = [
  { value: 0, label: '不限' },
  { value: 0.6, label: '0.6 以上' },
  { value: 0.8, label: '0.8 以上' },
];

// 数据处理模型是否已配置（系统设置 zhipu）
const zhipuConfigured = ref(true);
async function checkZhipuConfig() {
  try {
    const { listApiConfigsApi } = await import('#/api/core/system');
    const configs = (await listApiConfigsApi()) as { name: string; value: string }[];
    zhipuConfigured.value = !!configs.find((c) => c.name === 'zhipu_api_key')?.value;
  } catch {
    zhipuConfigured.value = false;
  }
}

const promptTextarea = ref<HTMLTextAreaElement | null>(null);
const promptScrollTop = ref(0);
const promptScrollLeft = ref(0);

// Prompt 高亮渲染（{{变量}} 高亮）
const promptHighlighted = computed(() => {
  const text = form.ai_filter_prompt || '';
  return text.replace(/\{\{\s*(\w+)\s*\}\}/g, (m, name) => {
    const known = AI_VARIABLES.some((v) => v.key === name);
    const color = known ? '#22c55e' : '#f43f5e';
    return `<span style="color:${color};font-weight:600">${m}</span>`;
  });
});
const promptChars = computed(() => (form.ai_filter_prompt || '').length);

function promptVarText(key: string): string {
  return `{{${key}}}`;
}

function insertPromptVariable(key: string) {
  const ta = promptTextarea.value;
  if (!ta) {
    form.ai_filter_prompt = (form.ai_filter_prompt || '') + `{{${key}}}`;
    return;
  }
  const start = ta.selectionStart ?? (form.ai_filter_prompt || '').length;
  const end = ta.selectionEnd ?? start;
  const cur = form.ai_filter_prompt || '';
  form.ai_filter_prompt = cur.slice(0, start) + `{{${key}}}` + cur.slice(end);
  requestAnimationFrame(() => {
    ta.focus();
    ta.selectionStart = ta.selectionEnd = start + key.length + 4;
  });
}

function onPromptInput(e: Event) {
  const ta = e.target as HTMLTextAreaElement;
  if (ta.value.length > 4000) {
    ta.value = ta.value.slice(0, 4000);
    form.ai_filter_prompt = ta.value;
  }
  promptScrollTop.value = ta.scrollTop;
  promptScrollLeft.value = ta.scrollLeft;
}

// 试跑
const tryRunOpen = ref(false);
const tryRunLoading = ref(false);
const tryRunSummary = ref('');
const tryRunItems = ref<
  { note_id: string; title: string; ok: boolean; is_match?: boolean; match_reason?: string; confidence?: number; elapsed?: number; error?: string; raw?: string }[]
>([]);
async function runAiTry() {
  if (!form.ai_filter_prompt?.trim()) {
    message.warning('请先填写筛选 Prompt');
    return;
  }
  tryRunLoading.value = true;
  try {
    const { aiTryRunApi } = await import('#/api/core/xhs');
    const res = await aiTryRunApi(editingId.value!, { prompt: form.ai_filter_prompt });
    tryRunSummary.value = res.summary || '';
    tryRunItems.value = res.items || [];
    tryRunOpen.value = true;
  } catch (e: any) {
    message.error(`试跑失败：${e.message}`);
  } finally {
    tryRunLoading.value = false;
  }
}

function toggleChannel(id: number) {
  const idx = form.notify_channel_ids.indexOf(id);
  if (idx >= 0) {
    form.notify_channel_ids.splice(idx, 1);
  } else {
    form.notify_channel_ids.push(id);
  }
}

const editModalOpen = ref(false);
const editingId = ref<number>();
const submitting = ref(false);
const form = reactive(defaultForm());

// 通知渠道名（用于列表 hover；失效渠道标注「已失效」）
function notifyChannelNames(task: XhsApi.TrackingTask): string {
  if (!task.notify_channel_ids.length) return '';
  const names = task.notify_channel_ids.map((id) => {
    const ch = notifyChannels.value.find((c) => c.id === id);
    return ch ? ch.label : `渠道 #${id}（已失效）`;
  });
  return names.join('、');
}

function openCreateModal() {
  Object.assign(form, defaultForm());
  editingId.value = undefined;
  loadNotifyChannels();
  checkZhipuConfig();
  editModalOpen.value = true;
}

function openEditModal(task: XhsApi.TrackingTask) {
  Object.assign(form, {
    name: task.name,
    keyword: task.keyword,
    require_num: task.require_num,
    sort_type_choice: task.sort_type_choice,
    note_type: task.note_type,
    note_time: task.note_time,
    note_range: task.note_range,
    must_include: [...task.must_include],
    must_exclude: [...task.must_exclude],
    interval_minutes: task.interval_minutes,
    enabled: task.enabled,
    notify_enabled: task.notify_enabled,
    notify_channel_ids: [...task.notify_channel_ids],
    notify_time_start: task.notify_time_start,
    notify_time_end: task.notify_time_end,
    notify_frequency: task.notify_frequency,
    notify_only_on_hit: task.notify_only_on_hit,
    ai_filter_enabled: task.ai_filter_enabled,
    ai_filter_prompt: task.ai_filter_prompt || AI_DEFAULT_PROMPT,
    ai_filter_min_confidence: task.ai_filter_min_confidence ?? 0.6,
  });
  editingId.value = task.id;
  loadNotifyChannels();
  checkZhipuConfig();
  editModalOpen.value = true;
}

async function submitForm() {
  if (!form.name.trim() || !form.keyword.trim()) {
    message.error('请填写任务名称和关键词');
    return;
  }
  if (form.notify_enabled && form.notify_channel_ids.length === 0) {
    message.error('请至少选择一个通知渠道');
    return;
  }
  if (form.ai_filter_enabled && !form.ai_filter_prompt?.trim()) {
    message.error('请填写筛选 Prompt');
    return;
  }
  if (
    form.ai_filter_enabled &&
    !/\{\{\s*note_\w+\s*\}\}/.test(form.ai_filter_prompt || '')
  ) {
    const ok = await new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: 'Prompt 未引用笔记内容',
        content: 'Prompt 中未引用笔记内容，模型将无法判断具体笔记，确定保存吗？',
        okText: '确定保存',
        cancelText: '取消',
        onOk: () => resolve(true),
        onCancel: () => resolve(false),
      });
    });
    if (!ok) return;
  }
  submitting.value = true;
  try {
    if (editingId.value) {
      await updateXhsTrackingTaskApi(editingId.value, form);
    } else {
      await createXhsTrackingTaskApi(form);
    }
    editModalOpen.value = false;
    message.success('已保存');
    fetchTasks();
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    submitting.value = false;
  }
}

async function toggleEnabled(task: XhsApi.TrackingTask, enabled: boolean) {
  try {
    const updated = await updateXhsTrackingTaskApi(task.id, {
      name: task.name,
      keyword: task.keyword,
      require_num: task.require_num,
      sort_type_choice: task.sort_type_choice,
      note_type: task.note_type,
      note_time: task.note_time,
      note_range: task.note_range,
      must_include: task.must_include,
      must_exclude: task.must_exclude,
      interval_minutes: task.interval_minutes,
      enabled,
      notify_enabled: task.notify_enabled,
      notify_channel_ids: task.notify_channel_ids,
      notify_time_start: task.notify_time_start,
      notify_time_end: task.notify_time_end,
      notify_frequency: task.notify_frequency,
      notify_only_on_hit: task.notify_only_on_hit,
      ai_filter_enabled: task.ai_filter_enabled,
      ai_filter_prompt: task.ai_filter_prompt,
      ai_filter_min_confidence: task.ai_filter_min_confidence,
    });
    task.enabled = updated.enabled;
    task.next_run_at = updated.next_run_at;
  } catch (e: any) {
    message.error(`操作失败：${e.message}`);
  }
}

function runNow(task: XhsApi.TrackingTask) {
  runXhsTrackingTaskNowApi(task.id)
    .then(() => {
      message.success('已提交一次扫描，稍后刷新查看结果');
    })
    .catch((e: any) => {
      message.error(`触发失败：${e.message}`);
    });
}

function removeTask(task: XhsApi.TrackingTask) {
  Modal.confirm({
    title: `确定删除追踪任务「${task.name}」吗？`,
    content: '定时扫描会停止，已经命中的笔记记录也会一并删除，此操作不可恢复。',
    okType: 'danger',
    onOk: async () => {
      try {
        await deleteXhsTrackingTaskApi(task.id);
        tasks.value = tasks.value.filter((t) => t.id !== task.id);
        if (selectedTask.value?.id === task.id) {
          selectedTask.value = undefined;
          hits.value = [];
        }
        message.success('已删除');
      } catch (e: any) {
        message.error(`删除失败：${e.message}`);
      }
    },
  });
}

// ------------------------------------------------------------- 命中列表 ----

const selectedTask = ref<XhsApi.TrackingTask>();
const hits = ref<XhsApi.TrackingHit[]>([]);
const hitsLoading = ref(false);
const aiOnlyFilter = ref(false);
const hitGroups = computed(() => {
  const base = aiOnlyFilter.value ? hits.value.filter((h) => h.ai_is_match === true) : hits.value;
  return groupNotesByRecency(base);
});
function aiMatchedCount(): number {
  return hits.value.filter((h) => h.ai_is_match === true).length;
}

async function fetchHits(taskId: number) {
  hitsLoading.value = true;
  try {
    hits.value = await listXhsTrackingHitsApi(taskId);
  } catch (e: any) {
    message.error(`加载命中笔记失败：${e.message}`);
  } finally {
    hitsLoading.value = false;
  }
}

function openTask(task: XhsApi.TrackingTask) {
  selectedTask.value = task;
  hits.value = [];
  fetchHits(task.id);
}

function backToList() {
  selectedTask.value = undefined;
  hits.value = [];
}

function coverOf(note: XhsApi.Note) {
  return note.video_cover || note.image_list[0] || '';
}
function coverProxied(note: XhsApi.Note) {
  const url = coverOf(note);
  if (!url) return '';
  return buildXhsMediaProxyUrl(url, {
    noteId: note.note_id,
    kind: note.video_cover ? 'cover' : 'image',
    index: note.video_cover ? undefined : 0,
  });
}
function galleryProxied(note: XhsApi.Note, index: number) {
  return buildXhsMediaProxyUrl(note.image_list[index] ?? '', { noteId: note.note_id, kind: 'image', index });
}
function videoProxied(note: XhsApi.Note) {
  if (!note.video_addr) return '';
  return buildXhsMediaProxyUrl(note.video_addr, { noteId: note.note_id, kind: 'video' });
}
function openInXhs(url: string) {
  window.open(url, '_blank', 'noopener,noreferrer');
}

const detailModalOpen = ref(false);
const detailNote = ref<XhsApi.TrackingHit>();

function openDetail(note: XhsApi.TrackingHit) {
  detailNote.value = note;
  detailModalOpen.value = true;
}

function ignoreHit(hit: XhsApi.TrackingHit) {
  const taskId = selectedTask.value?.id;
  if (!taskId) return;
  Modal.confirm({
    title: `确定忽略《${hit.title || '无标题'}》这条命中记录吗？`,
    content: '只是从命中列表里移除，不影响小红书上的原内容。',
    okType: 'danger',
    onOk: async () => {
      try {
        await deleteXhsTrackingHitApi(taskId, hit._hit_id);
        hits.value = hits.value.filter((h) => h._hit_id !== hit._hit_id);
        detailModalOpen.value = false;
        message.success('已忽略');
      } catch (e: any) {
        message.error(`操作失败：${e.message}`);
      }
    },
  });
}

fetchTasks();
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-[hsl(var(--background-deep))] p-6 select-none">
      <!-- ============================================== 追踪任务列表 -->
      <template v-if="!selectedTask">
        <div class="mb-6 shrink-0 flex items-center justify-between">
          <div>
            <h1 class="text-xl font-extrabold text-[hsl(var(--foreground))]">追踪任务</h1>
            <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">按关键词周期性搜索，命中符合条件的新笔记会自动记录下来</p>
          </div>
          <button class="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500" @click="openCreateModal">
            <Plus class="h-3.5 w-3.5" />
            新建追踪任务
          </button>
        </div>

        <div class="shrink-0 overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] shadow-xl">
          <div v-if="!tasksLoading && tasks.length === 0" class="flex flex-col items-center justify-center gap-2 p-12 text-center">
            <p class="text-sm font-semibold text-[hsl(var(--foreground))]">还没有追踪任务</p>
            <p class="text-xs text-[hsl(var(--muted-foreground))]">新建一个吧，比如「新加坡二手显示器」</p>
          </div>
          <div v-else class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] font-mono text-[11px] text-[hsl(var(--muted-foreground))] uppercase">
                <tr>
                  <th class="px-4 py-3">主题 / 关键词 / 状态</th>
                  <th class="px-4 py-3">本次新增</th>
                  <th class="px-4 py-3">AI 命中</th>
                  <th class="px-4 py-3">累计命中</th>
                  <th class="px-4 py-3">下次检查 / 频率</th>
                  <th class="px-4 py-3">启停</th>
                  <th class="px-4 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-[hsl(var(--border))]">
                <tr v-for="task in tasks" :key="task.id" class="transition-colors hover:bg-[hsl(var(--accent))]">
                  <td class="cursor-pointer px-4 py-3" @click="openTask(task)">
                    <div class="font-semibold text-[hsl(var(--foreground))]">{{ task.name }}</div>
                    <div v-if="task.notify_enabled && task.notify_channel_ids.length" class="mt-0.5 flex items-center gap-1 text-xs text-[hsl(var(--muted-foreground))]">
                      <Tooltip :title="notifyChannelNames(task)">
                        <span class="inline-flex items-center gap-0.5">
                          <Bell class="size-3" />
                          {{ task.notify_channel_ids.length }} 个渠道
                        </span>
                      </Tooltip>
                    </div>
                    <div v-if="task.ai_filter_enabled" class="mt-0.5 flex items-center gap-1 text-xs">
                      <Tooltip title="已开启 AI 智能筛选">
                        <span class="inline-flex items-center gap-0.5 text-[#a78bfa]">
                          <Sparkles class="size-3" />
                          AI 筛选
                        </span>
                      </Tooltip>
                    </div>
                    <div class="mt-0.5 flex items-center gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
                      <span>{{ task.keyword }}</span>
                    </div>
                    <div class="mt-1 flex items-center gap-1.5">
                      <span class="h-1.5 w-1.5 rounded-full" :class="statusInfo(task).dot"></span>
                      <span class="font-semibold" :class="statusInfo(task).text">{{ statusInfo(task).label }}</span>
                      <span v-if="task.status === 'failed' && task.last_run_message" class="truncate text-[11px] text-rose-400/80">
                        · {{ task.last_run_message }}
                      </span>
                    </div>
                  </td>
                  <td class="px-4 py-3 font-mono text-[hsl(var(--foreground))]">{{ task.last_hit_count }}</td>
                  <td class="px-4 py-3 font-mono" :class="task.ai_filter_enabled ? 'text-[#a78bfa]' : 'text-[hsl(var(--muted-foreground))]'">{{ task.ai_filter_enabled ? (task.last_ai_match_count ?? '—') : '—' }}</td>
                  <td class="px-4 py-3 font-mono text-[hsl(var(--foreground))]">{{ task.total_hit_count }}</td>
                  <td class="px-4 py-3 text-[hsl(var(--muted-foreground))]">
                    <template v-if="task.next_run_at">
                      {{ formatDateTime(task.next_run_at) }}
                    </template>
                    <template v-else-if="task.enabled">
                      <Tooltip title="调度器暂未返回下次执行时间">—</Tooltip>
                    </template>
                    <template v-else>—</template>
                    <div class="text-[11px] text-[hsl(var(--muted-foreground))]">{{ frequencyLabel(task.interval_minutes) }}</div>
                  </td>
                  <td class="px-4 py-3">
                    <Switch
                      size="small"
                      :checked="task.enabled"
                      checked-children="启用"
                      un-checked-children="停用"
                      @change="(v) => toggleEnabled(task, v as boolean)"
                    />
                  </td>
                  <td class="px-4 py-3 text-right">
                    <div class="flex items-center justify-end gap-2">
                      <button
                        class="rounded-lg border border-indigo-500/30 bg-indigo-600/10 px-2 py-1 text-[11px] font-semibold text-indigo-300 hover:bg-indigo-600/20 disabled:cursor-not-allowed disabled:opacity-40"
                        :disabled="task.status === 'running'"
                        @click="runNow(task)"
                      >
                        {{ task.status === 'running' ? '扫描中…' : task.status === 'failed' ? '重试' : '立即运行' }}
                      </button>
                      <Dropdown :trigger="['click']">
                        <button class="rounded-lg p-1.5 text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]" aria-label="更多操作">
                          <MoreHorizontal class="h-4 w-4" />
                        </button>
                        <template #overlay>
                          <Menu>
                            <MenuItem key="hits" @click="openTask(task)">查看命中笔记</MenuItem>
                            <MenuItem key="edit" @click="openEditModal(task)">编辑</MenuItem>
                            <MenuItem key="delete" danger @click="removeTask(task)">删除</MenuItem>
                          </Menu>
                        </template>
                      </Dropdown>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>

      <!-- ============================================== 命中笔记 -->
      <template v-else>
        <div class="mb-4 shrink-0 flex flex-wrap items-center gap-3">
          <button class="flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]" @click="backToList">
            <ArrowLeft class="h-3.5 w-3.5" />
            返回列表
          </button>
          <div class="text-xs text-[hsl(var(--muted-foreground))]">
            追踪任务 / <span class="text-[hsl(var(--foreground))]">{{ selectedTask.name }}</span>
          </div>
          <Tag color="blue">{{ selectedTask.keyword }}</Tag>
          <Tag>{{ hits.length }} 篇命中</Tag>
        </div>

        <div class="shrink-0 overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] shadow-xl">
          <div v-if="!hitsLoading && hits.length === 0" class="flex flex-col items-center justify-center gap-2 p-12 text-center">
            <p class="text-sm font-semibold text-[hsl(var(--foreground))]">还没有命中的笔记</p>
            <p class="text-xs text-[hsl(var(--muted-foreground))]">等下一次扫描，或者返回列表点「立即运行」试试</p>
          </div>
          <div v-else-if="selectedTask.ai_filter_enabled" class="mb-3 flex items-center gap-3">
            <label style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: hsl(var(--muted-foreground)); cursor: pointer">
              <input type="checkbox" v-model="aiOnlyFilter" style="accent-color: hsl(var(--primary))" />
              仅看 AI 命中
            </label>
            <span class="text-[11px] text-[hsl(var(--muted-foreground))]">
              {{ aiMatchedCount() }} 条 AI 命中
            </span>
          </div>
          <div v-else class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] font-mono text-[11px] text-[hsl(var(--muted-foreground))] uppercase">
                <tr>
                  <th class="px-4 py-3">笔记信息</th>
                  <th class="px-4 py-3">AI 判定</th>
                  <th class="px-4 py-3">发布时间</th>
                  <th class="px-4 py-3">点赞</th>
                  <th class="px-4 py-3">评论</th>
                  <th class="px-4 py-3 text-right">操作</th>
                </tr>
              </thead>
              <template v-for="group in hitGroups" :key="group.label">
                <tbody class="divide-y divide-[hsl(var(--border))]">
                  <tr>
                    <td colspan="5" class="bg-[hsl(var(--card))] px-4 py-2 text-[11px] font-bold text-[hsl(var(--muted-foreground))]">{{ group.label }}</td>
                  </tr>
                  <tr v-for="note in group.notes" :key="note.note_id" class="cursor-pointer transition-colors hover:bg-[hsl(var(--accent))]" @click="openDetail(note)">
                    <td class="px-4 py-3">
                      <div class="flex items-center gap-2.5">
                        <div class="h-10 w-10 shrink-0 overflow-hidden rounded-lg bg-[hsl(var(--muted))]">
                          <Image
                            :src="coverProxied(note)"
                            :preview="false"
                            width="40px"
                            height="40px"
                            style="object-fit: cover; display: block"
                            fallback="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxIiBoZWlnaHQ9IjEiLz4="
                          />
                        </div>
                        <div class="min-w-0">
                          <div class="truncate font-semibold text-[hsl(var(--foreground))]">{{ note.title || '无标题' }}</div>
                          <div class="text-[11px] text-[hsl(var(--muted-foreground))]">{{ note.nickname }}</div>
                        </div>
                      </div>
                    </td>
                    <td class="px-4 py-3">
                      <span v-if="note.ai_is_match === true" class="inline-flex items-center gap-1 text-[#22c55e]">
                        <Sparkles class="size-3" />
                        {{ note.ai_confidence ? '命中 ' + note.ai_confidence : '命中' }}
                      </span>
                      <span v-else-if="note.ai_is_match === false" class="text-[hsl(var(--muted-foreground))]">不符合</span>
                      <span v-else-if="note.ai_process_status === 'failed'" class="text-[#eab308]">AI 失败</span>
                      <span v-else class="text-[hsl(var(--muted-foreground))]">—</span>
                      <div v-if="note.ai_match_reason" class="text-[10px] text-[hsl(var(--muted-foreground))]" :title="note.ai_match_reason">{{ note.ai_match_reason }}</div>
                    </td>
                    <td class="px-4 py-3 text-[hsl(var(--muted-foreground))]">{{ note.upload_time }}</td>
                    <td class="px-4 py-3 font-mono text-[hsl(var(--muted-foreground))]">{{ note.liked_count }}</td>
                    <td class="px-4 py-3 font-mono text-[hsl(var(--muted-foreground))]">{{ note.comment_count }}</td>
                    <td class="px-4 py-3 text-right" @click.stop>
                      <button class="text-[11px] text-[hsl(var(--muted-foreground))] hover:text-rose-400" @click="ignoreHit(note)">忽略</button>
                    </td>
                  </tr>
                </tbody>
              </template>
            </table>
          </div>
        </div>
      </template>
    </div>

    <!-- 新建/编辑追踪任务 -->
    <Modal
      v-model:open="editModalOpen"
      :title="editingId ? '编辑追踪任务' : '新建追踪任务'"
      width="640px"
      :confirm-loading="submitting"
      ok-text="保存"
      @ok="submitForm"
    >
      <Alert
        type="info"
        show-icon
        message="过滤条件：标题+正文必须包含下面全部关键词，且不能出现排除关键词里的任意一个（不区分大小写）"
        style="margin-bottom: 12px"
      />
      <div style="display: flex; flex-direction: column; gap: 12px">
        <div>
          <div style="margin-bottom: 4px">任务名称</div>
          <Input v-model:value="form.name" placeholder="比如：新加坡二手显示器" />
        </div>
        <div>
          <div style="margin-bottom: 4px">搜索关键词</div>
          <Input v-model:value="form.keyword" placeholder="比如：新加坡 二手 显示器" />
        </div>
        <Row :gutter="12">
          <Col :span="12">
            <div style="margin-bottom: 4px">每次搜索数量</div>
            <InputNumber v-model:value="form.require_num" :min="1" :max="200" style="width: 100%" />
          </Col>
          <Col :span="12">
            <div style="margin-bottom: 4px">执行频率</div>
            <Select v-model:value="form.interval_minutes" :options="FREQUENCY_OPTIONS" style="width: 100%" />
          </Col>
        </Row>
        <Row :gutter="12">
          <Col :span="8">
            <div style="margin-bottom: 4px">排序方式</div>
            <Select v-model:value="form.sort_type_choice" :options="SORT_OPTIONS" style="width: 100%" />
          </Col>
          <Col :span="8">
            <div style="margin-bottom: 4px">笔记类型</div>
            <Select v-model:value="form.note_type" :options="NOTE_TYPE_OPTIONS" style="width: 100%" />
          </Col>
          <Col :span="8">
            <div style="margin-bottom: 4px">发布时间</div>
            <Select v-model:value="form.note_time" :options="NOTE_TIME_OPTIONS" style="width: 100%" />
          </Col>
        </Row>
        <div>
          <div style="margin-bottom: 4px">笔记范围</div>
          <Select v-model:value="form.note_range" :options="NOTE_RANGE_OPTIONS" style="width: 100%" />
        </div>
        <div>
          <div style="margin-bottom: 4px">必须包含关键词（回车添加）</div>
          <Select v-model:value="form.must_include" mode="tags" style="width: 100%" placeholder="比如：显示器" />
        </div>
        <div>
          <div style="margin-bottom: 4px">必须排除关键词（回车添加）</div>
          <Select
            v-model:value="form.must_exclude"
            mode="tags"
            style="width: 100%"
            placeholder="比如：求购、已出"
          />
        </div>

        <!-- ==================== AI 智能筛选 ==================== -->
        <div class="rounded-lg border" style="padding: 12px 14px; border-color: hsl(var(--border)); background: hsl(var(--muted) / 0.3)">
          <div style="display: flex; align-items: center; justify-content: space-between">
            <span style="font-size: 13px; font-weight: 600; color: hsl(var(--foreground))">AI 智能筛选</span>
            <Tooltip v-if="!zhipuConfigured" title="需先在系统设置中配置数据处理模型">
              <span style="display: inline-flex; align-items: center">
                <Switch v-model:checked="form.ai_filter_enabled" :disabled="true" checked-children="开" un-checked-children="关" />
              </span>
            </Tooltip>
            <Switch
              v-else
              v-model:checked="form.ai_filter_enabled"
              checked-children="开"
              un-checked-children="关"
            />
          </div>

          <template v-if="form.ai_filter_enabled">
            <div v-if="!zhipuConfigured" style="margin-top: 10px; display: flex; flex-direction: column; gap: 6px">
              <span style="font-size: 12px; color: #f43f5e">需先在系统设置中配置数据处理模型</span>
              <a href="/system/settings" target="_blank" style="font-size: 12px; color: hsl(var(--primary))">前往配置 →</a>
            </div>
            <template v-else>
              <!-- 筛选 Prompt -->
              <div style="margin-top: 12px">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px">
                  <span style="font-size: 12px; color: hsl(var(--muted-foreground))">筛选 Prompt</span>
                  <span style="display: flex; gap: 8px">
                    <a
                      style="font-size: 12px; color: hsl(var(--primary)); cursor: pointer"
                      @click="form.ai_filter_prompt = AI_DEFAULT_PROMPT"
                    >恢复默认</a>
                    <Dropdown>
                      <a style="font-size: 12px; color: hsl(var(--primary)); cursor: pointer">插入变量 ▾</a>
                      <template #overlay>
                        <div class="rounded-lg border border-slate-700/50 bg-slate-900/90 p-1 shadow-xl" style="max-height: 300px; overflow-y: auto">
                          <div
                            v-for="v in AI_VARIABLES"
                            :key="v.key"
                            class="cursor-pointer px-3 py-1.5 text-xs hover:bg-slate-700/40"
                            style="color: hsl(var(--foreground))"
                            @click="insertPromptVariable(v.key)"
                          >
                            <code class="text-[#22c55e]">{{ promptVarText(v.key) }}</code>
                            <span class="ml-2 text-[hsl(var(--muted-foreground))]">{{ v.desc }}</span>
                          </div>
                        </div>
                      </template>
                    </Dropdown>
                  </span>
                </div>
                <!-- 高亮文本域（overlay 技术：背景 pre 渲染高亮，textarea 透明文字） -->
                <div style="position: relative; border: 1px solid hsl(var(--border)); border-radius: 8px; overflow: hidden">
                  <pre
                    aria-hidden="true"
                    class="ai-prompt-pre"
                    :style="{
                      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                      fontSize: '13px',
                      lineHeight: '1.5',
                      padding: '8px 10px',
                      margin: 0,
                      minHeight: '190px',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      color: 'transparent',
                      transform: `translate(${-promptScrollLeft}px, ${-promptScrollTop}px)`,
                    }"
                  ><span v-html="promptHighlighted" /></pre>
                  <textarea
                    ref="promptTextarea"
                    v-model="form.ai_filter_prompt"
                    rows="10"
                    :maxlength="4000"
                    style="position: absolute; inset: 0; width: 100%; height: 100%; resize: vertical; background: transparent; color: transparent; caret-color: hsl(var(--foreground)); font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; line-height: 1.5; padding: 8px 10px; border: none; outline: none; white-space: pre-wrap; overflow: auto"
                    @input="onPromptInput"
                    @scroll="onPromptInput"
                    :placeholder="'描述你的筛选标准，可用 {{ 插入变量…'"
                  />
                </div>
                <div style="margin-top: 4px; font-size: 11px; color: hsl(var(--muted-foreground)); text-align: right">
                  {{ promptChars }}/4000
                </div>
              </div>

              <!-- 系统追加格式（只读折叠） -->
              <div style="margin-top: 8px; font-size: 12px; color: hsl(var(--muted-foreground))">
                ⓘ 系统会自动追加输出格式要求，你无需在 Prompt 中描述返回格式
              </div>
              <details style="margin-top: 6px; font-size: 12px">
                <summary style="cursor: pointer; color: hsl(var(--muted-foreground))">▸ 系统追加的输出格式（不可编辑）</summary>
                <pre
                  class="ai-prompt-pre"
                  style="margin-top: 6px; padding: 8px 10px; border-radius: 8px; background: hsl(var(--muted) / 0.4); border: 1px solid hsl(var(--border)); font-size: 12px; line-height: 1.5; color: hsl(var(--muted-foreground)); white-space: pre-wrap"
                >{{ AI_SYSTEM_APPEND }}</pre>
              </details>

              <!-- 最低置信度 -->
              <div style="margin-top: 12px; display: flex; align-items: center; justify-content: space-between">
                <span style="font-size: 12px; color: hsl(var(--muted-foreground))">最低置信度</span>
                <Select
                  v-model:value="form.ai_filter_min_confidence"
                  :options="AI_CONFIDENCE_OPTIONS"
                  style="width: 140px"
                />
              </div>

              <!-- 试跑 -->
              <div style="margin-top: 12px">
                <Button size="small" :loading="tryRunLoading" :disabled="!form.ai_filter_prompt?.trim()" @click="runAiTry">
                  🧪 用最近采集的数据试跑
                </Button>
              </div>
            </template>
          </template>
        </div>

        <!-- ==================== 机器人通知 ==================== -->
        <div
          class="rounded-lg border"
          style="padding: 12px 14px; border-color: hsl(var(--border)); background: hsl(var(--muted) / 0.3)"
        >
          <div style="display: flex; align-items: center; justify-content: space-between">
            <span style="font-size: 13px; font-weight: 600; color: hsl(var(--foreground))">机器人通知</span>
            <Switch
              v-model:checked="form.notify_enabled"
              checked-children="开"
              un-checked-children="关"
            />
          </div>

          <template v-if="form.notify_enabled">
            <!-- 通知渠道（多选） -->
            <div style="margin-top: 12px">
              <div style="margin-bottom: 4px; font-size: 12px; color: hsl(var(--muted-foreground))">通知渠道</div>
              <div v-if="notifyChannelsLoading" style="font-size: 12px; color: hsl(var(--muted-foreground))">加载中…</div>
              <template v-else-if="notifyChannels.length">
                <div
                  v-for="ch in notifyChannels"
                  :key="ch.id"
                  style="display: flex; align-items: center; gap: 8px; padding: 4px 0; cursor: pointer"
                  @click="toggleChannel(ch.id)"
                >
                  <input
                    type="checkbox"
                    :checked="form.notify_channel_ids.includes(ch.id)"
                    style="accent-color: hsl(var(--primary))"
                  />
                  <span style="font-size: 13px; color: hsl(var(--foreground))">{{ ch.label }}</span>
                </div>
              </template>
              <div v-else style="display: flex; flex-direction: column; gap: 6px">
                <span style="font-size: 12px; color: hsl(var(--muted-foreground))">还没有可用的通知渠道</span>
                <a
                  href="/system/settings"
                  target="_blank"
                  style="font-size: 12px; color: hsl(var(--primary))"
                >前往系统设置添加 →</a>
              </div>
              <!-- 已失效渠道：灰色删除线标注 -->
              <div
                v-for="id in invalidChannels"
                :key="'inv-' + id"
                style="display: flex; align-items: center; gap: 8px; padding: 4px 0"
              >
                <input type="checkbox" :checked="true" disabled style="accent-color: hsl(var(--muted-foreground))" />
                <span
                  style="font-size: 13px; color: hsl(var(--muted-foreground)); text-decoration: line-through; text-decoration-color: hsl(var(--muted-foreground));"
                >渠道 #{{ id }} · 渠道已失效</span>
              </div>
              <div
                v-if="form.notify_channel_ids.length === 0 && !notifyChannelsLoading"
                style="margin-top: 6px; font-size: 12px; color: #f43f5e"
              >请至少选择一个通知渠道</div>
            </div>

            <!-- 通知时段 -->
            <div style="margin-top: 12px">
              <div style="margin-bottom: 4px; font-size: 12px; color: hsl(var(--muted-foreground))">通知时段</div>
              <div style="display: flex; align-items: center; gap: 8px">
                <TimePicker
                  :value="startDayjs"
                  format="HH:mm"
                  style="width: 100px"
                  :disabled="unlimitedTime"
                  @change="(t: any) => (form.notify_time_start = t ? t.format('HH:mm') : null)"
                />
                <span style="color: hsl(var(--muted-foreground))">至</span>
                <TimePicker
                  :value="endDayjs"
                  format="HH:mm"
                  style="width: 100px"
                  :disabled="unlimitedTime"
                  @change="(t: any) => (form.notify_time_end = t ? t.format('HH:mm') : null)"
                />
                <label style="display: flex; align-items: center; gap: 4px; font-size: 12px; color: hsl(var(--muted-foreground)); cursor: pointer">
                  <input type="checkbox" v-model="unlimitedTime" style="accent-color: hsl(var(--primary))" />
                  不限时段
                </label>
              </div>
            </div>

            <!-- 通知频率 -->
            <div style="margin-top: 12px">
              <div style="margin-bottom: 4px; font-size: 12px; color: hsl(var(--muted-foreground))">通知频率</div>
              <Select v-model:value="form.notify_frequency" :options="NOTIFY_FREQ_OPTIONS" style="width: 100%" />
              <div v-if="notifyFreqWarn" style="margin-top: 4px; font-size: 12px; color: #eab308">
                {{ notifyFreqWarn }}
              </div>
              <div v-else style="margin-top: 4px; font-size: 12px; color: hsl(var(--muted-foreground))">
                {{ notifyFreqDesc }}
              </div>
            </div>

            <!-- 仅在有新命中时通知 -->
            <div style="margin-top: 12px; display: flex; align-items: center; justify-content: space-between">
              <span style="font-size: 12px; color: hsl(var(--muted-foreground))">仅在有新命中时通知</span>
              <Switch v-model:checked="form.notify_only_on_hit" size="small" />
            </div>
          </template>
        </div>

        <div>
          <Switch v-model:checked="form.enabled" checked-children="启用" un-checked-children="停用" />
        </div>
      </div>
    </Modal>

    <!-- ==================== AI 试跑结果抽屉 ==================== -->
    <Drawer v-model:open="tryRunOpen" title="AI 筛选试跑结果" width="560px">
      <div v-if="tryRunSummary" style="margin-bottom: 12px; padding: 10px 12px; border-radius: 8px; background: hsl(var(--muted) / 0.3); border: 1px solid hsl(var(--border)); font-size: 13px; font-weight: 600; color: hsl(var(--foreground))">
        {{ tryRunSummary }}
      </div>
      <div v-if="!tryRunItems.length" style="padding: 24px 0; text-align: center; font-size: 13px; color: hsl(var(--muted-foreground))">
        {{ tryRunSummary === '该任务还没有采集数据，请先运行一次' ? '该任务还没有采集数据，请先运行一次' : '暂无试跑结果' }}
      </div>
      <div v-for="(item, idx) in tryRunItems" :key="item.note_id" style="padding: 12px; margin-bottom: 10px; border-radius: 8px; border: 1px solid hsl(var(--border)); background: hsl(var(--card))">
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px">
          <span style="font-size: 13px; font-weight: 600; color: hsl(var(--foreground)); overflow: hidden; text-overflow: ellipsis; white-space: nowrap">{{ idx + 1 }}. {{ item.title }}</span>
          <span
            v-if="item.ok"
            style="flex-shrink: 0; font-size: 12px; font-weight: 600"
            :style="{ color: item.is_match ? '#22c55e' : '#f43f5e' }"
          >{{ item.is_match ? '✓ 符合' : '✗ 不符合' }}</span>
          <span v-else style="flex-shrink: 0; font-size: 12px; color: #eab308">解析失败</span>
        </div>
        <template v-if="item.ok">
          <div style="margin-top: 6px; font-size: 12px; color: hsl(var(--muted-foreground))">
            置信度：{{ item.confidence }} · 耗时 {{ item.elapsed }}s
          </div>
          <div v-if="item.match_reason" style="margin-top: 4px; font-size: 12px; color: hsl(var(--muted-foreground))">
            命中理由：{{ item.match_reason }}
          </div>
        </template>
        <div v-else-if="item.error" style="margin-top: 6px; font-size: 12px; color: #eab308">
          {{ item.error }}
        </div>
        <div v-if="item.raw" style="margin-top: 6px">
          <pre style="font-size: 11px; color: hsl(var(--muted-foreground)); white-space: pre-wrap; word-break: break-all; margin: 0">{{ item.raw }}</pre>
        </div>
      </div>
    </Drawer>

    <!-- 命中笔记详情 -->
    <Modal
      v-model:open="detailModalOpen"
      :title="detailNote?.title || '无标题'"
      :footer="null"
      width="720px"
    >
      <template v-if="detailNote">
        <Carousel v-if="detailNote.image_list.length" arrows>
          <div v-for="(_img, idx) in detailNote.image_list" :key="idx">
            <img :src="galleryProxied(detailNote, idx)" style="width: 100%; max-height: 420px; object-fit: contain" />
          </div>
        </Carousel>
        <video
          v-else-if="detailNote.video_addr"
          :src="videoProxied(detailNote)"
          controls
          style="width: 100%; max-height: 420px; background: #000"
        ></video>

        <p style="margin-top: 12px; white-space: pre-wrap">{{ detailNote.desc }}</p>
        <div style="margin-bottom: 8px">
          <Tag v-for="tag in detailNote.tags" :key="tag">#{{ tag }}</Tag>
        </div>
        <p style="margin-bottom: 12px; font-size: 12px; color: #8290a5">
          {{ detailNote.nickname }} · {{ detailNote.upload_time }} · {{ detailNote.ip_location }}
        </p>
        <div style="display: flex; gap: 8px">
          <Button v-if="detailNote.note_url" type="primary" ghost @click="openInXhs(detailNote.note_url)">
            在小红书查看原文
          </Button>
          <Button danger @click="ignoreHit(detailNote)">忽略这条命中</Button>
        </div>
      </template>
    </Modal>
  </Page>
</template>
