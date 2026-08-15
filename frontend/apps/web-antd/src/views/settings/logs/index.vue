<script lang="ts" setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { Button, Input, message, Select, Switch } from 'ant-design-vue';

import { getSystemLogsApi } from '#/api/core/system';

// 日志条数：排查问题看最近几条就够，太多没必要
const LINE_OPTIONS = [
  { label: '最近 10 行', value: 10 },
  { label: '最近 50 行', value: 50 },
  { label: '最近 100 行', value: 100 },
  { label: '最近 200 行', value: 200 },
];
const LEVEL_OPTIONS = [
  { label: '全部级别', value: '' },
  { label: 'ERROR', value: 'ERROR' },
  { label: 'WARNING', value: 'WARNING' },
  { label: 'INFO', value: 'INFO' },
];

const lines = ref<string[]>([]);
const loading = ref(false);
const loadError = ref('');
const logFile = ref('');
const totalLines = ref(0);
const lineCount = ref(50);
const levelFilter = ref('');
const searchQuery = ref('');
// 自动刷新默认开启（tail -f 体验），可手动关闭
const autoRefresh = ref(true);

// loguru 默认格式：2026-08-02 16:29:25.584 | INFO | module:func:line - message
const LEVEL_RE = /\|\s*(TRACE|DEBUG|INFO|SUCCESS|WARNING|ERROR|CRITICAL)\s*\|/;

function levelOf(line: string): string {
  return LEVEL_RE.exec(line)?.[1] ?? '';
}

const filteredLines = computed(() => {
  const q = searchQuery.value.trim().toLowerCase();
  return lines.value.filter((line) => {
    if (levelFilter.value && levelOf(line) !== levelFilter.value) return false;
    if (q && !line.toLowerCase().includes(q)) return false;
    return true;
  });
});

function levelClass(line: string) {
  const level = levelOf(line);
  if (level === 'ERROR' || level === 'CRITICAL') return 'log-line log-line--error';
  if (level === 'WARNING') return 'log-line log-line--warning';
  return 'log-line';
}

// ---- tail 跟随：固定在底部看最新日志，用户向上滚动时暂停跟随（像终端 tail -f） ----
const logViewerRef = ref<HTMLElement | null>(null);
const followTail = ref(true);

function scrollToBottom() {
  const el = logViewerRef.value;
  if (el) el.scrollTop = el.scrollHeight;
}

function onLogScroll() {
  const el = logViewerRef.value;
  if (!el) return;
  // 距底部 40px 以内视为"仍贴底"，保持跟随；滚上去则暂停
  followTail.value = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
}

function resumeFollow() {
  followTail.value = true;
  scrollToBottom();
}

async function fetchLogs(silent = false) {
  if (!silent) loading.value = true;
  loadError.value = '';
  try {
    const res = await getSystemLogsApi(lineCount.value);
    lines.value = res.lines;
    logFile.value = res.file;
    totalLines.value = res.total_lines;
  } catch (e: any) {
    loadError.value = e.message || '加载日志失败';
  } finally {
    if (!silent) loading.value = false;
  }
  // 数据更新后若仍处于"贴底跟随"状态，等 DOM 渲染完再滚回底部
  // （Vue 的 DOM 更新是异步的，直接滚会用旧的 scrollHeight，导致"自动滚动不生效"）
  if (followTail.value) {
    await nextTick();
    scrollToBottom();
  }
}

async function copyAll() {
  try {
    await navigator.clipboard.writeText(filteredLines.value.join('\n'));
    message.success('已复制');
  } catch {
    message.error('复制失败，可能是浏览器不支持或未授权剪贴板权限');
  }
}

let timer: ReturnType<typeof setInterval> | undefined;
function toggleAutoRefresh(checked: boolean) {
  autoRefresh.value = checked;
  if (timer) clearInterval(timer);
  if (checked) {
    timer = setInterval(() => fetchLogs(true), 5000);
  }
}

onMounted(() => {
  fetchLogs();
  // 自动刷新默认开启（tail -f）
  toggleAutoRefresh(true);
});
onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <Page :auto-content-height="true">
    <div style="position: relative; display: flex; flex-direction: column; gap: 12px; height: 100%">
      <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 8px">
        <Select v-model:value="lineCount" :options="LINE_OPTIONS" style="width: 140px" @change="() => fetchLogs()" />
        <Select v-model:value="levelFilter" :options="LEVEL_OPTIONS" style="width: 120px" />
        <Input v-model:value="searchQuery" placeholder="搜索日志内容" allow-clear style="width: 240px" />
        <Button :loading="loading" @click="() => fetchLogs()">刷新</Button>
        <Button @click="copyAll">复制当前显示内容</Button>
        <span style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: hsl(var(--muted-foreground))">
          <Switch size="small" :checked="autoRefresh" @change="(v) => toggleAutoRefresh(v as boolean)" />
          每 5 秒自动刷新
        </span>
        <span style="flex: 1"></span>
        <span style="font-size: 12px; color: hsl(var(--muted-foreground))">
          日志文件：{{ logFile || '--' }}（共 {{ totalLines }} 行，当前显示 {{ filteredLines.length }} 行）
        </span>
      </div>

      <div v-if="loadError" style="color: #ff4d4f; font-size: 12px">{{ loadError }}</div>

      <div ref="logViewerRef" class="log-viewer" @scroll.passive="onLogScroll">
        <div v-if="!loading && filteredLines.length === 0" style="padding: 24px; text-align: center; color: hsl(var(--muted-foreground))">
          没有匹配的日志
        </div>
        <div v-for="(line, idx) in filteredLines" :key="idx" :class="levelClass(line)">{{ line }}</div>
      </div>
      <div v-if="!followTail" class="tail-follow-bar">
        <span>已暂停跟随（向上查看历史日志）</span>
        <Button size="small" @click="resumeFollow">回到最新</Button>
      </div>
    </div>
  </Page>
</template>

<style scoped>
.log-viewer {
  flex: 1;
  overflow-y: auto;
  background: hsl(var(--background-deep));
  border: 1px solid hsl(var(--border));
  border-radius: 8px;
  padding: 8px 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
}
.tail-follow-bar {
  position: absolute;
  right: 20px;
  bottom: 20px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 8px;
  background: hsl(var(--muted));
  color: hsl(var(--muted-foreground));
  font-size: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
  z-index: 10;
}
.log-line {
  color: hsl(var(--muted-foreground));
  white-space: pre-wrap;
  word-break: break-all;
}
.log-line--warning {
  color: hsl(var(--warning));
}
.log-line--error {
  color: hsl(var(--destructive));
}
</style>
