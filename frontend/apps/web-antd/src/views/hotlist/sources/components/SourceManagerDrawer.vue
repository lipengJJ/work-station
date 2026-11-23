<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { computed, onUnmounted, reactive, ref, watch } from 'vue';

import {
  Drawer,
  Form,
  FormItem,
  Input,
  InputNumber,
  message,
  Modal,
  Select,
  Switch,
  Tooltip,
} from 'ant-design-vue';
import { FolderInput, Layers, RefreshCw, Rss } from 'lucide-vue-next';

import GroupManagerModal from './GroupManagerModal.vue';

import {
  batchSourcesApi,
  crawlOneSourceApi,
  crawlSourcesApi,
  deleteHotlistSourceApi,
  getCrawlStatusApi,
  listHotlistSourcesApi,
  listSourceGroupsApi,
  updateHotlistSourceApi,
} from '#/api/core/hotlist';

// 单源管理：启停 / 编辑 / 删除 / 单独&批量抓取 / 批量移动分组。这些操作在
// 「热点聚合 → 榜单」页的分组胶囊 + 新建/导入/分组管理三个入口之外，是原
// 独立源管理页仅剩的、没有替代入口的部分，抽成抽屉从榜单页复用，不用单独占一个路由。
const open = defineModel<boolean>('open', { default: false });
const props = defineProps<{ initialGroup?: string }>();

const emit = defineEmits<{ changed: [] }>();

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
const groupManagerOpen = ref(false);

function applyInitialGroup() {
  const group = props.initialGroup || '';
  if (!group) activeFilter.value = 'all';
  else if (group === 'ungrouped') activeFilter.value = 'ungrouped';
  else {
    const groupId = Number(group);
    activeFilter.value = Number.isFinite(groupId) ? groupId : 'all';
  }
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

// 每次打开都拉一遍最新数据；榜单页那边分组/源有变化时数据也不会过期太久
watch(open, (v) => {
  if (v) {
    applyInitialGroup();
    fetchSources();
    if (!batchCrawling.value) resumeBatchCrawl();
  }
});

async function handleGroupsChanged() {
  await fetchSources();
  if (
    typeof activeFilter.value === 'number' &&
    !groups.value.some((group) => group.id === activeFilter.value)
  ) {
    activeFilter.value = 'all';
  }
  emit('changed');
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

// 批量抓取的状态要能在关闭/重开抽屉后恢复：把 job_id + 目标源 + 开跑时间存进
// sessionStorage（F5 刷新不清），重开时读回来继续轮询后端进度。
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
    emit('changed');
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
 * （或超过 3 分钟兜底停止）。进度存在后端 + sessionStorage，重开抽屉也能恢复。
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
      emit('changed');
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
      message.info('抓取仍在进行，可稍后重开管理面板查看结果');
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

/** 重开抽屉后恢复「正在抓取」的显示：sessionStorage 里还有未完成的批次就继续轮询 */
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
    emit('changed');
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
    await fetchSources();
    emit('changed');
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
    await fetchSources();
    emit('changed');
  } catch (e: any) {
    message.error(`移动失败：${e.response?.data?.detail || e.message}`);
  } finally {
    batchMoving.value = false;
  }
}

// -------------------------------------------------------------- 编辑 ----
const editModalOpen = ref(false);
const editTarget = ref<HotlistApi.Source | null>(null);
const editForm = reactive({ name: '', interval_hours: 0.5, expected_domain: '' });
const editSaving = ref(false);

function openEdit(source: HotlistApi.Source) {
  editTarget.value = source;
  editForm.name = source.name;
  editForm.interval_hours = source.interval_hours;
  editForm.expected_domain = source.expected_domain;
  editModalOpen.value = true;
}

async function submitEdit() {
  if (!editTarget.value) return;
  editSaving.value = true;
  try {
    const updated = await updateHotlistSourceApi(editTarget.value.id, {
      name: editForm.name.trim() || undefined,
      interval_hours: editForm.interval_hours || undefined,
      expected_domain: editForm.expected_domain.trim(),
    });
    const idx = allSources.value.findIndex((s) => s.id === updated.id);
    if (idx >= 0) allSources.value[idx] = updated;
    message.success('已保存');
    editModalOpen.value = false;
    emit('changed');
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    editSaving.value = false;
  }
}

async function removeSource(source: HotlistApi.Source) {
  Modal.confirm({
    title: `删除源「${source.name}」？`,
    content:
      '该源已抓取的全部新闻数据（含向量索引）会一并永久删除，且不可恢复；仍被任意主题订阅关联的源不允许删除，需先在相关主题里移除。',
    okText: '永久删除',
    okType: 'danger',
    async onOk() {
      try {
        await deleteHotlistSourceApi(source.id);
        allSources.value = allSources.value.filter((s) => s.id !== source.id);
        message.success('已删除');
        emit('changed');
      } catch (e: any) {
        message.error(`删除失败：${e.response?.data?.detail || e.message}`);
      }
    },
  });
}
</script>

<template>
  <Drawer v-model:open="open" title="分组与数据源管理" width="min(1040px, 96vw)" :body-style="{ paddingTop: '12px' }">
    <div class="flex flex-wrap items-center gap-2">
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
        <button
          class="flex items-center gap-1 rounded-full border border-border px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary hover:text-primary"
          @click="groupManagerOpen = true"
        >
          <Layers class="size-3.5" />
          新建/编辑分组
        </button>
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
      class="mt-3 flex items-center gap-3 rounded-2xl border border-primary/30 bg-primary/10 px-4 py-3 text-xs"
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

    <div class="mt-3 overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
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
              <td class="px-4 py-3 font-mono text-muted-foreground">每 {{ source.interval_hours }} 小时</td>
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
        <FormItem label="抓取间隔（小时）">
          <InputNumber v-model:value="editForm.interval_hours" :min="0.1" :step="0.5" style="width: 100%" />
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

    <GroupManagerModal v-model:open="groupManagerOpen" @changed="handleGroupsChanged" />
  </Drawer>
</template>
