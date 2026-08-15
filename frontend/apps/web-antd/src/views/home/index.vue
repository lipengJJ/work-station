<script lang="ts" setup>
import type { WorkbenchApi } from '#/api/core/workbench';

import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';

import { Empty, Progress, Tag, Tooltip } from 'ant-design-vue';
import {
  Activity,
  CheckCircle2,
  Database,
  HardDrive,
  Loader2,
  PlusCircle,
  TrendingUp,
} from 'lucide-vue-next';

import { getHomeApi, getHomeStorageApi } from '#/api/core/workbench';

// ---------------------------------------------------------------- 常量 ----

const KIND_META: Record<string, { label: string; color: string; route: string }> = {
  collect: { label: '采集任务', color: 'blue', route: '/xhs/notes' },
  backfill: { label: '补抓评论', color: 'cyan', route: '/xhs/notes' },
  tracking: { label: '追踪扫描', color: 'purple', route: '/xhs/tracking' },
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

const STATUS_DOT_COLOR: Record<string, string> = {
  success: '#22c55e',
  running: '#eab308',
  pending: '#94a3b8',
  failed: '#f43f5e',
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

async function loadStorage() {
  try {
    storage.value = await getHomeStorageApi();
  } catch {
    // 静默
  }
}

// ------------------------------------------- 存储趋势折线图（SVG）----
const ST_W = 560;
const ST_H = 150;
const ST_PAD = { top: 12, right: 10, bottom: 20, left: 52 };

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
  const linePath = (key: 'db' | 'storage') =>
    points
      .map((p, i) => {
        const { x, y } = toXY(p[key], i);
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  // 刻度：0 / 1/3 / 2/3 / max
  const ticks = [0, 0.33, 0.66, 1].map((r) => ({
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
  return { lineDb: linePath('db'), lineStorage: linePath('storage'), ticks, labels, count: points.length };
});

function formatAxis(n: number): string {
  if (n >= 1024 * 1024 * 1024) return `${(n / 1024 / 1024 / 1024).toFixed(1)}GB`;
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(0)}MB`;
  return `${(n / 1024).toFixed(0)}KB`;
}

const nowText = ref('');
const lastRefreshText = ref('');

function clockTick() {
  nowText.value = new Date().toLocaleString('zh-CN', { hour12: false });
}

async function loadHome() {
  try {
    data.value = await getHomeApi();
    lastRefreshText.value = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  } catch {
    // 轮询失败静默
  } finally {
    loading.value = false;
  }
}

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

// ---------------------------------------------------------- SVG 趋势图 ----

const TREND_W = 560;
const TREND_H = 160;
const TREND_PAD = { top: 14, right: 10, bottom: 22, left: 28 };

const trendChart = computed(() => {
  const points = trend.value;
  const innerW = TREND_W - TREND_PAD.left - TREND_PAD.right;
  const innerH = TREND_H - TREND_PAD.top - TREND_PAD.bottom;
  const max = Math.max(1, ...points.flatMap((p) => [p.created, p.finished]));
  const step = points.length > 1 ? innerW / points.length : innerW;
  const barW = Math.min(26, step * 0.32);
  const bars = points.map((p, i) => {
    const cx = TREND_PAD.left + step * i + step / 2;
    const hCreated = (p.created / max) * innerH;
    const hFinished = (p.finished / max) * innerH;
    return {
      x1: cx - barW - 2,
      y1: TREND_PAD.top + innerH - hCreated,
      h1: hCreated,
      x2: cx + 2,
      y2: TREND_PAD.top + innerH - hFinished,
      h2: hFinished,
    };
  });
  const labels = points.map((p) => {
    const d = new Date(`${p.date}T00:00:00`);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  });
  return { bars, labels, max };
});

// ---------------------------------------------------------- SVG 环形图 ----

const RING_R = 52;
const RING_C = 2 * Math.PI * RING_R;
const RING_COLORS: [string, string][] = [
  ['success', '#22c55e'],
  ['running', '#eab308'],
  ['pending', '#94a3b8'],
  ['failed', '#f43f5e'],
];

const ringSeg = computed(() => {
  const d = dist.value;
  const total = Math.max(1, Object.values(d).reduce((a, b) => a + b, 0));
  return RING_COLORS.map(([key, color]) => ({
    color,
    len: ((d[key] ?? 0) / total) * RING_C,
    label: STATUS_LABEL[key] ?? key,
    count: d[key] ?? 0,
  }));
});

function ringOffset(i: number): number {
  return i === 0 ? 0 : -ringSeg.value.slice(0, i).reduce((a, s) => a + s.len, 0);
}

// ---------------------------------------------------------------- 时钟 ----

let timer: ReturnType<typeof setInterval> | undefined;
let storageTimer: ReturnType<typeof setInterval> | undefined;

onMounted(() => {
  clockTick();
  setInterval(clockTick, 1000);
  loadHome();
  timer = setInterval(loadHome, 5000);
  loadStorage();
  // 存储统计独立低频轮询（du 扫描有成本）
  storageTimer = setInterval(loadStorage, 30000);
});

onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
  if (storageTimer) clearInterval(storageTimer);
});
</script>

<template>
  <Page :auto-content-height="false">
    <!-- 顶部：监控状态条 -->
    <div
      style="
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 16px;
        margin-bottom: 14px;
        border-radius: 12px;
        border: 1px solid hsl(var(--border));
        background: hsl(var(--card));
      "
    >
      <div style="display: flex; align-items: center; gap: 10px">
        <span
          style="
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #22c55e;
            box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.6);
            animation: pulse-dot 1.8s infinite;
          "
        ></span>
        <span style="font-weight: 700; font-size: 14px; color: hsl(var(--foreground))">运行状态监控</span>
        <span style="font-size: 12px; color: hsl(var(--muted-foreground))">上次刷新 {{ lastRefreshText || '--' }}</span>
      </div>
      <div style="display: flex; align-items: center; gap: 14px">
        <span style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: hsl(var(--muted-foreground))">
          <Loader2 style="width: 13px; height: 13px; animation: spin 2s linear infinite" />
          每 5 秒自动刷新
        </span>
        <span style="font-family: ui-monospace, monospace; font-size: 14px; font-weight: 600; color: hsl(var(--foreground))">
          {{ nowText }}
        </span>
      </div>
    </div>

    <!-- KPI 卡片 -->
    <div class="kpi-grid">
      <div v-for="kpi in [
        { label: '任务总数', value: data?.summary.total_tasks ?? 0, icon: Database, color: '#3b82f6', sub: '全部模块累计' },
        { label: '运行中', value: data?.summary.running_count ?? 0, icon: Activity, color: '#eab308', sub: '采集 / 补抓 / 追踪' },
        { label: '今日新增', value: data?.summary.today_new ?? 0, icon: PlusCircle, color: '#22c55e', sub: '今天创建的任务' },
        { label: '今日完成', value: data?.summary.today_done ?? 0, icon: CheckCircle2, color: '#06b6d4', sub: '今天跑完的任务' },
        { label: '成功率', value: `${data?.summary.success_rate ?? 0}%`, icon: TrendingUp, color: '#8b5cf6', sub: `${data?.summary.success_count ?? 0} 成功 / ${(data?.summary.success_count ?? 0) + (data?.summary.failed_count ?? 0)} 完成` },
      ] as const"
        :key="kpi.label"
        style="
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 16px;
          border-radius: 12px;
          border: 1px solid hsl(var(--border));
          background: hsl(var(--card));
          position: relative;
          overflow: hidden;
        "
      >
        <div
          class="kpi-icon"
          :style="{
            width: 44,
            height: 44,
            borderRadius: 12,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: `color-mix(in srgb, ${kpi.color} 16%, transparent)`,
            color: kpi.color,
            flexShrink: 0,
          }"
        >
          <component :is="kpi.icon" :style="{ width: 22, height: 22 }" />
        </div>
        <div style="min-width: 0">
          <div style="font-size: 12px; color: hsl(var(--muted-foreground))">{{ kpi.label }}</div>
          <div style="font-size: 26px; font-weight: 800; line-height: 1.2; font-variant-numeric: tabular-nums; color: hsl(var(--foreground))">
            {{ kpi.value }}
          </div>
          <div style="font-size: 11px; color: hsl(var(--muted-foreground)); white-space: nowrap; overflow: hidden; text-overflow: ellipsis">
            {{ kpi.sub }}
          </div>
        </div>
      </div>
    </div>

    <!-- 存储面板：左=当前数值明细，右=趋势折线 -->
    <div
      class="storage-panel"
    >
      <!-- 左：当前存储明细 -->
      <div style="display: flex; flex-direction: column; gap: 8px; min-width: 0">
        <div style="display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 700; color: hsl(var(--foreground))">
          <HardDrive style="width: 14px; height: 14px" />
          存储使用
          <span style="margin-left: auto; font-size: 11px; font-weight: 400; color: hsl(var(--muted-foreground))">每 30 秒刷新</span>
        </div>
        <div
          v-for="item in [
            { label: '数据库', value: formatBytes(storage?.db_size ?? 0), color: '#3b82f6', note: 'SQLite 持久化' },
            { label: '笔记素材', value: formatBytes(storage?.storage_size ?? 0), color: '#22c55e', note: 'Excel/图文素材' },
            { label: '合计占用', value: formatBytes((storage?.db_size ?? 0) + (storage?.storage_size ?? 0)), color: '#f59e0b', note: '持久化总量' },
          ] as const"
          :key="item.label"
          style="display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 8px; background: hsl(var(--background-deep))"
        >
          <i :style="{ width: 8, height: 8, borderRadius: '50%', background: item.color, flexShrink: 0 }"></i>
          <span style="font-size: 12px; color: hsl(var(--muted-foreground))">{{ item.label }}</span>
          <span style="margin-left: auto; font-size: 15px; font-weight: 800; font-variant-numeric: tabular-nums; color: hsl(var(--foreground))">{{ item.value }}</span>
          <span style="font-size: 10px; color: hsl(var(--muted-foreground))">{{ item.note }}</span>
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-top: 2px">
          <div v-for="c in [
            { label: '笔记', v: storage?.note_count ?? 0, u: '篇' },
            { label: '评论', v: storage?.comment_count ?? 0, u: '条' },
            { label: '任务', v: storage?.task_count ?? 0, u: '个' },
          ] as const" :key="c.label" style="text-align: center; padding: 6px 4px; border-radius: 8px; background: hsl(var(--background-deep))">
            <div style="font-size: 14px; font-weight: 700; font-variant-numeric: tabular-nums; color: hsl(var(--foreground))">
              {{ c.v }}<span style="font-size: 10px; font-weight: 400; color: hsl(var(--muted-foreground))"> {{ c.u }}</span>
            </div>
            <div style="font-size: 10px; color: hsl(var(--muted-foreground))">{{ c.label }}</div>
          </div>
        </div>
      </div>

      <!-- 右：趋势折线 -->
      <div style="min-width: 0">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px">
          <span style="display: flex; align-items: center; gap: 12px; font-size: 11px; color: hsl(var(--muted-foreground))">
            <span style="display: flex; align-items: center; gap: 5px"><i style="width: 9px; height: 3px; border-radius: 2px; background: #3b82f6"></i>数据库</span>
            <span style="display: flex; align-items: center; gap: 5px"><i style="width: 9px; height: 3px; border-radius: 2px; background: #22c55e"></i>素材</span>
            <span>近 24h · 每 5 分钟采样</span>
          </span>
        </div>
        <svg :viewBox="`0 0 ${ST_W} ${ST_H}`" style="width: 100%; height: auto">
          <template v-for="tick in storageChart.ticks" :key="tick.y">
            <line
              :x1="ST_PAD.left"
              :x2="ST_W - ST_PAD.right"
              :y1="tick.y"
              :y2="tick.y"
              stroke="hsl(var(--border))"
              stroke-width="0.6"
              stroke-dasharray="3 4"
            />
            <text :x="ST_PAD.left - 6" :y="tick.y + 3" text-anchor="end" fill="hsl(var(--muted-foreground))" style="font-size: 10px">
              {{ tick.label }}
            </text>
          </template>
          <template v-if="storageChart.count > 1">
            <path :d="storageChart.lineStorage" fill="none" stroke="#22c55e" stroke-width="1.8" opacity="0.9" />
            <path :d="storageChart.lineDb" fill="none" stroke="#3b82f6" stroke-width="1.8" opacity="0.9" />
          </template>
          <text
            v-if="!storageChart.count"
            :x="ST_W / 2"
            :y="ST_H / 2"
            text-anchor="middle"
            fill="hsl(var(--muted-foreground))"
            style="font-size: 12px"
          >
            正在采样中，每 5 分钟记录一个点
          </text>
          <g v-for="l in storageChart.labels" :key="l.x">
            <text :x="l.x" :y="ST_H - 6" text-anchor="middle" fill="hsl(var(--muted-foreground))" style="font-size: 10px">
              {{ l.t }}
            </text>
          </g>
        </svg>
      </div>
    </div>

    <!-- 图表行：趋势 + 状态分布 -->
    <div class="chart-row">
      <div
        style="
          padding: 14px 16px;
          border-radius: 12px;
          border: 1px solid hsl(var(--border));
          background: hsl(var(--card));
        "
      >
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px">
          <span style="font-size: 13px; font-weight: 700; color: hsl(var(--foreground))">近 7 天任务趋势</span>
          <span style="display: flex; gap: 14px; font-size: 11px; color: hsl(var(--muted-foreground))">
            <span style="display: flex; align-items: center; gap: 5px"><i style="width: 9px; height: 9px; border-radius: 2px; background: hsl(var(--primary))"></i>创建</span>
            <span style="display: flex; align-items: center; gap: 5px"><i style="width: 9px; height: 9px; border-radius: 2px; background: #22c55e"></i>完成</span>
          </span>
        </div>
        <svg :viewBox="`0 0 ${TREND_W} ${TREND_H}`" style="width: 100%; height: auto">
          <template v-for="n in 4" :key="n">
            <line
              :x1="TREND_PAD.left"
              :x2="TREND_W - TREND_PAD.right"
              :y1="TREND_PAD.top + ((TREND_H - TREND_PAD.top - TREND_PAD.bottom) / 4) * (n - 1)"
              :y2="TREND_PAD.top + ((TREND_H - TREND_PAD.top - TREND_PAD.bottom) / 4) * (n - 1)"
              stroke="hsl(var(--border))"
              stroke-width="0.6"
              stroke-dasharray="3 4"
            />
          </template>
          <template v-if="trend.length">
            <g v-for="b in trendChart.bars" :key="b.x1">
              <rect :x="b.x1" :y="b.y1" :width="10" :height="b.h1" rx="2" fill="hsl(var(--primary))" opacity="0.85" />
              <rect :x="b.x2" :y="b.y2" :width="10" :height="b.h2" rx="2" fill="#22c55e" opacity="0.85" />
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
        </svg>
      </div>

      <!-- 状态分布环形 -->
      <div
        style="
          display: flex;
          align-items: center;
          gap: 18px;
          padding: 14px 16px;
          border-radius: 12px;
          border: 1px solid hsl(var(--border));
          background: hsl(var(--card));
        "
      >
        <svg viewBox="0 0 140 140" style="width: 132px; height: 132px; flex-shrink: 0">
          <circle cx="70" cy="70" :r="RING_R" fill="none" stroke="hsl(var(--muted))" stroke-width="14" />
          <circle
            v-for="(seg, i) in ringSeg"
            :key="seg.label"
            cx="70"
            cy="70"
            :r="RING_R"
            fill="none"
            :stroke="seg.color"
            stroke-width="14"
            :stroke-dasharray="`${seg.len} ${RING_C - seg.len}`"
            :stroke-dashoffset="i === 0 ? 0 : -ringOffset(i)"
            stroke-linecap="butt"
            transform="rotate(-90 70 70)"
            opacity="0.9"
          />
          <text x="70" y="66" text-anchor="middle" fill="hsl(var(--foreground))" style="font-size: 22px; font-weight: 800">
            {{ Object.values(dist).reduce((a, b) => a + b, 0) }}
          </text>
          <text x="70" y="84" text-anchor="middle" fill="hsl(var(--muted-foreground))" style="font-size: 10px">任务总数</text>
        </svg>
        <div style="display: flex; flex-direction: column; gap: 8px; min-width: 0">
          <div v-for="seg in ringSeg" :key="seg.label" style="display: flex; align-items: center; gap: 8px">
            <i :style="{ width: 10, height: 10, borderRadius: 3, background: seg.color, flexShrink: 0 }"></i>
            <span style="font-size: 12px; color: hsl(var(--muted-foreground)); width: 44px">{{ seg.label }}</span>
            <span style="font-size: 13px; font-weight: 700; font-variant-numeric: tabular-nums; color: hsl(var(--foreground))">{{ seg.count }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 运行中任务 -->
    <div
      style="
        padding: 14px 16px;
        margin-bottom: 14px;
        border-radius: 12px;
        border: 1px solid hsl(var(--border));
        background: hsl(var(--card));
      "
    >
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px">
        <span style="font-size: 13px; font-weight: 700; color: hsl(var(--foreground))">运行中任务</span>
        <span style="font-size: 11px; color: hsl(var(--muted-foreground))">点击卡片跳转详情</span>
      </div>
      <Empty v-if="!loading && !hasRunning" description="暂无运行中的任务" />
      <div v-else style="display: flex; flex-wrap: wrap; gap: 12px">
        <div
          v-for="t in runningTasks"
          :key="`${t.kind}-${t.id}`"
          style="
            width: 300px;
            padding: 12px 14px;
            border-radius: 10px;
            border: 1px solid hsl(var(--border));
            background: hsl(var(--background-deep));
            cursor: pointer;
            transition: transform 0.15s, box-shadow 0.15s;
          "
          @click="router.push(KIND_META[t.kind]?.route ?? '/')"
          @mouseover="($event.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'"
          @mouseout="($event.currentTarget as HTMLElement).style.transform = 'translateY(0)'"
        >
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px">
            <div style="display: flex; align-items: center; gap: 8px; min-width: 0">
              <Tag :color="KIND_META[t.kind]?.color" style="margin-inline-end: 0">{{ KIND_META[t.kind]?.label }}</Tag>
              <span style="font-weight: 600; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: hsl(var(--foreground))">
                {{ t.title }}
              </span>
            </div>
            <span style="display: flex; align-items: center; gap: 5px; font-size: 11px; color: hsl(var(--muted-foreground))">
              <i
                :style="{
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  background: STATUS_DOT_COLOR[t.status] ?? 'hsl(var(--muted-foreground))',
                  animation: t.status === 'running' ? 'pulse-dot 1.8s infinite' : 'none',
                }"
              ></i>
              {{ t.status === 'pending' ? '排队中' : '进行中' }}
            </span>
          </div>
          <div style="display: flex; align-items: center; gap: 8px; margin-top: 10px">
            <Progress :percent="taskProgress(t)" :show-info="false" size="small" status="active" style="flex: 1; margin: 0" />
            <Tooltip :title="`${t.progress_current ?? 0} / ${t.progress_total ?? 0}`">
              <span style="font-size: 11px; color: hsl(var(--muted-foreground))">
                {{ t.progress_current ?? 0 }}/{{ t.progress_total ?? 0 }}
              </span>
            </Tooltip>
          </div>
          <div style="margin-top: 6px; font-size: 11px; color: hsl(var(--muted-foreground))">
            {{ phaseText(t) }}
            <span v-if="t.started_at" style="margin-left: 8px">{{ new Date(t.started_at).toLocaleTimeString() }} 开始</span>
          </div>
        </div>
      </div>
    </div>
  </Page>
</template>

<style>
@keyframes pulse-dot {
  0% {
    box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.5);
  }
  70% {
    box-shadow: 0 0 0 7px rgba(34, 197, 94, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(34, 197, 94, 0);
  }
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
<style scoped>
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin-bottom: 14px;
}
.storage-panel {
  display: grid;
  grid-template-columns: 0.9fr 1.4fr;
  gap: 14px;
  padding: 14px 16px;
  margin-bottom: 14px;
  border-radius: 12px;
  border: 1px solid hsl(var(--border));
  background: hsl(var(--card));
}
.chart-row {
  display: grid;
  grid-template-columns: 1.6fr 1fr;
  gap: 12px;
  margin-bottom: 14px;
}
/* 手机端：单列堆叠 + KPI 两列 + 图标缩小 */
@media (max-width: 767px) {
  .kpi-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 10px;
  }
  .storage-panel {
    grid-template-columns: 1fr;
  }
  .chart-row {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 480px) {
  .kpi-icon {
    width: 34px !important;
    height: 34px !important;
    border-radius: 10px !important;
  }
  .kpi-grid > div {
    padding: 12px !important;
    gap: 10px !important;
  }
}
</style>
