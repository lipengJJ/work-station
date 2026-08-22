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
  Database,
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

// ---------------------------------------------------------------- 数据 ----

const data = ref<WorkbenchApi.HomeResponse>();
const storage = ref<WorkbenchApi.StorageStats>();
const loading = ref(true);
const router = useRouter();

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

function taskProgress(t: WorkbenchApi.RunningTask): number {
  if (!t.progress_total) return 0;
  return Math.min(100, Math.round(((t.progress_current ?? 0) / t.progress_total) * 100));
}

function phaseText(t: WorkbenchApi.RunningTask): string {
  return PHASE_TEXT[t.phase ?? ''] ?? t.phase ?? '';
}

// ---------------------------------------------------------- 任务趋势柱状图（放大填满）----

const TREND_W = 560;
const TREND_H = 220;
const TREND_PAD = { top: 16, right: 12, bottom: 26, left: 34 };

const trendChart = computed(() => {
  const points = trend.value;
  const innerW = TREND_W - TREND_PAD.left - TREND_PAD.right;
  const innerH = TREND_H - TREND_PAD.top - TREND_PAD.bottom;
  const max = Math.max(1, ...points.flatMap((p) => [p.created, p.finished]));
  const step = points.length > 1 ? innerW / points.length : innerW;
  const barW = Math.min(34, step * 0.34);
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

// ---------------------------------------------------------- 存储面积折线图（Prometheus 风格）----

const ST_W = 560;
const ST_H = 210;
const ST_PAD = { top: 14, right: 12, bottom: 24, left: 46 };

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

const RING_R = 50;
const RING_C = 2 * Math.PI * RING_R;
const successRate = computed(() => {
  const r = summary.value?.success_rate ?? 0;
  return Math.max(0, Math.min(100, r));
});
const successDone = computed(() => (summary.value?.success_count ?? 0) + (summary.value?.failed_count ?? 0));

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
    <div class="home-eclipse custom-scrollbar flex h-full flex-col gap-5 overflow-y-auto p-6 lg:p-8 select-none">
      <!-- 双列布局 -->
      <div class="grid min-h-0 grid-cols-1 gap-5 xl:grid-cols-[1.9fr_1fr]">
        <!-- ==================== 左列 ==================== -->
        <div class="flex min-w-0 flex-col gap-5">
          <!-- ① 概览 -->
          <div class="rounded-[22px] p-6" style="background: var(--hm-card)">
            <div class="mb-5 text-lg font-bold" style="color: var(--hm-ink)">概览</div>
            <div class="grid grid-cols-2 gap-6 md:grid-cols-4">
              <div
                v-for="kpi in [
                  { label: '任务总数', value: summary?.total_tasks ?? 0, icon: Database, sub: '全部模块累计' },
                  { label: '运行中', value: summary?.running_count ?? 0, icon: Activity, sub: '采集 / 补抓 / 追踪' },
                  { label: '今日新增', value: summary?.today_new ?? 0, icon: PlusCircle, sub: '今天创建的任务' },
                  { label: '今日完成', value: summary?.today_done ?? 0, icon: CheckCircle2, sub: '今天跑完的任务' },
                ] as const"
                :key="kpi.label"
                class="flex items-center gap-3.5"
              >
                <div class="flex size-12 shrink-0 items-center justify-center rounded-2xl" style="background: var(--hm-accent-soft); color: var(--hm-accent)">
                  <component :is="kpi.icon" class="size-6" />
                </div>
                <div class="min-w-0">
                  <div class="text-xs" style="color: var(--hm-muted)">{{ kpi.label }}</div>
                  <div class="text-3xl font-black tabular-nums" style="color: var(--hm-accent)">{{ kpi.value }}</div>
                  <div class="truncate text-[11px]" style="color: var(--hm-muted)">{{ kpi.sub }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- ② 任务趋势（独占左列宽度，柱状图放大填满） -->
          <div class="rounded-[22px] p-6" style="background: var(--hm-card)">
            <div class="mb-4 flex items-center justify-between">
              <span class="text-lg font-bold" style="color: var(--hm-ink)">任务趋势</span>
              <span class="flex gap-3 text-[11px]" style="color: var(--hm-muted)">
                <span class="flex items-center gap-1.5"><i class="h-2 w-2 rounded-full" style="background: var(--hm-accent)"></i>创建</span>
                <span class="flex items-center gap-1.5"><i class="h-2 w-2 rounded-full" style="background: var(--hm-chart-2)"></i>完成</span>
              </span>
            </div>
            <svg :viewBox="`0 0 ${TREND_W} ${TREND_H}`" class="h-auto w-full">
              <template v-for="tick in trendChart.ticks" :key="tick.y">
                <line :x1="TREND_PAD.left" :x2="TREND_W - TREND_PAD.right" :y1="tick.y" :y2="tick.y" stroke="var(--hm-inner)" stroke-width="0.7" stroke-dasharray="3 4" />
                <text :x="TREND_PAD.left - 6" :y="tick.y + 3" text-anchor="end" fill="var(--hm-muted)" style="font-size: 10px">{{ tick.label }}</text>
              </template>
              <template v-if="trend.length">
                <g v-for="(b, i) in trendChart.bars" :key="i">
                  <rect :x="b.x1" :y="b.y1" :width="b.w" :height="Math.max(b.h1, 2)" rx="4" fill="var(--hm-accent)" opacity="0.92" />
                  <rect :x="b.x2" :y="b.y2" :width="b.w" :height="Math.max(b.h2, 2)" rx="4" fill="var(--hm-chart-2)" opacity="0.9" />
                </g>
                <g v-for="(label, i) in trendChart.labels" :key="label">
                  <text
                    :x="TREND_PAD.left + (trend.length > 1 ? ((TREND_W - TREND_PAD.left - TREND_PAD.right) / trend.length) * i + (TREND_W - TREND_PAD.left - TREND_PAD.right) / trend.length / 2 : TREND_W / 2)"
                    :y="TREND_H - 6"
                    text-anchor="middle"
                    fill="var(--hm-muted)"
                    style="font-size: 10px"
                  >
                    {{ label }}
                  </text>
                </g>
              </template>
            </svg>
          </div>

          <!-- ⑤ 系统信息（深色 CTA 卡片） -->
          <div class="rounded-[22px] p-7" style="background: var(--hm-dark-card); color: var(--hm-dark-text)">
            <div class="flex flex-wrap items-center justify-between gap-6">
              <div>
                <div class="text-sm opacity-70">当前数据</div>
                <div class="text-4xl font-black tabular-nums">
                  {{ formatBytes((storage?.db_size ?? 0) + (storage?.storage_size ?? 0)) }}
                </div>
                <div class="mt-1 text-xs opacity-60">数据库 + 素材合计</div>
                <ul class="mt-4 space-y-1.5 text-sm">
                  <li>· 结构化笔记 {{ storage?.structured_count ?? 0 }} 篇</li>
                  <li>· 分析报告 {{ storage?.report_count ?? 0 }} 份</li>
                </ul>
              </div>
              <button
                class="flex items-center gap-2 rounded-full px-6 py-3 text-sm font-bold transition-opacity hover:opacity-90"
                style="background: var(--hm-accent-soft); color: var(--hm-accent)"
                @click="router.push('/system/task-center')"
              >
                进入任务中心
                <ArrowRight class="size-4" />
              </button>
            </div>
          </div>
        </div>

        <!-- ==================== 右列 ==================== -->
        <div class="flex min-w-0 flex-col gap-5">
          <!-- ② 成功率环形 -->
          <div class="rounded-[22px] p-6" style="background: var(--hm-card)">
            <div class="mb-3 text-lg font-bold" style="color: var(--hm-ink)">成功率</div>
            <div class="flex items-center gap-5">
              <svg viewBox="0 0 140 140" class="h-[130px] w-[130px] shrink-0">
                <circle cx="70" cy="70" r="60" fill="none" stroke="var(--hm-inner)" stroke-width="4" />
                <circle
                  cx="70"
                  cy="70"
                  :r="RING_R"
                  fill="none"
                  stroke="var(--hm-accent)"
                  stroke-width="13"
                  :stroke-dasharray="`${(successRate / 100) * RING_C} ${RING_C}`"
                  stroke-linecap="round"
                  transform="rotate(-90 70 70)"
                />
                <text x="70" y="74" text-anchor="middle" fill="var(--hm-accent)" style="font-size: 24px; font-weight: 900">
                  {{ successRate }}%
                </text>
                <text x="70" y="92" text-anchor="middle" fill="var(--hm-muted)" style="font-size: 10px">成功率</text>
              </svg>
              <div class="min-w-0 flex-1">
                <div class="mb-2 flex items-center justify-between text-[11px]" style="color: var(--hm-muted)">
                  <span>成功 {{ summary?.success_count ?? 0 }}</span>
                  <span>完成 {{ successDone }}</span>
                </div>
                <div class="h-1.5 w-full overflow-hidden rounded-full" style="background: var(--hm-inner)">
                  <div class="h-full rounded-full" style="background: var(--hm-accent)" :style="{ width: `${successRate}%` }"></div>
                </div>
                <div class="mt-3 text-[11px] leading-relaxed" style="color: var(--hm-muted)">
                  {{ Object.entries(dist).map(([k, v]) => `${STATUS_LABEL[k] ?? k} ${v}`).join(' · ') || '暂无统计' }}
                </div>
              </div>
            </div>
          </div>

          <!-- ③ 存储使用（Prometheus 风格面积折线图） -->
          <div class="rounded-[22px] p-6" style="background: var(--hm-card)">
            <div class="mb-4 flex items-center justify-between">
              <span class="text-lg font-bold" style="color: var(--hm-ink)">存储使用</span>
              <span class="flex gap-3 text-[11px]" style="color: var(--hm-muted)">
                <span class="flex items-center gap-1.5"><i class="h-2 w-2 rounded-full" style="background: var(--hm-accent)"></i>数据库</span>
                <span class="flex items-center gap-1.5"><i class="h-2 w-2 rounded-full" style="background: var(--hm-chart-2)"></i>素材</span>
              </span>
            </div>
            <svg :viewBox="`0 0 ${ST_W} ${ST_H}`" class="h-auto w-full">
              <defs>
                <linearGradient id="home-grad-db" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="var(--hm-accent)" stop-opacity="0.25" />
                  <stop offset="100%" stop-color="var(--hm-accent)" stop-opacity="0" />
                </linearGradient>
                <linearGradient id="home-grad-st" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="var(--hm-chart-2)" stop-opacity="0.25" />
                  <stop offset="100%" stop-color="var(--hm-chart-2)" stop-opacity="0" />
                </linearGradient>
              </defs>
              <template v-for="tick in storageChart.ticks" :key="tick.y">
                <line :x1="ST_PAD.left" :x2="ST_W - ST_PAD.right" :y1="tick.y" :y2="tick.y" stroke="var(--hm-inner)" stroke-width="0.7" stroke-dasharray="3 4" />
                <text :x="ST_PAD.left - 6" :y="tick.y + 3" text-anchor="end" fill="var(--hm-muted)" style="font-size: 10px">{{ tick.label }}</text>
              </template>
              <template v-if="storageChart.count > 1">
                <path :d="storageChart.areaStorage" fill="url(#home-grad-st)" />
                <path :d="storageChart.areaDb" fill="url(#home-grad-db)" />
                <path :d="storageChart.lineStorage" fill="none" stroke="var(--hm-chart-2)" stroke-width="1.8" opacity="0.9" />
                <path :d="storageChart.lineDb" fill="none" stroke="var(--hm-accent)" stroke-width="1.8" opacity="0.95" />
              </template>
              <text v-if="!storageChart.count" :x="ST_W / 2" :y="ST_H / 2" text-anchor="middle" fill="var(--hm-muted)" style="font-size: 12px">
                正在采样中，每 5 分钟记录一个点
              </text>
              <g v-for="l in storageChart.labels" :key="l.x">
                <text :x="l.x" :y="ST_H - 6" text-anchor="middle" fill="var(--hm-muted)" style="font-size: 10px">{{ l.t }}</text>
              </g>
            </svg>
            <div class="mt-4 flex justify-between border-t pt-3 text-[11px]" style="border-color: var(--hm-inner); color: var(--hm-muted)">
              <span>笔记 {{ storage?.note_count ?? 0 }}</span>
              <span>评论 {{ storage?.comment_count ?? 0 }}</span>
              <span>任务 {{ storage?.task_count ?? 0 }}</span>
            </div>
          </div>

          <!-- ④ 运行中任务 -->
          <div class="flex min-h-0 flex-1 flex-col rounded-[22px] p-6" style="background: var(--hm-card)">
            <div class="mb-4 flex items-center justify-between">
              <span class="text-lg font-bold" style="color: var(--hm-ink)">运行中任务</span>
              <span class="text-[11px]" style="color: var(--hm-muted)">点击跳转详情</span>
            </div>
            <Empty v-if="!loading && !hasRunning" description="暂无运行中的任务" />
            <div v-else class="flex max-h-[560px] flex-col gap-2 overflow-y-auto">
              <div
                v-for="t in runningTasks"
                :key="`${t.kind}-${t.id}`"
                class="flex cursor-pointer items-start gap-3 rounded-2xl p-3 transition-colors hover:bg-[var(--hm-inner)]"
                @click="router.push(KIND_META[t.kind]?.route ?? '/')"
              >
                <div class="flex size-10 shrink-0 items-center justify-center rounded-xl" style="background: var(--hm-accent-soft); color: var(--hm-accent)">
                  <component :is="KIND_META[t.kind]?.icon" class="size-5" />
                </div>
                <div class="min-w-0 flex-1">
                  <div class="flex items-center justify-between gap-2">
                    <div class="truncate text-sm font-bold" style="color: var(--hm-ink)">{{ t.title }}</div>
                    <span class="flex shrink-0 items-center gap-1.5 text-[11px]" style="color: var(--hm-muted)">
                      <i
                        class="h-1.5 w-1.5 rounded-full"
                        :class="{ 'home-dot-running': t.status === 'running' }"
                        :style="{ background: t.status === 'running' ? 'var(--hm-accent)' : 'var(--hm-muted)' }"
                      ></i>
                      {{ t.status === 'pending' ? '排队中' : '进行中' }}
                    </span>
                  </div>
                  <div class="truncate text-xs" style="color: var(--hm-muted)">{{ phaseText(t) }}</div>
                  <div class="mt-1.5 h-1 w-full overflow-hidden rounded-full" style="background: var(--hm-inner)">
                    <div class="h-full rounded-full" style="background: var(--hm-accent)" :style="{ width: `${taskProgress(t)}%` }"></div>
                  </div>
                  <div class="mt-1.5 text-[11px]" style="color: var(--hm-muted)">
                    <span v-if="t.started_at">{{ new Date(t.started_at).toLocaleTimeString() }} 开始</span>
                    <span class="ml-2">{{ t.progress_current ?? 0 }}/{{ t.progress_total ?? 0 }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Page>
</template>

<style scoped>
/* ===== 首页专属墨绿色板（Eclipse 风格），亮暗两套 ===== */
.home-eclipse {
  --hm-page: #e5e5e5;
  --hm-card: #edece7;
  --hm-inner: #e3e2dc;
  --hm-ink: #2b3a45;
  --hm-muted: #8a8f8a;
  --hm-accent: #1a4d1a;
  --hm-accent-mid: #5c8a52;
  --hm-accent-soft: #a9c89b;
  --hm-chart-2: #a9c89b;
  --hm-dark-card: #3d453d;
  --hm-dark-text: #f0efea;
  background: var(--hm-page);
}

.dark .home-eclipse {
  --hm-page: #141614;
  --hm-card: #1e211e;
  --hm-inner: #262a26;
  --hm-ink: #e8eae6;
  --hm-muted: #8a928a;
  --hm-accent: #7db86a;
  --hm-accent-mid: #5c8a52;
  --hm-accent-soft: #35502e;
  --hm-chart-2: #5c8a52;
  --hm-dark-card: #2a2e2a;
  --hm-dark-text: #e8eae6;
}

.home-dot-running {
  animation: home-pulse 1.8s infinite;
}

@keyframes home-pulse {
  0% {
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--hm-accent) 45%, transparent);
  }
  70% {
    box-shadow: 0 0 0 7px transparent;
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
  }
}
</style>
