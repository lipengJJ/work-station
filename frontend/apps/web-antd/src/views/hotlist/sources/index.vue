<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Form,
  FormItem,
  Input,
  message,
  Modal,
  Select,
  Switch,
  Tooltip,
} from 'ant-design-vue';
import { ArrowLeft, CheckCircle2, FolderInput, Layers, Plus, RefreshCw, Rss, TriangleAlert, Upload } from 'lucide-vue-next';

import GroupManagerModal from './components/GroupManagerModal.vue';

import {
  batchSourcesApi,
  crawlOneSourceApi,
  crawlSourcesApi,
  createHotlistSourceApi,
  deleteHotlistSourceApi,
  getCrawlStatusApi,
  importSourcesOpmlApi,
  listHotlistSourcesApi,
  listSourceGroupsApi,
  updateHotlistSourceApi,
} from '#/api/core/hotlist';

const KIND_LABEL: Record<HotlistApi.SourceKind, string> = {
  hotlist: '中文热榜',
  tech: '技术源',
};

// 瞬时类失败（本机 DNS 抖动、上游整体故障）不是这个源坏了，用橙色；
// 永久类（地址失效 / 解析失败）才是真的要处理，用红色。
const TRANSIENT_KINDS = new Set([
  'connect_timeout',
  'connection_error',
  'dns_error',
  'read_timeout',
  'upstream_5xx',
  'upstream_down',
]);

function statusInfo(source: HotlistApi.Source) {
  if (!source.enabled) return { label: '已停用', dot: 'bg-muted-foreground', text: 'text-muted-foreground' };
  if (source.last_status === 'failed') {
    const kind = source.last_error_kind;
    const label = source.last_error_label || '失败';
    const times = source.consecutive_failures > 1 ? `（${source.consecutive_failures} 次）` : '';
    // 没有 kind = 旧数据（本次改造之前记的），照旧显示
    if (!kind) return { label: `失败（连续 ${source.consecutive_failures} 次）`, dot: 'bg-destructive', text: 'text-destructive' };
    return TRANSIENT_KINDS.has(kind)
      ? { label: `${label}${times}`, dot: 'bg-warning', text: 'text-warning' }
      : { label: `${label}${times}`, dot: 'bg-destructive', text: 'text-destructive' };
  }
  if (source.last_status === 'success') return { label: '正常', dot: 'bg-success', text: 'text-success' };
  return { label: '待抓取', dot: 'bg-muted-foreground', text: 'text-muted-foreground' };
}

// -------------------------------------------------------------- 数据 ----
const allSources = ref<HotlistApi.Source[]>([]);
const groups = ref<HotlistApi.SourceGroup[]>([]);
const loading = ref(false);
type FilterKey = 'all' | 'ungrouped' | number;
const activeFilter = ref<FilterKey>('all');

const enabledSourceCount = computed(() => allSources.value.filter((s) => s.enabled).length);
const failedSourceCount = computed(() => allSources.value.filter((s) => s.enabled && s.last_status === 'failed').length);

// -------------------------------------------------------------- 分组卡片视图 ----
// 默认只看分组，不关心具体某条 RSS 源；点进某个分组才展开该组的源表格。
const viewMode = ref<'groups' | 'table'>('groups');

function healthSummary(sources: HotlistApi.Source[]) {
  let failed = 0;
  let ok = 0;
  let pending = 0;
  for (const s of sources) {
    if (!s.enabled) continue;
    if (s.last_status === 'failed') failed++;
    else if (s.last_status === 'success') ok++;
    else pending++;
  }
  return { failed, ok, pending };
}

const groupCards = computed(() => {
  const ungroupedSources = allSources.value.filter((s) => s.group_id === null || s.group_id === undefined);
  const cards = groups.value.map((g) => {
    const sources = allSources.value.filter((s) => s.group_id === g.id);
    return {
      key: g.id as FilterKey,
      name: g.name,
      color: g.color || '#8c8c8c',
      count: sources.length,
      enabledCount: sources.filter((s) => s.enabled).length,
      ...healthSummary(sources),
    };
  });
  cards.push({
    key: 'ungrouped',
    name: '未分组',
    color: '#8c8c8c',
    count: ungroupedSources.length,
    enabledCount: ungroupedSources.filter((s) => s.enabled).length,
    ...healthSummary(ungroupedSources),
  });
  return cards;
});

function enterGroup(key: FilterKey) {
  activeFilter.value = key;
  viewMode.value = 'table';
}

function backToGroups() {
  viewMode.value = 'groups';
}

const groupById = computed(() => new Map(groups.value.map((g) => [g.id, g])));

const filteredSources = computed(() => {
  if (activeFilter.value === 'all') return allSources.value;
  if (activeFilter.value === 'ungrouped') {
    return allSources.value.filter((s) => s.group_id === null || s.group_id === undefined);
  }
  return allSources.value.filter((s) => s.group_id === activeFilter.value);
});

const filterTabs = computed(() => {
  const total = allSources.value.length;
  const ungrouped = allSources.value.filter((s) => s.group_id === null || s.group_id === undefined).length;
  return [
    { key: 'all' as FilterKey, label: `全部（${total}）` },
    { key: 'ungrouped' as FilterKey, label: `未分组（${ungrouped}）` },
    ...groups.value.map((g) => ({
      key: g.id as FilterKey,
      label: `${g.name}（${g.source_count}）`,
    })),
  ];
});

async function fetchSources() {
  loading.value = true;
  try {
    const [sources, groupList] = await Promise.all([listHotlistSourcesApi(), listSourceGroupsApi()]);
    allSources.value = sources;
    groups.value = groupList;
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    loading.value = false;
  }
}

// -------------------------------------------------------------- 立即抓取 ----
// 状态列展示的是「上一次抓取」的结果。这些源的 cron 多是 4 小时一次，网络恢复或
// 改完配置后不该干等到下个整点才知道好没好，所以给一个手动触发 + 自动刷新。

/** 正在抓取中的源 id（行内按钮转圈用） */
const crawlingIds = ref<Set<string>>(new Set());
/** 批量抓取进行中：轮询后端进度，直到整批抓完 */
const batchCrawling = ref(false);
const batchCrawlHint = ref('');
let pollTimer: null | ReturnType<typeof setTimeout> = null;

// 批量抓取的状态要能在刷新页面后恢复：把 job_id + 目标源 + 开跑时间存进
// sessionStorage（F5 刷新不清），mount 时读回来继续轮询后端进度。
const BATCH_CRAWL_STORAGE_KEY = 'hotlist.batch-crawl';
const BATCH_CRAWL_TIMEOUT_MS = 180_000;

interface BatchCrawlState {
  jobId: string;
  targets: string[];
  startedAt: number;
}

function persistBatchCrawl(state: BatchCrawlState) {
  sessionStorage.setItem(BATCH_CRAWL_STORAGE_KEY, JSON.stringify(state));
}

function loadBatchCrawl(): null | BatchCrawlState {
  try {
    const raw = sessionStorage.getItem(BATCH_CRAWL_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as BatchCrawlState;
    if (!parsed?.jobId || !Array.isArray(parsed?.targets)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function clearBatchCrawl() {
  sessionStorage.removeItem(BATCH_CRAWL_STORAGE_KEY);
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
  batchCrawling.value = false;
  batchCrawlHint.value = '';
  clearBatchCrawl();
}

/** 抓单个源：同步接口，返回即是该源抓完后的最新状态，直接替换这一行 */
async function crawlOne(source: HotlistApi.Source) {
  if (crawlingIds.value.has(source.id)) return;
  crawlingIds.value = new Set(crawlingIds.value).add(source.id);
  try {
    const updated = await crawlOneSourceApi(source.id);
    Object.assign(source, updated);
    if (updated.last_status === 'success') {
      message.success(`${updated.name || updated.id}：抓取成功，共 ${updated.total_fetched} 条`);
    } else {
      message.warning(`${updated.name || updated.id}：${updated.last_error_label || '抓取失败'}`);
    }
  } catch (e: any) {
    message.error(`抓取失败：${e.response?.data?.detail || e.message}`);
  } finally {
    const next = new Set(crawlingIds.value);
    next.delete(source.id);
    crawlingIds.value = next;
  }
}

/**
 * 批量抓取：后端后台跑，这里轮询 /crawl-status 的进度，直到整批抓完
 * （或超过 3 分钟兜底停止）。进度存在后端 + sessionStorage，刷新页面也能恢复。
 */
function schedulePoll(jobId: string, targets: string[], startedAt: number) {
  const deadline = startedAt + BATCH_CRAWL_TIMEOUT_MS;
  const poll = async () => {
    let gotStatus = false;
    let running = false;
    let done = 0;
    let total = targets.length;
    let finished = false;
    let skipped = false;
    let failed = 0;
    try {
      const st = await getCrawlStatusApi(jobId);
      gotStatus = true;
      running = st.running;
      done = st.done ?? 0;
      total = st.total ?? total;
      finished = st.finished ?? false;
      skipped = st.skipped ?? false;
      failed = st.failed ?? 0;
    } catch {
      // 单次状态查询失败，下一轮再试
    }

    // 顺手刷新列表，状态列跟着变（失败也不影响主流程）
    try {
      allSources.value = await listHotlistSourcesApi();
    } catch {
      // 忽略
    }

    if (gotStatus && !running) {
      stopPolling();
      if (finished && skipped) {
        message.info('本轮抓取未执行（本机网络不可用），未累加失败');
        return;
      }
      const failedCount =
        failed > 0
          ? failed
          : allSources.value.filter(
              (s) => targets.includes(s.id) && s.last_status === 'failed',
            ).length;
      if (failedCount > 0) {
        message.warning(`抓取完成，${failedCount} 个源失败（状态列已写明原因）`);
      } else {
        message.success('抓取完成');
      }
      return;
    }

    batchCrawlHint.value = `正在抓取… ${done}/${total}`;
    if (Date.now() > deadline) {
      stopPolling();
      message.info('抓取仍在进行，可稍后手动刷新查看结果');
      return;
    }
    pollTimer = setTimeout(poll, 3000);
  };
  pollTimer = setTimeout(poll, 3000);
}

async function crawlMany(sourceIds: string[], label: string) {
  if (batchCrawling.value) return;
  const targets = sourceIds.length > 0 ? sourceIds : allSources.value.filter((s) => s.enabled).map((s) => s.id);
  if (targets.length === 0) {
    message.warning('没有可抓取的源');
    return;
  }
  let res: HotlistApi.CrawlTrigger;
  try {
    res = await crawlSourcesApi(sourceIds);
  } catch (e: any) {
    message.error(`触发失败：${e.response?.data?.detail || e.message}`);
    return;
  }
  batchCrawling.value = true;
  batchCrawlHint.value = `正在抓取 ${res.count} 个源…`;
  const startedAt = Date.now();
  persistBatchCrawl({ jobId: res.job_id, targets, startedAt });
  message.success(`已开始抓取 ${label}（${res.count} 个源），完成后会自动刷新`);
  schedulePoll(res.job_id, targets, startedAt);
}

/** 刷新页面后恢复「正在抓取」的显示：sessionStorage 里还有未完成的批次就继续轮询 */
function resumeBatchCrawl() {
  const saved = loadBatchCrawl();
  if (!saved) return;
  // 早就超过轮询兜底时间，这单肯定已结束，直接清掉
  if (Date.now() - saved.startedAt > BATCH_CRAWL_TIMEOUT_MS) {
    clearBatchCrawl();
    return;
  }
  batchCrawling.value = true;
  batchCrawlHint.value = '正在恢复抓取状态…';
  schedulePoll(saved.jobId, saved.targets, saved.startedAt);
}

onUnmounted(stopPolling);

async function toggleEnabled(source: HotlistApi.Source, enabled: boolean) {
  try {
    await updateHotlistSourceApi(source.id, { enabled });
    source.enabled = enabled;
    message.success(enabled ? '已启用' : '已停用');
  } catch (e: any) {
    message.error(`操作失败：${e.message}`);
  }
}

// -------------------------------------------------------------- 多选 + 批量 ----
const selectedKeys = ref<string[]>([]);
const batchMoveOpen = ref(false);
const batchMoveGroup = ref<number | undefined>(undefined);
const batchMoving = ref(false);

function groupLabel(id: number | null | undefined) {
  if (id === null || id === undefined) return '未分组';
  return groupById.value.get(id)?.name || `分组 ${id}`;
}

async function batchSetEnabled(enabled: boolean) {
  if (selectedKeys.value.length === 0) {
    message.warning('请先勾选源');
    return;
  }
  try {
    const res = await batchSourcesApi({ source_ids: selectedKeys.value, enabled });
    message.success(`已${enabled ? '启用' : '停用'} ${res.enabled_changed} 个源`);
    selectedKeys.value = [];
    fetchSources();
  } catch (e: any) {
    message.error(`操作失败：${e.response?.data?.detail || e.message}`);
  }
}

async function submitBatchMove() {
  if (selectedKeys.value.length === 0) {
    message.warning('请先勾选源');
    return;
  }
  batchMoving.value = true;
  try {
    const res = await batchSourcesApi({
      source_ids: selectedKeys.value,
      group_id: batchMoveGroup.value ?? null,
    });
    message.success(`已移动 ${res.moved} 个源`);
    batchMoveOpen.value = false;
    batchMoveGroup.value = undefined;
    selectedKeys.value = [];
    fetchSources();
  } catch (e: any) {
    message.error(`移动失败：${e.response?.data?.detail || e.message}`);
  } finally {
    batchMoving.value = false;
  }
}

// -------------------------------------------------------------- 编辑 ----
const editModalOpen = ref(false);
const editTarget = ref<HotlistApi.Source | null>(null);
const editForm = reactive({ name: '', cron_expr: '', expected_domain: '' });
const editSaving = ref(false);

function openEdit(source: HotlistApi.Source) {
  editTarget.value = source;
  editForm.name = source.name;
  editForm.cron_expr = source.cron_expr;
  editForm.expected_domain = source.expected_domain;
  editModalOpen.value = true;
}

async function submitEdit() {
  if (!editTarget.value) return;
  editSaving.value = true;
  try {
    const updated = await updateHotlistSourceApi(editTarget.value.id, {
      name: editForm.name.trim() || undefined,
      cron_expr: editForm.cron_expr.trim() || undefined,
      expected_domain: editForm.expected_domain.trim(),
    });
    const idx = allSources.value.findIndex((s) => s.id === updated.id);
    if (idx >= 0) allSources.value[idx] = updated;
    message.success('已保存');
    editModalOpen.value = false;
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    editSaving.value = false;
  }
}

// -------------------------------------------------------------- 新建（RSS）----
const createModalOpen = ref(false);
const createForm = reactive({ id: '', name: '', url: '', expected_domain: '', cron_expr: '*/30 * * * *' });
const createSaving = ref(false);

function openCreate() {
  createForm.id = '';
  createForm.name = '';
  createForm.url = '';
  createForm.expected_domain = '';
  createForm.cron_expr = '*/30 * * * *';
  createModalOpen.value = true;
}

async function submitCreate() {
  if (!createForm.id.trim() || !createForm.name.trim() || !createForm.url.trim()) {
    message.warning('请填写完整');
    return;
  }
  createSaving.value = true;
  try {
    const created = await createHotlistSourceApi({
      id: createForm.id.trim(),
      name: createForm.name.trim(),
      adapter: 'rss',
      adapter_params: { url: createForm.url.trim() },
      expected_domain: createForm.expected_domain.trim(),
      cron_expr: createForm.cron_expr.trim() || '*/30 * * * *',
    });
    allSources.value.push(created);
    message.success('已创建');
    createModalOpen.value = false;
  } catch (e: any) {
    message.error(`创建失败：${e.message}`);
  } finally {
    createSaving.value = false;
  }
}

async function removeSource(source: HotlistApi.Source) {
  Modal.confirm({
    title: `删除源「${source.name}」？`,
    content: '删除后该源已抓取的历史条目仍会保留，只是不再继续抓取。',
    okType: 'danger',
    async onOk() {
      try {
        await deleteHotlistSourceApi(source.id);
        allSources.value = allSources.value.filter((s) => s.id !== source.id);
        message.success('已删除');
      } catch (e: any) {
        message.error(`删除失败：${e.message}`);
      }
    },
  });
}

// -------------------------------------------------------------- OPML 导入 ----
const importModalOpen = ref(false);
const importFileText = ref('');
const importUrl = ref('');
const importGroupId = ref<number | undefined>(undefined);
const importSaving = ref(false);

function readOpmlFile(file: File) {
  const reader = new FileReader();
  reader.onload = () => {
    importFileText.value = String(reader.result || '');
  };
  reader.readAsText(file);
  return false;
}

async function submitImport() {
  if (!importFileText.value.trim() && !importUrl.value.trim()) {
    message.warning('请上传 .opml 文件或填写 OPML 的 URL');
    return;
  }
  importSaving.value = true;
  try {
    const res = await importSourcesOpmlApi({
      content: importFileText.value || undefined,
      opml_url: importUrl.value || undefined,
      group_id: importGroupId.value ?? null,
    });
    message.success(`导入完成：新增 ${res.created.length} 个、复用 ${res.reused.length} 个、跳过 ${res.skipped} 个`);
    importModalOpen.value = false;
    importFileText.value = '';
    importUrl.value = '';
    importGroupId.value = undefined;
    fetchSources();
  } catch (e: any) {
    message.error(`导入失败：${e.response?.data?.detail || e.message}`);
  } finally {
    importSaving.value = false;
  }
}

// -------------------------------------------------------------- 分组管理 ----
const groupManagerOpen = ref(false);

onMounted(async () => {
  await fetchSources();
  resumeBatchCrawl();
});
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-background-deep p-6 lg:p-8 select-none">
      <!-- 页头 Hero -->
      <div class="fade-up relative mb-8 shrink-0 overflow-hidden rounded-3xl border border-border bg-card p-6 shadow-sm">
        <div class="pointer-events-none absolute -right-12 -top-14 size-52 rounded-full bg-primary/12 blur-3xl"></div>
        <div class="pointer-events-none absolute -bottom-20 -left-14 size-60 rounded-full bg-success/10 blur-3xl"></div>
        <div class="relative flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div class="flex items-center gap-4">
            <div
              class="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-primary to-primary/50 text-primary-foreground shadow-lg shadow-primary/25"
            >
              <Rss class="size-5" />
            </div>
            <div>
              <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-primary">Source Management</p>
              <h1
                class="display-font mt-1 bg-gradient-to-r from-foreground to-foreground/60 bg-clip-text text-2xl font-black tracking-tight text-transparent"
              >
                源管理
              </h1>
              <p class="mt-1 text-xs text-muted-foreground">
                分组管理 / 批量开关 / OPML 批量导入；RSS 类源可在此新增，无需改代码
              </p>
            </div>
          </div>
          <div class="flex shrink-0 items-center gap-2">
            <button
              class="flex items-center gap-1 rounded-full border border-border bg-card px-3.5 py-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
              @click="importModalOpen = true"
            >
              <Upload class="h-3.5 w-3.5" />
              批量导入 OPML
            </button>
            <button
              class="flex items-center gap-1 rounded-full border border-border bg-card px-3.5 py-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
              @click="groupManagerOpen = true"
            >
              <Layers class="h-3.5 w-3.5" />
              分组管理
            </button>
            <button
              class="flex items-center gap-1.5 rounded-full bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground shadow-md shadow-primary/20 transition-all hover:bg-primary/90 hover:shadow-lg"
              @click="openCreate"
            >
              <Plus class="h-3.5 w-3.5" />
              新建 RSS 源
            </button>
          </div>
        </div>
      </div>

      <!-- 统计卡片 -->
      <div class="fade-up mb-6 grid shrink-0 grid-cols-2 gap-4 xl:grid-cols-4" style="animation-delay: 60ms">
        <div
          class="group relative overflow-hidden rounded-2xl border border-border bg-card p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-xl"
        >
          <div class="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-primary via-primary/70 to-primary/30"></div>
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-muted-foreground">源总数</span>
            <Rss class="size-4 text-primary/70 transition-transform duration-300 group-hover:scale-110" />
          </div>
          <div class="mt-3 text-3xl font-bold tracking-tight text-foreground">{{ allSources.length }}</div>
        </div>
        <div
          class="group relative overflow-hidden rounded-2xl border border-border bg-card p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-xl"
          style="animation-delay: 120ms"
        >
          <div class="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-success via-success/70 to-success/30"></div>
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-muted-foreground">启用源</span>
            <CheckCircle2 class="size-4 text-success/70 transition-transform duration-300 group-hover:scale-110" />
          </div>
          <div class="mt-3 text-3xl font-bold tracking-tight text-foreground">{{ enabledSourceCount }}</div>
        </div>
        <div
          class="group relative overflow-hidden rounded-2xl border border-border bg-card p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-xl"
          style="animation-delay: 180ms"
        >
          <div class="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-muted-foreground via-muted-foreground/50 to-muted-foreground/20"></div>
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-muted-foreground">分组数</span>
            <Layers class="size-4 text-muted-foreground/60 transition-transform duration-300 group-hover:scale-110" />
          </div>
          <div class="mt-3 text-3xl font-bold tracking-tight text-foreground">{{ groups.length }}</div>
        </div>
        <div
          class="group relative overflow-hidden rounded-2xl border border-border bg-card p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-xl"
          style="animation-delay: 240ms"
        >
          <div
            class="absolute inset-x-0 top-0 h-1"
            :class="failedSourceCount > 0 ? 'bg-gradient-to-r from-destructive via-destructive/70 to-destructive/30' : 'bg-gradient-to-r from-muted-foreground via-muted-foreground/50 to-muted-foreground/20'"
          ></div>
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-muted-foreground">失败源</span>
            <TriangleAlert
              class="size-4 transition-transform duration-300 group-hover:scale-110"
              :class="failedSourceCount > 0 ? 'text-destructive' : 'text-muted-foreground/50'"
            />
          </div>
          <div class="mt-3 text-3xl font-bold tracking-tight" :class="failedSourceCount > 0 ? 'text-destructive' : 'text-foreground'">
            {{ failedSourceCount }}
          </div>
        </div>
      </div>

      <!-- ===================== 分组卡片视图（默认） ===================== -->
      <div v-if="viewMode === 'groups'">
        <div class="fade-up mb-4 flex shrink-0 items-center justify-between" style="animation-delay: 300ms">
          <p class="text-xs text-muted-foreground">点击分组查看组内的源；不关心具体某条源时看这一层就够了</p>
          <button
            class="shrink-0 text-xs text-muted-foreground transition-colors hover:text-primary"
            @click="enterGroup('all')"
          >
            查看全部源列表（{{ allSources.length }}）→
          </button>
        </div>
        <div
          v-if="!loading && groupCards.length === 0"
          class="fade-up rounded-2xl border border-dashed border-border p-16 text-center text-sm text-muted-foreground"
          style="animation-delay: 360ms"
        >
          还没有分组，先在右上角「分组管理」里建一个
        </div>
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <div
            v-for="(card, idx) in groupCards"
            :key="String(card.key)"
            class="fade-up group cursor-pointer rounded-2xl border border-border bg-card p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:border-primary/40 hover:shadow-xl"
            :style="{ animationDelay: `${360 + idx * 50}ms` }"
            @click="enterGroup(card.key)"
          >
            <div class="mb-3 flex items-center gap-2.5">
              <span
                class="flex size-9 shrink-0 items-center justify-center rounded-xl text-white shadow-sm transition-transform duration-300 group-hover:scale-110"
                :style="{ backgroundColor: card.color }"
              >
                <Rss class="size-4" />
              </span>
              <span class="truncate text-sm font-semibold text-foreground">{{ card.name }}</span>
              <span class="ml-auto shrink-0 rounded-full bg-muted px-2.5 py-0.5 text-xs text-muted-foreground">
                {{ card.count }} 个源
              </span>
            </div>
            <div class="flex flex-wrap items-center gap-2 text-[11px]">
              <span class="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">
                启用 <b class="font-semibold text-foreground">{{ card.enabledCount }}</b>
              </span>
              <span v-if="card.ok" class="rounded-full bg-success/10 px-2 py-0.5 font-medium text-success">正常 {{ card.ok }}</span>
              <span v-if="card.failed" class="rounded-full bg-destructive/10 px-2 py-0.5 font-medium text-destructive">失败 {{ card.failed }}</span>
              <span v-if="card.pending" class="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">待抓取 {{ card.pending }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- ===================== 分组筛选 Tab + 源表格 ===================== -->
      <template v-else>
        <div class="fade-up mb-4 flex shrink-0 flex-wrap items-center gap-2" style="animation-delay: 300ms">
          <button
            class="flex items-center gap-1 rounded-full border border-border px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
            @click="backToGroups"
          >
            <ArrowLeft class="h-3.5 w-3.5" />
            分组
          </button>
          <button
            v-for="tab in filterTabs"
            :key="String(tab.key)"
            class="rounded-full border px-3 py-1.5 text-xs transition-colors"
            :class="
              activeFilter === tab.key
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border text-muted-foreground hover:text-foreground'
            "
            @click="activeFilter = tab.key"
          >
            {{ tab.label }}
          </button>

          <div class="ml-auto flex items-center gap-2">
            <span v-if="batchCrawlHint" class="text-[11px] text-muted-foreground">{{ batchCrawlHint }}</span>
            <button
              :disabled="batchCrawling || filteredSources.length === 0"
              class="flex items-center gap-1 rounded-full border border-border px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary hover:text-primary disabled:opacity-50"
              title="立即抓取当前筛选下所有启用中的源，完成后自动刷新状态"
              @click="crawlMany(filteredSources.filter((s) => s.enabled).map((s) => s.id), '当前分组')"
            >
              <RefreshCw class="h-3.5 w-3.5" :class="batchCrawling ? 'animate-spin' : ''" />
              {{ batchCrawling ? '抓取中…' : '抓取本组全部' }}
            </button>
          </div>
        </div>

        <!-- 批量操作条 -->
        <div
          v-if="selectedKeys.length > 0"
          class="fade-up mb-4 flex shrink-0 items-center gap-3 rounded-2xl border border-primary/30 bg-primary/10 px-4 py-3 text-xs"
        >
          <span class="font-semibold text-primary">已选 {{ selectedKeys.length }} 个源</span>
          <button
            class="rounded-full border border-border px-3 py-1 text-[11px] transition-colors hover:text-primary"
            @click="batchMoveOpen = true"
          >
            <FolderInput class="mr-1 inline size-3" />
            移动到分组
          </button>
          <button
            :disabled="batchCrawling"
            class="rounded-full border border-border px-3 py-1 text-[11px] transition-colors hover:text-primary disabled:opacity-50"
            @click="crawlMany(selectedKeys, '选中的源')"
          >
            <RefreshCw class="mr-1 inline size-3" :class="batchCrawling ? 'animate-spin' : ''" />
            立即抓取
          </button>
          <button
            class="rounded-full border border-border px-3 py-1 text-[11px] transition-colors hover:text-success"
            @click="batchSetEnabled(true)"
          >
            批量启用
          </button>
          <button
            class="rounded-full border border-border px-3 py-1 text-[11px] transition-colors hover:text-warning"
            @click="batchSetEnabled(false)"
          >
            批量停用
          </button>
          <button
            class="ml-auto text-[11px] text-muted-foreground transition-colors hover:text-foreground"
            @click="selectedKeys = []"
          >
            取消选择
          </button>
        </div>

        <div class="fade-up shrink-0 overflow-hidden rounded-2xl border border-border bg-card shadow-sm" style="animation-delay: 360ms">
          <div
            v-if="!loading && filteredSources.length === 0"
            class="flex flex-col items-center justify-center gap-3 p-16 text-center"
          >
            <div class="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
              <Rss class="size-5" />
            </div>
            <p class="text-sm font-medium text-foreground">暂无源</p>
          </div>
          <div v-else class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="border-b border-border bg-muted/50 text-[11px] font-medium text-muted-foreground">
                <tr>
                  <th class="w-10 px-2 py-3">
                    <input
                      type="checkbox"
                      class="accent-primary"
                      :checked="filteredSources.length > 0 && filteredSources.every((s) => selectedKeys.includes(s.id))"
                      @change="(e) => {
                        const checked = (e.target as HTMLInputElement).checked;
                        selectedKeys = checked ? filteredSources.map((s) => s.id) : [];
                      }"
                    />
                  </th>
                  <th class="px-4 py-3">源</th>
                  <th class="px-4 py-3">分组</th>
                  <th class="px-4 py-3">类型</th>
                  <th class="px-4 py-3">抓取频率</th>
                  <th class="px-4 py-3">状态</th>
                  <th class="px-4 py-3">累计条数</th>
                  <th class="px-4 py-3">启用</th>
                  <th class="px-4 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-border">
                <tr v-for="source in filteredSources" :key="source.id" class="transition-colors hover:bg-accent/60">
                  <td class="px-2 py-3">
                    <input type="checkbox" class="accent-primary" :value="source.id" v-model="selectedKeys" />
                  </td>
                  <td class="px-4 py-3">
                    <div class="font-medium text-foreground">{{ source.name || source.id }}</div>
                    <div class="text-[11px] text-muted-foreground">{{ source.id }} · {{ source.adapter }}</div>
                  </td>
                  <td class="px-4 py-3">
                    <span
                      class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px]"
                      :style="{
                        backgroundColor: source.group_id ? `${groupById.get(source.group_id)?.color || '#8c8c8c'}22` : 'transparent',
                        color: source.group_id ? groupById.get(source.group_id)?.color || '#8c8c8c' : 'hsl(var(--muted-foreground))',
                        border: source.group_id ? `1px solid ${groupById.get(source.group_id)?.color || '#8c8c8c'}55` : '1px dashed hsl(var(--border))',
                      }"
                    >
                      {{ groupLabel(source.group_id) }}
                    </span>
                  </td>
                  <td class="px-4 py-3 text-muted-foreground">{{ KIND_LABEL[source.source_kind] || source.source_kind }}</td>
                  <td class="px-4 py-3 font-mono text-muted-foreground">{{ source.cron_expr }}</td>
                  <td class="px-4 py-3">
                    <Tooltip :title="source.last_error || ''">
                      <span class="inline-flex items-center gap-1.5" :class="statusInfo(source).text">
                        <span class="h-1.5 w-1.5 rounded-full" :class="statusInfo(source).dot"></span>
                        {{ statusInfo(source).label }}
                      </span>
                    </Tooltip>
                  </td>
                  <td class="px-4 py-3 font-mono text-muted-foreground">{{ source.total_fetched }}</td>
                  <td class="px-4 py-3">
                    <Switch size="small" :checked="source.enabled" @change="(v) => toggleEnabled(source, Boolean(v))" />
                  </td>
                  <td class="px-4 py-3 text-right">
                    <div class="flex items-center justify-end gap-3">
                      <button
                        :disabled="crawlingIds.has(source.id) || !source.enabled"
                        class="inline-flex items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-primary disabled:opacity-40"
                        :title="source.enabled ? '立即抓取这个源，看它现在到底通不通' : '源已停用'"
                        @click="crawlOne(source)"
                      >
                        <RefreshCw class="size-3" :class="crawlingIds.has(source.id) ? 'animate-spin' : ''" />
                        {{ crawlingIds.has(source.id) ? '抓取中' : '抓取' }}
                      </button>
                      <button class="text-[11px] text-muted-foreground transition-colors hover:text-primary" @click="openEdit(source)">
                        编辑
                      </button>
                      <button class="text-[11px] text-muted-foreground transition-colors hover:text-destructive" @click="removeSource(source)">
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </div>

    <!-- 移动到分组弹窗 -->
    <Modal v-model:open="batchMoveOpen" title="移动到分组" :footer="null" width="400px">
      <Form layout="vertical">
        <FormItem label="目标分组（选择「未分组」= 移出分组）">
          <Select
            v-model:value="batchMoveGroup"
            allow-clear
            placeholder="未分组"
            :options="groups.map((g) => ({ value: g.id, label: `${g.name}（${g.source_count}）` }))"
          />
        </FormItem>
        <p class="mb-3 text-xs text-muted-foreground">将移动 {{ selectedKeys.length }} 个源</p>
        <div class="flex justify-end gap-2">
          <button class="rounded-full border border-border px-4 py-1.5 text-xs" @click="batchMoveOpen = false">取消</button>
          <button
            :disabled="batchMoving"
            class="rounded-full bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
            @click="submitBatchMove"
          >
            移动
          </button>
        </div>
      </Form>
    </Modal>

    <Modal v-model:open="editModalOpen" title="编辑源" :footer="null" width="440px">
      <Form layout="vertical">
        <FormItem label="显示名">
          <Input v-model:value="editForm.name" placeholder="源显示名" />
        </FormItem>
        <FormItem label="cron 表达式">
          <Input v-model:value="editForm.cron_expr" placeholder="*/30 * * * *" />
        </FormItem>
        <FormItem label="期望域名（域名安全校验，留空跳过校验）">
          <Input v-model:value="editForm.expected_domain" placeholder="例如 weibo.com" />
        </FormItem>
        <div class="flex justify-end gap-2">
          <button class="rounded-full border border-border px-4 py-1.5 text-xs" @click="editModalOpen = false">取消</button>
          <button
            :disabled="editSaving"
            class="rounded-full bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
            @click="submitEdit"
          >
            保存
          </button>
        </div>
      </Form>
    </Modal>

    <Modal v-model:open="createModalOpen" title="新建 RSS 源" :footer="null" width="440px">
      <Form layout="vertical">
        <FormItem label="源 id（唯一，英文/数字/短横线）">
          <Input v-model:value="createForm.id" placeholder="例如 my-blog" />
        </FormItem>
        <FormItem label="显示名">
          <Input v-model:value="createForm.name" placeholder="源显示名" />
        </FormItem>
        <FormItem label="Feed 地址">
          <Input v-model:value="createForm.url" placeholder="https://example.com/feed.xml" />
        </FormItem>
        <FormItem label="期望域名（可选，留空跳过域名安全校验）">
          <Input v-model:value="createForm.expected_domain" placeholder="例如 example.com" />
        </FormItem>
        <FormItem label="cron 表达式">
          <Input v-model:value="createForm.cron_expr" />
        </FormItem>
        <div class="flex justify-end gap-2">
          <button class="rounded-full border border-border px-4 py-1.5 text-xs" @click="createModalOpen = false">取消</button>
          <button
            :disabled="createSaving"
            class="rounded-full bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
            @click="submitCreate"
          >
            创建
          </button>
        </div>
      </Form>
    </Modal>

    <!-- OPML 批量导入 -->
    <Modal v-model:open="importModalOpen" title="批量导入 OPML 到分组" :footer="null" width="480px">
      <Form layout="vertical">
        <FormItem label="上传 .opml 文件">
          <input type="file" accept=".opml,.xml" class="text-xs" @change="(e) => readOpmlFile((e.target as HTMLInputElement).files?.[0] as File)" />
        </FormItem>
        <FormItem label="或填写 OPML 的 URL">
          <Input v-model:value="importUrl" placeholder="https://example.com/feeds.opml" />
        </FormItem>
        <FormItem label="归入分组（可选）">
          <Select
            v-model:value="importGroupId"
            allow-clear
            placeholder="不归组"
            :options="groups.map((g) => ({ value: g.id, label: `${g.name}（${g.source_count}）` }))"
          />
        </FormItem>
        <div class="flex justify-end gap-2">
          <button class="rounded-full border border-border px-4 py-1.5 text-xs" @click="importModalOpen = false">取消</button>
          <button
            :disabled="importSaving"
            class="rounded-full bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
            @click="submitImport"
          >
            导入
          </button>
        </div>
      </Form>
    </Modal>

    <GroupManagerModal v-model:open="groupManagerOpen" @changed="fetchSources" />
  </Page>
</template>

<style scoped>
.display-font {
  font-family:
    'SF Pro Display', 'PingFang SC', 'Hiragino Sans GB', 'Noto Sans SC',
    'Microsoft YaHei', system-ui, sans-serif;
}
.fade-up {
  animation: fade-up 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
}
@keyframes fade-up {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
