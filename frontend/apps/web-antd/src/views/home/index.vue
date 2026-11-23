<script lang="ts" setup>
import type { WorkbenchApi } from '#/api/core/workbench';

import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';

import { Empty } from 'ant-design-vue';
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  ClipboardList,
  Database,
  HardDrive,
  MessageSquare,
  PlusCircle,
  Radar,
  Search,
} from 'lucide-vue-next';

import { getHomeApi, getHomeStorageApi } from '#/api/core/workbench';

// ---------------------------------------------------------------- 常量 ----

const KIND_META: Record<string, { label: string; route: string; icon: unknown }> = {
  collect: { label: '采集任务', route: '/xhs/notes', icon: Search },
  backfill: { label: '补抓评论', route: '/xhs/notes', icon: MessageSquare },
  tracking: { label: '追踪扫描', route: '/xhs/tracking', icon: Radar },
};

const PHASE_TEXT: Record<string, string> = {
  queued: '等待开始',
  searching: '搜索候选笔记',
  fetching_notes: '数据爬取',
  structuring: '数据清洗',
  downloading_media: '素材下载',
  fetching_comments: '抓取评论',
  exporting: '导出文件',
  fetching_missing_comments: '补抓评论中',
  scanning: '扫描中',
  done: '已完成',
  failed: '失败',
};

const STATUS_LABEL: Record<string, string> = {
  pending: '排队中',
  running: '运行中',
  success: '成功',
  failed: '失败',
};

const TASK_STATUS_META: Record<string, { label: string; cls: string }> = {
  pending: { label: '排队中', cls: 'text-muted' },
  running: { label: '运行中', cls: 'text-warning' },
  success: { label: '成功', cls: 'text-success' },
  failed: { label: '失败', cls: 'text-destructive' },
};

// ---------------------------------------------------------------- 数据 ----

const data = ref<WorkbenchApi.HomeResponse>();
const storage = ref<WorkbenchApi.StorageStats>();
const loading = ref(true);
const router = useRouter();

const today = new Date().toLocaleDateString('zh-CN', {
  month: 'long',
  day: 'numeric',
  weekday: 'long',
});

function formatBytes(n: number): string {
  if (!n) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatAxis(n: number): string {
  if (n >= 1024 * 1024 * 1024) return `${(n / 1024 / 1024 / 1024).toFixed(1)}GB`;
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(0)}MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)}KB`;
  return `${Math.round(n)}B`;
}

async function loadStorage() {
  try {
    storage.value = await getHomeStorageApi();
  } catch {
    // 静默
  }
}

async function loadHome() {
  try {
    data.value = await getHomeApi();
  } catch {
    // 轮询失败静默
  } finally {
    loading.value = false;
  }
}

const summary = computed(() => data.value?.summary);
const runningTasks = computed(() => data.value?.running_tasks ?? []);
const hasRunning = computed(() => runningTasks.value.length > 0);
const trend = computed(() => data.value?.trend ?? []);
const dist = computed(() => data.value?.status_distribution ?? {});
const recentTasks = computed(() => data.value?.recent_tasks ?? []);

const totalBytes = computed(
  () => (storage.value?.db_size ?? 0) + (storage.value?.storage_size ?? 0),
);

function taskProgress(t: WorkbenchApi.RunningTask): number {
  if (!t.progress_total) return 0;
  return Math.min(100, Math.round(((t.progress_current ?? 0) / t.progress_total) * 100));
}

function phaseText(t: WorkbenchApi.RunningTask): string {
  return PHASE_TEXT[t.phase ?? ''] ?? t.phase ?? '';
}

function taskTime(iso: null | string): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('zh-CN', { hour12: false }).slice(5, 16);
}

// ---------------------------------------------------------- 任务趋势柱状图 ----

const TREND_W = 560;
const TREND_H = 200;
const TREND_PAD = { top: 14, right: 12, bottom: 24, left: 32 };

const trendChart = computed(() => {
  const points = trend.value;
  const innerW = TREND_W - TREND_PAD.left - TREND_PAD.right;
  const innerH = TREND_H - TREND_PAD.top - TREND_PAD.bottom;
  const max = Math.max(1, ...points.flatMap((p) => [p.created, p.finished]));
  const step = points.length > 1 ? innerW / points.length : innerW;
  const barW = Math.min(30, step * 0.32);
  const gap = 4;
  const bars = points.map((p, i) => {
    const cx = TREND_PAD.left + step * i + step / 2;
    const hCreated = (p.created / max) * innerH;
    const hFinished = (p.finished / max) * innerH;
    return {
      x1: cx - barW - gap / 2,
      y1: TREND_PAD.top + innerH - hCreated,
      h1: hCreated,
      x2: cx + gap / 2,
      y2: TREND_PAD.top + innerH - hFinished,
      h2: hFinished,
      w: barW,
    };
  });
  const labels = points.map((p) => {
    const d = new Date(`${p.date}T00:00:00`);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  });
  const ticks = [0, 0.5, 1].map((r) => ({
    y: TREND_PAD.top + innerH - r * innerH,
    label: Math.round(max * r),
  }));
  return { bars, labels, ticks, max };
});

// ---------------------------------------------------------- 存储面积折线图 ----

const ST_W = 560;
const ST_H = 200;
const ST_PAD = { top: 12, right: 12, bottom: 22, left: 44 };

const storageChart = computed(() => {
  const points = storage.value?.trend ?? [];
  const innerW = ST_W - ST_PAD.left - ST_PAD.right;
  const innerH = ST_H - ST_PAD.top - ST_PAD.bottom;
  const max = Math.max(1, ...points.flatMap((p) => [p.db, p.storage]));
  const step = points.length > 1 ? innerW / (points.length - 1) : innerW;
  const toXY = (v: number, i: number) => ({
    x: ST_PAD.left + step * i,
    y: ST_PAD.top + innerH - (v / max) * innerH,
  });
  const line = (key: 'db' | 'storage') =>
    points
      .map((p, i) => {
        const { x, y } = toXY(p[key], i);
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  const area = (key: 'db' | 'storage') => {
    if (points.length < 2) return '';
    const first = toXY(points[0]![key], 0);
    const last = toXY(points[points.length - 1]![key], points.length - 1);
    const baseY = ST_PAD.top + innerH;
    return `${line(key)} L${last.x.toFixed(1)},${baseY} L${first.x.toFixed(1)},${baseY} Z`;
  };
  const ticks = [0, 0.5, 1].map((r) => ({
    y: ST_PAD.top + innerH - r * innerH,
    label: formatAxis(max * r),
  }));
  const labels: { x: number; t: string }[] = [];
  if (points.length) {
    const idxs = [0, Math.floor((points.length - 1) / 2), points.length - 1];
    [...new Set(idxs)].forEach((i) => {
      const pt = points[i]!;
      labels.push({ x: toXY(pt.db, i).x, t: pt.t });
    });
  }
  return {
    lineDb: line('db'),
    areaDb: area('db'),
    lineStorage: line('storage'),
    areaStorage: area('storage'),
    ticks,
    labels,
    count: points.length,
  };
});

// ---------------------------------------------------------- 成功率环形 ----

const RING_R = 46;
const RING_C = 2 * Math.PI * RING_R;
const successRate = computed(() => {
  const r = summary.value?.success_rate ?? 0;
  return Math.max(0, Math.min(100, r));
});
const successDone = computed(
  () => (summary.value?.success_count ?? 0) + (summary.value?.failed_count ?? 0),
);

// ---------------------------------------------------------------- 时钟 ----

let timer: ReturnType<typeof setInterval> | undefined;
let storageTimer: ReturnType<typeof setInterval> | undefined;

onMounted(() => {
  loadHome();
  timer = setInterval(loadHome, 5000);
  loadStorage();
  storageTimer = setInterval(loadStorage, 30000);
});

onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
  if (storageTimer) clearInterval(storageTimer);
});
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-col gap-3 overflow-y-auto p-4 lg:p-5 select-none">
      <!-- ==================== 页头：紧凑一行 ==================== -->
      <div class="flex items-center justify-between gap-3 px-1">
        <div class="min-w-0">
          <div class="text-base font-bold text-foreground">总览</div>
          <div class="mt-0.5 truncate text-xs text-muted-foreground">{{ today }} · 任务中心状态一览</div>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <span class="flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-xs text-muted-foreground">
            <i class="h-1.5 w-1.5 rounded-full bg-primary"></i>
            运行中 {{ summary?.running_count ?? 0 }}
          </span>
          <span class="hidden items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-xs text-muted-foreground sm:flex">
            <HardDrive class="size-3.5 text-primary" />
            {{ formatBytes(totalBytes) }}
          </span>
        </div>
      </div>

      <!-- ==================== KPI 条 ==================== -->
      <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div
          v-for="kpi in [
            { label: '任务总数', value: summary?.total_tasks ?? 0, icon: Database, sub: '全部模块累计' },
            { label: '运行中', value: summary?.running_count ?? 0, icon: Activity, sub: '采集 / 补抓 / 追踪' },
            { label: '今日新增', value: summary?.today_new ?? 0, icon: PlusCircle, sub: '今天创建的任务' },
            { label: '今日完成', value: summary?.today_done ?? 0, icon: CheckCircle2, sub: '今天跑完的任务' },
          ] as const"
          :key="kpi.label"
          class="rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40"
        >
          <div class="flex items-center justify-between gap-2">
            <span class="truncate text-xs text-muted-foreground">{{ kpi.label }}</span>
            <span class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <component :is="kpi.icon" class="size-4" />
            </span>
          </div>
          <div class="mt-2.5 text-2xl font-bold tabular-nums text-foreground">{{ kpi.value }}</div>
          <div class="mt-0.5 truncate text-[11px] text-muted-foreground">{{ kpi.sub }}</div>
        </div>
      </div>

      <!-- ==================== 图表区 ==================== -->
      <div class="grid gap-3 lg:grid-cols-2">
        <!-- 任务趋势 -->
        <div class="rounded-xl border border-border bg-card p-4">
          <div class="mb-3 flex items-center justify-between">
            <span class="text-sm font-semibold text-foreground">任务趋势</span>
            <span class="flex gap-3 text-[11px] text-muted-foreground">
              <span class="flex items-center gap-1.5"><i class="h-2 w-2 rounded-full bg-primary"></i>创建</span>
              <span class="flex items-center gap-1.5"><i class="h-2 w-2 rounded-full bg-success"></i>完成</span>
            </span>
          </div>
          <svg :viewBox="`0 0 ${TREND_W} ${TREND_H}`" class="h-auto w-full">
            <template v-for="tick in trendChart.ticks" :key="tick.y">
              <line :x1="TREND_PAD.left" :x2="TREND_W - TREND_PAD.right" :y1="tick.y" :y2="tick.y" stroke="hsl(var(--border))" stroke-width="0.7" stroke-dasharray="3 4" />
              <text :x="TREND_PAD.left - 6" :y="tick.y + 3" text-anchor="end" fill="hsl(var(--muted-foreground))" style="font-size: 10px">{{ tick.label }}</text>
            </template>
            <template v-if="trend.length">
              <g v-for="(b, i) in trendChart.bars" :key="i">
                <rect :x="b.x1" :y="b.y1" :width="b.w" :height="Math.max(b.h1, 2)" rx="3" fill="hsl(var(--primary))" opacity="0.9" />
                <rect :x="b.x2" :y="b.y2" :width="b.w" :height="Math.max(b.h2, 2)" rx="3" fill="hsl(var(--success))" opacity="0.85" />
              </g>
              <g v-for="(label, i) in trendChart.labels" :key="label">
                <text
                  :x="TREND_PAD.left + (trend.length > 1 ? ((TREND_W - TREND_PAD.left - TREND_PAD.right) / trend.length) * i + (TREND_W - TREND_PAD.left - TREND_PAD.right) / trend.length / 2 : TREND_W / 2)"
                  :y="TREND_H - 6"
                  text-anchor="middle"
                  fill="hsl(var(--muted-foreground))"
                  style="font-size: 10px"
                >
                  {{ label }}
                </text>
              </g>
            </template>
            <text v-if="!trend.length" :x="TREND_W / 2" :y="TREND_H / 2" text-anchor="middle" fill="hsl(var(--muted-foreground))" style="font-size: 12px">
              暂无任务数据
            </text>
          </svg>
        </div>

        <!-- 存储使用 -->
        <div class="rounded-xl border border-border bg-card p-4">
          <div class="mb-3 flex items-center justify-between">
            <span class="text-sm font-semibold text-foreground">存储使用</span>
            <span class="flex gap-3 text-[11px] text-muted-foreground">
              <span class="flex items-center gap-1.5"><i class="h-2 w-2 rounded-full bg-primary"></i>数据库</span>
              <span class="flex items-center gap-1.5"><i class="h-2 w-2 rounded-full bg-secondary-foreground/70"></i>素材</span>
            </span>
          </div>
          <svg :viewBox="`0 0 ${ST_W} ${ST_H}`" class="h-auto w-full">
            <defs>
              <linearGradient id="home-grad-db" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="hsl(var(--primary))" stop-opacity="0.22" />
                <stop offset="100%" stop-color="hsl(var(--primary))" stop-opacity="0" />
              </linearGradient>
              <linearGradient id="home-grad-st" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="hsl(var(--secondary-foreground))" stop-opacity="0.18" />
                <stop offset="100%" stop-color="hsl(var(--secondary-foreground))" stop-opacity="0" />
              </linearGradient>
            </defs>
            <template v-for="tick in storageChart.ticks" :key="tick.y">
              <line :x1="ST_PAD.left" :x2="ST_W - ST_PAD.right" :y1="tick.y" :y2="tick.y" stroke="hsl(var(--border))" stroke-width="0.7" stroke-dasharray="3 4" />
              <text :x="ST_PAD.left - 6" :y="tick.y + 3" text-anchor="end" fill="hsl(var(--muted-foreground))" style="font-size: 10px">{{ tick.label }}</text>
            </template>
            <template v-if="storageChart.count > 1">
              <path :d="storageChart.areaStorage" fill="url(#home-grad-st)" />
              <path :d="storageChart.areaDb" fill="url(#home-grad-db)" />
              <path :d="storageChart.lineStorage" fill="none" stroke="hsl(var(--secondary-foreground))" stroke-width="1.8" opacity="0.55" />
              <path :d="storageChart.lineDb" fill="none" stroke="hsl(var(--primary))" stroke-width="1.8" opacity="0.95" />
            </template>
            <text v-if="!storageChart.count" :x="ST_W / 2" :y="ST_H / 2" text-anchor="middle" fill="hsl(var(--muted-foreground))" style="font-size: 12px">
              正在采样中，每 5 分钟记录一个点
            </text>
            <g v-for="l in storageChart.labels" :key="l.x">
              <text :x="l.x" :y="ST_H - 6" text-anchor="middle" fill="hsl(var(--muted-foreground))" style="font-size: 10px">{{ l.t }}</text>
            </g>
          </svg>
          <div class="mt-3 flex justify-between border-t pt-2.5 text-[11px] text-muted-foreground" style="border-color: hsl(var(--border))">
            <span>笔记 {{ storage?.note_count ?? 0 }}</span>
            <span>评论 {{ storage?.comment_count ?? 0 }}</span>
            <span>任务 {{ storage?.task_count ?? 0 }}</span>
            <span>结构化 {{ storage?.structured_count ?? 0 }}</span>
            <span>报告 {{ storage?.report_count ?? 0 }}</span>
          </div>
        </div>
      </div>

      <!-- ==================== 底部三栏 ==================== -->
      <div class="grid gap-3 lg:grid-cols-3">
        <!-- 成功率 -->
        <div class="rounded-xl border border-border bg-card p-4">
          <div class="mb-3 text-sm font-semibold text-foreground">成功率</div>
          <div class="flex items-center gap-4">
            <svg viewBox="0 0 120 120" class="h-[104px] w-[104px] shrink-0">
              <circle cx="60" cy="60" r="52" fill="none" stroke="hsl(var(--muted))" stroke-width="4" />
              <circle
                cx="60"
                cy="60"
                :r="RING_R"
                fill="none"
                stroke="hsl(var(--primary))"
                stroke-width="12"
                :stroke-dasharray="`${(successRate / 100) * RING_C} ${RING_C}`"
                stroke-linecap="round"
                transform="rotate(-90 60 60)"
              />
              <text x="60" y="63" text-anchor="middle" fill="hsl(var(--foreground))" style="font-size: 21px; font-weight: 800">{{ successRate }}%</text>
              <text x="60" y="79" text-anchor="middle" fill="hsl(var(--muted-foreground))" style="font-size: 9px">成功率</text>
            </svg>
            <div class="min-w-0 flex-1">
              <div class="mb-2 flex items-center justify-between text-[11px] text-muted-foreground">
                <span>成功 {{ summary?.success_count ?? 0 }}</span>
                <span>完成 {{ successDone }}</span>
              </div>
              <div class="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div class="h-full rounded-full bg-primary" :style="{ width: `${successRate}%` }"></div>
              </div>
              <div class="mt-3 flex flex-wrap gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
                <span v-for="(v, k) in dist" :key="k" class="rounded-md bg-muted/60 px-1.5 py-0.5">
                  {{ STATUS_LABEL[k] ?? k }} {{ v }}
                </span>
                <span v-if="!Object.keys(dist).length">暂无统计</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 运行中任务 -->
        <div class="flex min-h-0 flex-col rounded-xl border border-border bg-card p-4">
          <div class="mb-2 flex items-center justify-between">
            <span class="text-sm font-semibold text-foreground">运行中任务</span>
            <span class="text-[11px] text-muted-foreground">点击跳转详情</span>
          </div>
          <Empty v-if="!loading && !hasRunning" :image="Empty.PRESENTED_IMAGE_SIMPLE" description="暂无运行中的任务" />
          <div v-else class="flex max-h-[260px] flex-col gap-1.5 overflow-y-auto pr-0.5">
            <div
              v-for="t in runningTasks"
              :key="`${t.kind}-${t.id}`"
              class="flex cursor-pointer items-start gap-2.5 rounded-lg p-2 transition-colors hover:bg-muted/50"
              @click="router.push(KIND_META[t.kind]?.route ?? '/')"
            >
              <div class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <component :is="KIND_META[t.kind]?.icon" class="size-4" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center justify-between gap-2">
                  <div class="truncate text-[13px] font-semibold text-foreground">{{ t.title }}</div>
                  <span class="flex shrink-0 items-center gap-1.5 text-[11px] text-muted-foreground">
                    <i
                      class="h-1.5 w-1.5 rounded-full home-dot-running"
                      :style="{ background: t.status === 'running' ? 'hsl(var(--primary))' : 'hsl(var(--muted-foreground))' }"
                    ></i>
                    {{ t.status === 'pending' ? '排队中' : '进行中' }}
                  </span>
                </div>
                <div class="truncate text-xs text-muted-foreground">{{ phaseText(t) }}</div>
                <div class="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-muted">
                  <div class="h-full rounded-full bg-primary" :style="{ width: `${taskProgress(t)}%` }"></div>
                </div>
                <div class="mt-1 text-[11px] text-muted-foreground">
                  <span v-if="t.started_at">{{ new Date(t.started_at).toLocaleTimeString() }} 开始</span>
                  <span class="ml-2">{{ t.progress_current ?? 0 }}/{{ t.progress_total ?? 0 }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 最近任务 -->
        <div class="flex min-h-0 flex-col rounded-xl border border-border bg-card p-4">
          <div class="mb-2 flex items-center justify-between">
            <span class="text-sm font-semibold text-foreground">最近任务</span>
            <button
              class="flex items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-primary"
              @click="router.push('/system/task-center')"
            >
              全部
              <ArrowRight class="size-3" />
            </button>
          </div>
          <Empty v-if="!loading && !recentTasks.length" :image="Empty.PRESENTED_IMAGE_SIMPLE" description="暂无任务记录" />
          <div v-else class="flex max-h-[260px] flex-col gap-1.5 overflow-y-auto pr-0.5">
            <div
              v-for="t in recentTasks.slice(0, 8)"
              :key="t.id"
              class="flex cursor-pointer items-center gap-2.5 rounded-lg p-2 transition-colors hover:bg-muted/50"
              @click="router.push('/system/task-center')"
            >
              <div class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                <ClipboardList class="size-4" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center justify-between gap-2">
                  <span class="truncate text-[13px] font-medium text-foreground">
                    {{ t.module }} · {{ t.task_type }}
                  </span>
                  <span class="shrink-0 text-[11px]" :class="TASK_STATUS_META[t.status]?.cls ?? 'text-muted'">
                    {{ TASK_STATUS_META[t.status]?.label ?? t.status }}
                  </span>
                </div>
                <div class="truncate text-xs text-muted-foreground">
                  {{ t.result_summary || '—' }}
                </div>
                <div class="mt-0.5 text-[11px] text-muted-foreground">{{ taskTime(t.created_at) }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Page>
</template>

<style scoped>
.home-dot-running {
  animation: home-pulse 1.8s infinite;
}

@keyframes home-pulse {
  0% {
    box-shadow: 0 0 0 0 color-mix(in srgb, hsl(var(--primary)) 45%, transparent);
  }
  70% {
    box-shadow: 0 0 0 6px transparent;
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
  }
}
</style>
