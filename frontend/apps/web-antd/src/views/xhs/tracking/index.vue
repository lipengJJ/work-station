<script lang="ts" setup>
import type { XhsApi } from '#/api/core/xhs';

import { computed, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Alert,
  Button,
  Carousel,
  Col,
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
  Tooltip,
} from 'ant-design-vue';
import { ArrowLeft, MoreHorizontal, Plus } from 'lucide-vue-next';

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
  };
}

const editModalOpen = ref(false);
const editingId = ref<number>();
const submitting = ref(false);
const form = reactive(defaultForm());

function openCreateModal() {
  Object.assign(form, defaultForm());
  editingId.value = undefined;
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
  });
  editingId.value = task.id;
  editModalOpen.value = true;
}

async function submitForm() {
  if (!form.name.trim() || !form.keyword.trim()) {
    message.error('请填写任务名称和关键词');
    return;
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
const hitGroups = computed(() => groupNotesByRecency(hits.value));

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
          <div v-else class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] font-mono text-[11px] text-[hsl(var(--muted-foreground))] uppercase">
                <tr>
                  <th class="px-4 py-3">笔记信息</th>
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
        <div>
          <Switch v-model:checked="form.enabled" checked-children="启用" un-checked-children="停用" />
        </div>
      </div>
    </Modal>

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
