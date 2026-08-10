<script lang="ts" setup>
import type { XhsApi } from '#/api/core/xhs';

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';

import {
  Carousel,
  Checkbox,
  Dropdown,
  Empty,
  Image,
  Menu,
  MenuItem,
  message,
  Modal,
  Radio,
  RadioGroup,
  Spin,
  Tag,
  Tooltip,
} from 'ant-design-vue';
import {
  ArrowLeft,
  ChevronRight,
  Download,
  Plus,
  Search,
  Tags as TagsIcon,
} from 'lucide-vue-next';

import {
  addXhsProjectNotesApi,
  buildXhsMediaProxyUrl,
  createXhsAnalysisProjectApi,
  deleteXhsCollectTaskApi,
  downloadXhsCollectTaskApi,
  getXhsNoteStructuredApi,
  getXhsNoteTaskNotesApi,
  incrementalCollectXhsTaskApi,
  listXhsAnalysisProjectsApi,
  listXhsCollectTasksApi,
  listXhsNoteTasksApi,
  processXhsTaskAiDataApi,
  refreshXhsNoteApi,
} from '#/api/core/xhs';
import { groupNotesByRecency } from '#/utils/note-grouping';

import CreateCollectTaskModal from '../_shared/CreateCollectTaskModal.vue';
import { phaseLabel, progressPercent } from '../_shared/xhs-collect';
import XhsTokenManager from '../_shared/XhsTokenManager.vue';

const router = useRouter();

// 后端存的是不带时区偏移的 UTC 字符串（如 "2026-07-26T13:38:17.106045"），直接按字符串
// 截断展示，不走 new Date() 解析——避免被浏览器当成本地时间再转一遍导致时间对不上。
function formatDateTime(iso: string) {
  if (!iso) return '';
  return iso.slice(0, 16).replace('T', ' ');
}

const STATUS_LABEL: Record<string, string> = {
  pending: '排队中',
  running: '运行中',
  success: '已完成',
  failed: '失败',
};
const STATUS_DOT: Record<string, string> = {
  pending: 'bg-slate-500',
  running: 'bg-amber-400',
  success: 'bg-emerald-400',
  failed: 'bg-rose-500',
};

// ------------------------------------------------------------- 一级：任务列表 ----

const tasks = ref<XhsApi.CollectTask[]>([]);
const tasksLoading = ref(false);
const tasksTotal = ref(0);
const tasksPage = ref(1);
const tasksPageSize = 20;
const searchQuery = ref('');
const statusFilter = ref<string>('');
const aiProcessingIds = ref(new Set<number>());

async function fetchTasks() {
  tasksLoading.value = true;
  try {
    const data = await listXhsNoteTasksApi({
      query: searchQuery.value || undefined,
      status: statusFilter.value || undefined,
      page: tasksPage.value,
      page_size: tasksPageSize,
    });
    tasks.value = data.items;
    tasksTotal.value = data.total;
    aiProcessingIds.value = new Set(
      data.items.filter((task) => task.phase === 'ai_processing').map((task) => task.id),
    );
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    tasksLoading.value = false;
  }
}

let searchDebounce: ReturnType<typeof setTimeout> | undefined;
watch([searchQuery, statusFilter], () => {
  if (searchDebounce) clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => {
    tasksPage.value = 1;
    fetchTasks();
  }, 300);
});

function clearTaskFilters() {
  searchQuery.value = '';
  statusFilter.value = '';
}

// ------------------------------------------------------- 新建采集任务 + 进度 ----
// listXhsNoteTasksApi 只列出"已经有笔记数据"的采集任务（note_count > 0），刚创建、
// 还在跑第一批的任务不会出现在上面那个列表里——单独轮询一份不做这个过滤的列表，
// 只挑 running/pending 的任务显示阶段和进度，任一任务从这个集合里消失（成功或失败）
// 就顺带刷新一次上面的正式列表，让它能重新出现（或者早失败的悄悄消失）。
const newTaskModalOpen = ref(false);
const runningTasks = ref<XhsApi.CollectTask[]>([]);
let runningTasksTimer: ReturnType<typeof setInterval> | undefined;

async function fetchRunningTasks() {
  try {
    const all = await listXhsCollectTasksApi();
    const stillRunningIds = new Set(
      all.filter((t) => t.status === 'running' || t.status === 'pending').map((t) => t.id),
    );
    const hadFinished = runningTasks.value.some((t) => !stillRunningIds.has(t.id));
    runningTasks.value = all.filter((t) => stillRunningIds.has(t.id));
    if (hadFinished) fetchTasks();
    if (aiProcessingIds.value.size) fetchTasks();
  } catch {
    // 忽略单次轮询失败，下一轮再试
  }
}

function onTaskCreated() {
  fetchRunningTasks();
}

const tasksTotalPages = computed(() => Math.max(1, Math.ceil(tasksTotal.value / tasksPageSize)));
function goTasksPage(p: number) {
  if (p < 1 || p > tasksTotalPages.value) return;
  tasksPage.value = p;
  fetchTasks();
}

// ------------------------------------------------------------- 二级：任务笔记 ----

const selectedTask = ref<XhsApi.CollectTask>();
const notes = ref<XhsApi.Note[]>([]);
const notesLoading = ref(false);
const notesTotal = ref(0);
const notesPage = ref(1);
const notesPageSize = 50;
const noteSearchQuery = ref('');
const noteTypeFilter = ref<'' | '图集' | '视频'>('');
const dateRangeFilter = ref<'7d' | '30d' | '180d' | ''>('');
const selectedNoteIds = ref<Set<string>>(new Set());

const noteGroups = computed(() => groupNotesByRecency(notes.value));

async function fetchNotes() {
  if (!selectedTask.value) return;
  notesLoading.value = true;
  try {
    const data = await getXhsNoteTaskNotesApi(selectedTask.value.id, {
      query: noteSearchQuery.value || undefined,
      note_type: noteTypeFilter.value || undefined,
      date_range: dateRangeFilter.value || undefined,
      page: notesPage.value,
      page_size: notesPageSize,
    });
    notes.value = data.items;
    notesTotal.value = data.total;
  } catch (e: any) {
    message.error(`加载笔记失败：${e.message}`);
  } finally {
    notesLoading.value = false;
  }
}

let noteSearchDebounce: ReturnType<typeof setTimeout> | undefined;
watch([noteSearchQuery, noteTypeFilter, dateRangeFilter], () => {
  if (noteSearchDebounce) clearTimeout(noteSearchDebounce);
  noteSearchDebounce = setTimeout(() => {
    notesPage.value = 1;
    fetchNotes();
  }, 300);
});

const notesTotalPages = computed(() => Math.max(1, Math.ceil(notesTotal.value / notesPageSize)));
function goNotesPage(p: number) {
  if (p < 1 || p > notesTotalPages.value) return;
  notesPage.value = p;
  fetchNotes();
}

async function openTask(task: XhsApi.CollectTask) {
  selectedTask.value = task;
  notes.value = [];
  selectedNoteIds.value = new Set();
  noteSearchQuery.value = '';
  noteTypeFilter.value = '';
  dateRangeFilter.value = '';
  notesPage.value = 1;
  await fetchNotes();
}

function backToList() {
  selectedTask.value = undefined;
  notes.value = [];
  selectedNoteIds.value = new Set();
}

function toggleNoteSelect(noteId: string) {
  const next = new Set(selectedNoteIds.value);
  if (next.has(noteId)) next.delete(noteId);
  else next.add(noteId);
  selectedNoteIds.value = next;
}

const allOnPageSelected = computed(
  () => notes.value.length > 0 && notes.value.every((n) => selectedNoteIds.value.has(n.note_id)),
);
function toggleSelectAllOnPage() {
  const next = new Set(selectedNoteIds.value);
  if (allOnPageSelected.value) {
    for (const n of notes.value) next.delete(n.note_id);
  } else {
    for (const n of notes.value) next.add(n.note_id);
  }
  selectedNoteIds.value = next;
}

function coverOf(note: XhsApi.Note) {
  return note.video_cover || note.image_list[0] || '';
}
// 优先让后端发本地已下载的素材文件（CDN 原始 URL 采集完约一天后就会过期），
// 三个用途分别对应封面图/图集里第几张/正文视频，位置信息和 download_media() 落盘
// 时用的文件名规则一致（image_{index}.jpg / cover.jpg / video.mp4）。
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
const detailNote = ref<XhsApi.Note>();
function openDetail(note: XhsApi.Note) {
  detailNote.value = note;
  detailModalOpen.value = true;
}

const refreshingNote = ref(false);
async function refreshNoteData() {
  const note = detailNote.value;
  if (!note || refreshingNote.value) return;
  refreshingNote.value = true;
  try {
    const updated = await refreshXhsNoteApi(note.note_id);
    detailNote.value = updated;
    const idx = notes.value.findIndex((n) => n.note_id === note.note_id);
    if (idx !== -1) notes.value[idx] = updated;
    message.success('已刷新为最新数据');
  } catch (e: any) {
    message.error(`刷新失败：${e.message}`);
  } finally {
    refreshingNote.value = false;
  }
}

// ------------------------------------------------------------- AI 结构化数据 ----

const aiDataModalOpen = ref(false);
const aiDataLoading = ref(false);
const aiDataTitle = ref('');
const aiDataError = ref('');
const aiDataContent = ref<XhsApi.NoteStructured>();
const aiDataPretty = computed(() => (aiDataContent.value ? JSON.stringify(aiDataContent.value, null, 2) : ''));

async function openAiData(note: XhsApi.Note) {
  aiDataModalOpen.value = true;
  aiDataTitle.value = note.title || note.note_id;
  aiDataError.value = '';
  aiDataContent.value = undefined;
  aiDataLoading.value = true;
  try {
    aiDataContent.value = await getXhsNoteStructuredApi(note.note_id);
  } catch (e: any) {
    aiDataError.value = e.message || '加载失败';
  } finally {
    aiDataLoading.value = false;
  }
}

async function exportTask(kind: 'archive' | 'comments' | 'excel') {
  if (!selectedTask.value) return;
  try {
    await downloadXhsCollectTaskApi(selectedTask.value.id, kind);
  } catch (e: any) {
    message.error(`导出失败：${e.message}`);
  }
}

// ------------------------------------------------------------- 批量加入 AI 分析 ----

const addToAnalysisOpen = ref(false);
const projects = ref<XhsApi.AnalysisProject[]>([]);
const projectsLoading = ref(false);
const pickMode = ref<'existing' | 'new'>('existing');
const pickProjectId = ref<number>();
const newProjectName = ref('');
const addingToAnalysis = ref(false);

async function openAddToAnalysis() {
  if (selectedNoteIds.value.size === 0) return;
  addToAnalysisOpen.value = true;
  pickMode.value = 'existing';
  pickProjectId.value = undefined;
  newProjectName.value = '';
  projectsLoading.value = true;
  try {
    projects.value = await listXhsAnalysisProjectsApi();
    if (projects.value.length === 0) pickMode.value = 'new';
    else pickProjectId.value = projects.value[0]?.id;
  } catch (e: any) {
    message.error(`加载分析项目失败：${e.message}`);
  } finally {
    projectsLoading.value = false;
  }
}

async function confirmAddToAnalysis() {
  if (!selectedTask.value) return;
  const noteIds = [...selectedNoteIds.value];
  addingToAnalysis.value = true;
  try {
    let projectId = pickProjectId.value;
    if (pickMode.value === 'new') {
      if (!newProjectName.value.trim()) {
        message.error('请输入新项目名称');
        addingToAnalysis.value = false;
        return;
      }
      const created = await createXhsAnalysisProjectApi(newProjectName.value.trim());
      projectId = created.id;
    }
    if (!projectId) {
      message.error('请选择一个分析项目');
      addingToAnalysis.value = false;
      return;
    }
    const added = await addXhsProjectNotesApi(projectId, selectedTask.value.id, noteIds);
    message.success(`已加入 ${added.length} 篇笔记到分析项目`);
    addToAnalysisOpen.value = false;
    selectedNoteIds.value = new Set();
  } catch (e: any) {
    message.error(`加入失败：${e.message}`);
  } finally {
    addingToAnalysis.value = false;
  }
}

function goAiAnalysis() {
  router.push('/xhs/ai-analysis');
}

function deleteTask(task: XhsApi.CollectTask) {
  Modal.confirm({
    title: `确定删除任务「${task.keyword}」及其所有数据吗？`,
    content: '此操作不可恢复。',
    okType: 'danger',
    onOk: async () => {
      try {
        await deleteXhsCollectTaskApi(task.id);
        message.success('已删除');
        fetchTasks();
      } catch (e: any) {
        message.error(`删除失败：${e.message}`);
      }
    },
  });
}

async function processAiData(task: XhsApi.CollectTask) {
  try {
    aiProcessingIds.value = new Set(aiProcessingIds.value).add(task.id);
    const result = await processXhsTaskAiDataApi(task.id);
    message.success(result.message);
    await fetchTasks();
  } catch (e: any) {
    aiProcessingIds.value.delete(task.id);
    aiProcessingIds.value = new Set(aiProcessingIds.value);
    message.error(`AI 数据处理失败：${e.message}`);
  }
}

// ------------------------------------------------------------- 增量采集 ----
// 小红书搜索没有翻页续搜的游标，实际新增数量可能少于填写的数量（该关键词候选已
// 接近用尽时），后端会在 message 里说明"新增 X/Y 篇"。

const incrementalModalOpen = ref(false);
const incrementalTarget = ref<XhsApi.CollectTask>();
const incrementalCount = ref(50);
const incrementalSubmitting = ref(false);

function openIncrementalModal(task: XhsApi.CollectTask) {
  incrementalTarget.value = task;
  incrementalCount.value = 50;
  incrementalModalOpen.value = true;
}

async function submitIncremental() {
  const task = incrementalTarget.value;
  if (!task || incrementalCount.value < 1) return;
  incrementalSubmitting.value = true;
  try {
    await incrementalCollectXhsTaskApi(task.id, incrementalCount.value);
    message.success('已开始增量采集，可在下方进度面板查看');
    incrementalModalOpen.value = false;
    fetchRunningTasks();
  } catch (e: any) {
    message.error(`发起失败：${e.message}`);
  } finally {
    incrementalSubmitting.value = false;
  }
}

onMounted(() => {
  fetchTasks();
  fetchRunningTasks();
  runningTasksTimer = setInterval(fetchRunningTasks, 3000);
});

onBeforeUnmount(() => {
  if (runningTasksTimer) clearInterval(runningTasksTimer);
});
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-[#0B0E14] p-6 select-none">
      <div class="mb-4 shrink-0">
        <XhsTokenManager />
      </div>

      <!-- ============================================== 一级：采集任务列表 -->
      <template v-if="!selectedTask">
        <div class="mb-6 shrink-0 flex items-start justify-between gap-3">
          <div>
            <h1 class="text-xl font-extrabold text-white">笔记管理</h1>
            <p class="mt-1 text-xs text-slate-400">按采集主题浏览已经抓取的笔记，点击进入某个主题查看具体笔记</p>
          </div>
          <button
            class="flex shrink-0 items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500"
            @click="newTaskModalOpen = true"
          >
            <Plus class="h-3.5 w-3.5" />
            采集任务
          </button>
        </div>

        <!-- 进行中的采集任务：新任务还没有笔记数据时不会出现在下面的正式列表里，
             单独轮询展示阶段和进度，任务一完成/失败就自动从这里消失 -->
        <div v-if="runningTasks.length" class="mb-4 shrink-0 space-y-2">
          <div
            v-for="task in runningTasks"
            :key="task.id"
            class="rounded-xl border border-[#1E2433] bg-[#0F131C] px-4 py-3"
          >
            <div class="mb-1.5 flex items-center justify-between text-xs">
              <span class="font-semibold text-white">{{ task.keyword }}</span>
              <span class="text-slate-400">
                {{ phaseLabel(task.phase) }}
                <template v-if="task.progress_total">（{{ task.progress_current }} / {{ task.progress_total }}）</template>
              </span>
            </div>
            <div class="h-1.5 w-full overflow-hidden rounded-full bg-[#1E2433]">
              <div
                class="h-full rounded-full bg-indigo-500 transition-all"
                :style="{ width: `${progressPercent(task)}%` }"
              ></div>
            </div>
          </div>
        </div>

        <div class="mb-4 shrink-0 flex flex-wrap items-center gap-2">
          <div class="relative">
            <Search class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
            <input
              v-model="searchQuery"
              placeholder="搜索主题或关键词"
              class="w-64 rounded-lg border border-[#232B3E] bg-[#121622] py-1.5 pr-3 pl-8 text-xs text-white outline-none focus:border-indigo-500"
            />
          </div>
          <select
            v-model="statusFilter"
            class="rounded-lg border border-[#232B3E] bg-[#121622] px-3 py-1.5 text-xs text-white outline-none focus:border-indigo-500"
          >
            <option value="">全部状态</option>
            <option value="running">运行中</option>
            <option value="success">已完成</option>
            <option value="failed">失败</option>
          </select>
        </div>

        <div class="shrink-0 overflow-hidden rounded-2xl border border-[#1E2433] bg-[#0F131C] shadow-xl">
          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="border-b border-[#1E2433] bg-[#121622] font-mono text-[11px] text-slate-400 uppercase">
                <tr>
                  <th class="px-4 py-3.5">采集主题与关键词</th>
                  <th class="px-4 py-3.5">状态</th>
                  <th class="px-4 py-3.5">主题笔记</th>
                  <th class="px-4 py-3.5">
                    <Tooltip title="最近一轮采集（全新或增量）实际新增的笔记数">
                      <span class="cursor-help border-b border-dashed border-slate-600">本次新增</span>
                    </Tooltip>
                  </th>
                  <th class="px-4 py-3.5">
                    <Tooltip title="后端暂未提供该字段，可后续从分析项目关联统计后接入">
                      <span class="cursor-help border-b border-dashed border-slate-600">已选证据</span>
                    </Tooltip>
                  </th>
                  <th class="px-4 py-3.5">
                    <Tooltip title="Task 表目前只有创建时间，没有单独的更新时间字段">
                      <span class="cursor-help border-b border-dashed border-slate-600">最近更新</span>
                    </Tooltip>
                  </th>
                  <th class="px-4 py-3.5 text-right">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-[#1E2433]">
                <tr
                  v-for="task in tasks"
                  :key="task.id"
                  tabindex="0"
                  class="group cursor-pointer transition-colors hover:bg-[#161C2A] focus:bg-[#161C2A] focus:outline-none focus-visible:ring-1 focus-visible:ring-indigo-500"
                  @click="openTask(task)"
                  @keyup.enter="openTask(task)"
                >
                  <td class="px-4 py-4">
                    <div class="font-semibold text-white">{{ task.keyword }}</div>
                    <div class="mt-0.5 text-[11px] text-slate-500">关键词：{{ task.keyword }}</div>
                  </td>
                  <td class="px-4 py-4">
                    <span
class="inline-flex items-center gap-1.5 font-semibold" :class="[
                      task.status === 'success' ? 'text-emerald-400' : task.status === 'failed' ? 'text-rose-400' : task.status === 'running' ? 'text-amber-300' : 'text-slate-400',
                    ]"
>
                      <span class="h-1.5 w-1.5 rounded-full" :class="STATUS_DOT[task.status]"></span>
                      {{ STATUS_LABEL[task.status] || task.status }}
                    </span>
                  </td>
                  <td class="px-4 py-4 font-mono text-slate-200">{{ task.note_count }}</td>
                  <td class="px-4 py-4 font-mono text-slate-200">{{ task.collect_stats?.collected_count ?? '—' }}</td>
                  <td class="px-4 py-4 text-slate-600">—</td>
                  <td class="px-4 py-4 text-slate-400">{{ formatDateTime(task.created_at) }}（创建时间）</td>
                  <td class="px-4 py-4 text-right">
                    <div class="flex items-center justify-end gap-3">
                      <button
                        class="text-[11px] text-slate-500 hover:text-indigo-400 disabled:opacity-40"
                        :disabled="task.status === 'running' || task.status === 'pending'"
                        @click.stop="openIncrementalModal(task)"
                      >
                        增量采集
                      </button>
                      <Tooltip title="使用智谱补齐缺失、失败或正文已变化的 AI 结构化数据；已成功且内容未变化的笔记会自动跳过">
                        <button
                          class="text-[11px] text-slate-500 hover:text-cyan-400 disabled:cursor-not-allowed disabled:opacity-40"
                          :disabled="task.status === 'running' || task.status === 'pending' || aiProcessingIds.has(task.id)"
                          @click.stop="processAiData(task)"
                        >
                          <template v-if="aiProcessingIds.has(task.id)">
                            AI 处理中 {{ task.progress_current }}/{{ task.progress_total }}
                          </template>
                          <template v-else>AI 数据处理</template>
                        </button>
                      </Tooltip>
                      <button class="text-[11px] text-slate-500 hover:text-rose-400" @click.stop="deleteTask(task)">删除</button>
                      <span class="inline-flex items-center gap-1 font-semibold text-indigo-400 group-hover:text-indigo-300">
                        查看笔记
                        <ChevronRight class="h-3.5 w-3.5" />
                      </span>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="!tasksLoading && tasks.length === 0" class="flex flex-col items-center justify-center gap-3 p-12 text-center">
            <template v-if="searchQuery || statusFilter">
              <p class="text-sm font-semibold text-white">没有匹配的采集任务</p>
              <button class="rounded-lg border border-[#232B3E] bg-[#121622] px-3 py-1.5 text-xs text-slate-300 hover:text-white" @click="clearTaskFilters">
                清除筛选条件
              </button>
            </template>
            <template v-else>
              <p class="text-sm font-semibold text-white">暂无已保存的笔记数据</p>
              <p class="text-xs text-slate-400">先发起一次采集吧</p>
              <button class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500" @click="newTaskModalOpen = true">
                新建采集任务
              </button>
            </template>
          </div>
        </div>

        <div v-if="tasksTotal > tasksPageSize" class="mt-4 shrink-0 flex items-center justify-between text-xs text-slate-400">
          <span>共 {{ tasksTotal }} 个采集主题</span>
          <div class="flex items-center gap-2">
            <button class="rounded-lg border border-[#232B3E] bg-[#121622] px-2 py-1 disabled:opacity-40" :disabled="tasksPage <= 1" @click="goTasksPage(tasksPage - 1)">上一页</button>
            <span>{{ tasksPage }} / {{ tasksTotalPages }}</span>
            <button class="rounded-lg border border-[#232B3E] bg-[#121622] px-2 py-1 disabled:opacity-40" :disabled="tasksPage >= tasksTotalPages" @click="goTasksPage(tasksPage + 1)">下一页</button>
          </div>
        </div>
      </template>

      <!-- ============================================== 二级：任务笔记 -->
      <template v-else>
        <div class="mb-4 shrink-0 flex flex-wrap items-center gap-3">
          <button class="flex items-center gap-1 rounded-lg border border-[#232B3E] bg-[#121622] px-3 py-1.5 text-xs text-slate-300 hover:text-white" @click="backToList">
            <ArrowLeft class="h-3.5 w-3.5" />
            返回列表
          </button>
          <div class="text-xs text-slate-500">
            采集主题 / <span class="text-white">{{ selectedTask.keyword }}</span>
          </div>
          <Tag color="blue">{{ selectedTask.note_count }} 篇笔记</Tag>
        </div>

        <div class="mb-4 shrink-0 flex flex-wrap items-center gap-2">
          <div class="relative">
            <Search class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
            <input
              v-model="noteSearchQuery"
              placeholder="搜索标题、内容或作者"
              class="w-56 rounded-lg border border-[#232B3E] bg-[#121622] py-1.5 pr-3 pl-8 text-xs text-white outline-none focus:border-indigo-500"
            />
          </div>
          <select v-model="noteTypeFilter" class="rounded-lg border border-[#232B3E] bg-[#121622] px-3 py-1.5 text-xs text-white outline-none focus:border-indigo-500">
            <option value="">全部类型</option>
            <option value="图集">图集</option>
            <option value="视频">视频</option>
          </select>
          <select v-model="dateRangeFilter" class="rounded-lg border border-[#232B3E] bg-[#121622] px-3 py-1.5 text-xs text-white outline-none focus:border-indigo-500">
            <option value="">全部时间</option>
            <option value="7d">最近一周</option>
            <option value="30d">最近一个月</option>
            <option value="180d">最近半年</option>
          </select>
          <Tooltip title="后端暂未支持互动量筛选">
            <button disabled class="cursor-not-allowed rounded-lg border border-[#232B3E] bg-[#121622] px-3 py-1.5 text-xs text-slate-600">互动量筛选</button>
          </Tooltip>
          <Tooltip title="后端暂未支持更多筛选条件">
            <button disabled class="cursor-not-allowed rounded-lg border border-[#232B3E] bg-[#121622] px-3 py-1.5 text-xs text-slate-600">更多筛选</button>
          </Tooltip>

          <span class="flex-1"></span>

          <span v-if="selectedNoteIds.size > 0" class="text-xs text-slate-400">已选择 {{ selectedNoteIds.size }} 项</span>
          <button
            class="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="selectedNoteIds.size === 0"
            @click="openAddToAnalysis"
          >
            批量加入 AI 分析
          </button>
          <Tooltip title="后端暂未支持给笔记添加标签">
            <button disabled class="flex cursor-not-allowed items-center gap-1 rounded-lg border border-[#232B3E] bg-[#121622] px-3 py-1.5 text-xs text-slate-600">
              <TagsIcon class="h-3.5 w-3.5" />
              添加标签
            </button>
          </Tooltip>
          <Dropdown :trigger="['click']">
            <button class="flex items-center gap-1 rounded-lg border border-[#232B3E] bg-[#121622] px-3 py-1.5 text-xs text-slate-300 hover:text-white">
              <Download class="h-3.5 w-3.5" />
              导出
            </button>
            <template #overlay>
              <Menu>
                <MenuItem key="excel" @click="exportTask('excel')">导出 Excel</MenuItem>
                <MenuItem v-if="selectedTask.has_comments" key="comments" @click="exportTask('comments')">导出评论</MenuItem>
                <MenuItem key="archive" @click="exportTask('archive')">导出素材压缩包</MenuItem>
              </Menu>
            </template>
          </Dropdown>
        </div>

        <div class="shrink-0 overflow-hidden rounded-2xl border border-[#1E2433] bg-[#0F131C] shadow-xl">
          <div v-if="!notesLoading && notes.length === 0" class="flex flex-col items-center justify-center gap-2 p-12 text-center">
            <p class="text-sm font-semibold text-white">
              {{ noteSearchQuery || noteTypeFilter || dateRangeFilter ? '没有匹配的笔记' : '该任务暂无笔记数据' }}
            </p>
          </div>
          <div v-else class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="border-b border-[#1E2433] bg-[#121622] font-mono text-[11px] text-slate-400 uppercase">
                <tr>
                  <th class="px-3 py-3">
                    <Checkbox :checked="allOnPageSelected" @change="toggleSelectAllOnPage" />
                  </th>
                  <th class="px-4 py-3">笔记信息</th>
                  <th class="px-4 py-3">内容类型</th>
                  <th class="px-4 py-3">发布时间</th>
                  <th class="px-4 py-3">点赞</th>
                  <th class="px-4 py-3">评论</th>
                  <th class="px-4 py-3">收藏</th>
                  <th class="px-4 py-3">标签</th>
                  <th class="px-4 py-3 text-right">操作</th>
                </tr>
              </thead>
              <template v-for="group in noteGroups" :key="group.label">
                <tbody class="divide-y divide-[#1E2433]">
                  <tr>
                    <td colspan="9" class="bg-[#121622] px-4 py-2 text-[11px] font-bold text-slate-400">{{ group.label }}</td>
                  </tr>
                  <tr
                    v-for="note in group.notes"
                    :key="note.note_id"
                    class="cursor-pointer transition-colors hover:bg-[#161C2A]"
                    @click="openDetail(note)"
                  >
                    <td class="px-3 py-3" @click.stop="toggleNoteSelect(note.note_id)">
                      <Checkbox :checked="selectedNoteIds.has(note.note_id)" />
                    </td>
                    <td class="px-4 py-3">
                      <div class="flex items-center gap-2.5">
                        <div class="h-10 w-10 shrink-0 overflow-hidden rounded-lg bg-[#181F30]">
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
                          <div class="truncate font-semibold text-white">{{ note.title || '无标题' }}</div>
                          <div class="text-[11px] text-slate-500">{{ note.nickname }}</div>
                        </div>
                      </div>
                    </td>
                    <td class="px-4 py-3 text-slate-300">{{ note.note_type || '—' }}</td>
                    <td class="px-4 py-3 text-slate-400">{{ note.upload_time }}</td>
                    <td class="px-4 py-3 font-mono text-slate-300">{{ note.liked_count }}</td>
                    <td class="px-4 py-3 font-mono text-slate-300">{{ note.comment_count }}</td>
                    <td class="px-4 py-3 font-mono text-slate-300">{{ note.collected_count }}</td>
                    <td class="px-4 py-3">
                      <div class="flex flex-wrap gap-1">
                        <Tag v-for="tag in note.tags.slice(0, 3)" :key="tag" color="default">{{ tag }}</Tag>
                      </div>
                    </td>
                    <td class="px-4 py-3 text-right">
                      <button
                        class="text-[11px] text-slate-500 hover:text-blue-400"
                        @click.stop="openAiData(note)"
                      >
                        AI 数据
                      </button>
                    </td>
                  </tr>
                </tbody>
              </template>
            </table>
          </div>
        </div>

        <div v-if="notesTotal > notesPageSize" class="mt-4 shrink-0 flex items-center justify-between text-xs text-slate-400">
          <span>共 {{ notesTotal }} 篇笔记</span>
          <div class="flex items-center gap-2">
            <button class="rounded-lg border border-[#232B3E] bg-[#121622] px-2 py-1 disabled:opacity-40" :disabled="notesPage <= 1" @click="goNotesPage(notesPage - 1)">上一页</button>
            <span>{{ notesPage }} / {{ notesTotalPages }}</span>
            <button class="rounded-lg border border-[#232B3E] bg-[#121622] px-2 py-1 disabled:opacity-40" :disabled="notesPage >= notesTotalPages" @click="goNotesPage(notesPage + 1)">下一页</button>
          </div>
        </div>
      </template>
    </div>

    <!-- 单篇笔记详情 -->
    <Modal v-model:open="detailModalOpen" :title="detailNote?.title || '无标题'" :footer="null" width="720px">
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
        <p style="margin-bottom: 4px; font-size: 12px; color: #8290a5">
          {{ detailNote.nickname }} · {{ detailNote.upload_time }} · {{ detailNote.ip_location }}
        </p>
        <p style="margin-bottom: 12px; font-size: 12px; color: #8290a5">
          ♥ {{ detailNote.liked_count }} · ★ {{ detailNote.collected_count }} · 💬 {{ detailNote.comment_count }}
        </p>
        <div style="display: flex; gap: 8px">
          <button
            v-if="detailNote.note_url"
            class="rounded-lg border border-indigo-500/40 bg-indigo-600/10 px-3 py-1.5 text-xs font-bold text-indigo-300 hover:bg-indigo-600/20"
            @click="openInXhs(detailNote.note_url)"
          >
            在小红书查看原文
          </button>
          <button
            class="rounded-lg border border-[#232B3E] bg-[#121622] px-3 py-1.5 text-xs font-bold text-slate-300 hover:text-white disabled:opacity-50"
            :disabled="refreshingNote"
            @click="refreshNoteData"
          >
            {{ refreshingNote ? '刷新中…' : '刷新最新数据' }}
          </button>
        </div>
      </template>
    </Modal>

    <!-- AI 结构化数据（智谱 GLM 预处理结果） -->
    <Modal v-model:open="aiDataModalOpen" :title="`AI 结构化数据 · ${aiDataTitle}`" :footer="null" width="640px">
      <Spin :spinning="aiDataLoading">
        <Empty v-if="!aiDataLoading && aiDataError" :description="aiDataError" />
        <pre
          v-else-if="aiDataContent"
          class="max-h-[60vh] overflow-auto rounded-lg bg-[#121622] p-4 text-xs text-slate-300"
          style="white-space: pre-wrap; word-break: break-all"
          >{{ aiDataPretty }}</pre>
        <div v-else style="min-height: 120px"></div>
      </Spin>
    </Modal>

    <!-- 批量加入 AI 分析 -->
    <Modal
      v-model:open="addToAnalysisOpen"
      title="加入 AI 分析项目"
      :confirm-loading="addingToAnalysis"
      ok-text="确认加入"
      @ok="confirmAddToAnalysis"
    >
      <p class="mb-3 text-xs text-slate-400">已选择 {{ selectedNoteIds.size }} 篇笔记</p>
      <RadioGroup v-model:value="pickMode" class="mb-3">
        <Radio value="existing" :disabled="projects.length === 0">加入已有项目</Radio>
        <Radio value="new">新建项目</Radio>
      </RadioGroup>
      <div v-if="pickMode === 'existing'">
        <select
          v-model="pickProjectId"
          class="w-full rounded-lg border border-[#232B3E] bg-[#121622] px-3 py-2 text-xs text-white outline-none focus:border-indigo-500"
        >
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}（{{ p.note_count }} 篇）</option>
        </select>
      </div>
      <div v-else>
        <input
          v-model="newProjectName"
          placeholder="新分析项目名称"
          class="w-full rounded-lg border border-[#232B3E] bg-[#121622] px-3 py-2 text-xs text-white outline-none focus:border-indigo-500"
        />
      </div>
      <button class="mt-3 text-xs text-indigo-400 hover:text-indigo-300" @click="goAiAnalysis">前往 AI 分析页面 →</button>
    </Modal>

    <!-- 新建采集任务：表单本身在共享组件里，和「采集任务」页用同一个 -->
    <CreateCollectTaskModal
      v-model:open="newTaskModalOpen"
      :tasks="tasks"
      @created="onTaskCreated"
    />

    <!-- 增量采集：跳过已采集过的笔记，只补齐填写的数量 -->
    <Modal
      v-model:open="incrementalModalOpen"
      :title="`增量采集 · ${incrementalTarget?.keyword ?? ''}`"
      :confirm-loading="incrementalSubmitting"
      ok-text="开始采集"
      cancel-text="取消"
      @ok="submitIncremental"
    >
      <p class="mb-3 text-xs text-slate-500">
        当前主题笔记：{{ incrementalTarget?.note_count ?? 0 }} 篇。会跳过已经采集过的笔记，只补齐下面填写的新增数量；
        如果该关键词候选内容已经接近用尽，实际新增可能少于填写的数量。
      </p>
      <div class="mb-1 text-xs font-bold text-slate-400">本次新增数量</div>
      <input
        v-model.number="incrementalCount"
        type="number"
        min="1"
        max="500"
        class="w-full rounded-lg border border-[#232B3E] bg-[#121622] px-3 py-2 text-xs text-white outline-none focus:border-indigo-500"
      />
    </Modal>
  </Page>
</template>
