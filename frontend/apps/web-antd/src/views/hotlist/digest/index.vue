<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { computed, onMounted, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';

import { message, Select } from 'ant-design-vue';
import { Layers, Radio, Sparkles } from 'lucide-vue-next';

import { getHotlistDigestApi, listHotlistSourcesApi, listSourceGroupsApi } from '#/api/core/hotlist';

const MODE_TABS: { value: HotlistApi.DigestMode; label: string; hint: string }[] = [
  { value: 'daily', label: '当日汇总', hint: '当天全部条目' },
  { value: 'incremental', label: '只看新增', hint: '各源最新一批里的新条目' },
  { value: 'current', label: '当前榜单', hint: '各源最新一批仍在榜的条目' },
];

function formatDateTime(iso: null | string) {
  if (!iso) return '—';
  return iso.slice(0, 16).replace('T', ' ');
}

const sources = ref<HotlistApi.Source[]>([]);
const groups = ref<HotlistApi.SourceGroup[]>([]);
async function fetchSources() {
  try {
    const [srcs, grps] = await Promise.all([
      listHotlistSourcesApi(),
      listSourceGroupsApi(),
    ]);
    sources.value = srcs;
    groups.value = grps;
  } catch {
    /* 静默降级 */
  }
}
function sourceName(sourceId: string) {
  return sources.value.find((s) => s.id === sourceId)?.name || sourceId;
}

// 数据源分组下拉：只展示用户创建的分组名（不关心具体某个 RSS 源）。
// value 约定：'' = 全部分组，'ungrouped' = 未分组，其余为分组 id 的字符串。
interface GroupSelectOption {
  label: string;
  value: string;
}
const groupOptions = computed<GroupSelectOption[]>(() => [
  { value: '', label: '全部分组' },
  ...groups.value.map((g) => ({ value: String(g.id), label: g.name })),
  { value: 'ungrouped', label: '未分组' },
]);

const mode = ref<HotlistApi.DigestMode>('daily');
const sourceFilter = ref<string>('');
const digest = ref<HotlistApi.Digest | null>(null);
const loading = ref(false);

async function fetchDigest() {
  loading.value = true;
  try {
    digest.value = await getHotlistDigestApi({
      mode: mode.value,
      group: sourceFilter.value || undefined,
    });
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    loading.value = false;
  }
}

watch([mode, sourceFilter], fetchDigest);

const currentHint = computed(() => MODE_TABS.find((t) => t.value === mode.value)?.hint || '');

onMounted(() => {
  fetchSources();
  fetchDigest();
});
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-background-deep p-6 lg:p-8 select-none">
      <!-- 页头 Hero -->
      <div class="fade-up relative mb-8 shrink-0 overflow-hidden rounded-3xl border border-border bg-card p-6 shadow-sm">
        <div class="pointer-events-none absolute -right-12 -top-14 size-52 rounded-full bg-primary/12 blur-3xl"></div>
        <div class="pointer-events-none absolute -bottom-20 -left-14 size-60 rounded-full bg-success/10 blur-3xl"></div>
        <div class="relative flex items-center gap-4">
          <div
            class="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-primary to-primary/50 text-primary-foreground shadow-lg shadow-primary/25"
          >
            <Sparkles class="size-5" />
          </div>
          <div>
            <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-primary">Smart Digest</p>
            <h1
              class="display-font mt-1 bg-gradient-to-r from-foreground to-foreground/60 bg-clip-text text-2xl font-black tracking-tight text-transparent"
            >
              热点摘要
            </h1>
            <p class="mt-1 text-xs text-muted-foreground">按频率词规则分组的当日热点摘要，{{ currentHint }}</p>
          </div>
        </div>
      </div>

      <!-- 统计卡片 -->
      <div class="fade-up mb-6 grid shrink-0 grid-cols-1 gap-4 sm:grid-cols-3" style="animation-delay: 60ms">
        <div
          class="group relative overflow-hidden rounded-2xl border border-border bg-card p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-xl"
        >
          <div class="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-primary via-primary/70 to-primary/30"></div>
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-muted-foreground">总条目</span>
            <Sparkles class="size-4 text-primary/70 transition-transform duration-300 group-hover:scale-110" />
          </div>
          <div class="mt-3 text-3xl font-bold tracking-tight text-foreground">{{ digest?.total_items ?? 0 }}</div>
          <div class="mt-1 text-[11px] text-muted-foreground">{{ digest?.stat_date || '—' }}</div>
        </div>
        <div
          class="group relative overflow-hidden rounded-2xl border border-border bg-card p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-xl"
          style="animation-delay: 120ms"
        >
          <div class="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-success via-success/70 to-success/30"></div>
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-muted-foreground">规则分组</span>
            <Layers class="size-4 text-success/70 transition-transform duration-300 group-hover:scale-110" />
          </div>
          <div class="mt-3 text-3xl font-bold tracking-tight text-foreground">{{ digest?.groups.length ?? 0 }}</div>
          <div class="mt-1 text-[11px] text-muted-foreground">按频率词规则聚合</div>
        </div>
        <div
          class="group relative overflow-hidden rounded-2xl border border-border bg-card p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-xl"
          style="animation-delay: 180ms"
        >
          <div class="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-muted-foreground via-muted-foreground/50 to-muted-foreground/20"></div>
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-muted-foreground">数据源</span>
            <Radio class="size-4 text-muted-foreground/60 transition-transform duration-300 group-hover:scale-110" />
          </div>
          <div class="mt-3 text-3xl font-bold tracking-tight text-foreground">{{ sources.length }}</div>
          <div class="mt-1 text-[11px] text-muted-foreground">覆盖的抓取源</div>
        </div>
      </div>

      <!-- 模式分段控件 -->
      <div class="fade-up mb-5 inline-flex shrink-0 items-center gap-0.5 self-start rounded-full border border-border bg-card p-1 shadow-sm" style="animation-delay: 240ms">
        <button
          v-for="tab in MODE_TABS"
          :key="tab.value"
          class="rounded-full px-4 py-1.5 text-xs font-medium transition-all"
          :class="
            mode === tab.value
              ? 'bg-primary text-primary-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground'
          "
          @click="mode = tab.value"
        >
          {{ tab.label }}
        </button>
      </div>

      <!-- 筛选工具栏 -->
      <div class="fade-up mb-5 flex shrink-0 flex-wrap items-center gap-2" style="animation-delay: 300ms">
        <Select
          v-model:value="sourceFilter"
          allow-clear
          placeholder="全部分组"
          class="w-44"
          :options="groupOptions"
        />
      </div>

      <!-- 空状态 -->
      <div
        v-if="!loading && digest && digest.groups.length === 0"
        class="fade-up rounded-2xl border border-border bg-card p-16 text-center"
        style="animation-delay: 360ms"
      >
        <div class="mx-auto mb-3 flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <Sparkles class="size-5" />
        </div>
        <p class="text-sm font-medium text-foreground">暂无内容</p>
        <p class="mt-1 text-xs text-muted-foreground">
          {{ mode === 'incremental' ? '当前没有比上一批更新的条目' : '当天还没有抓到数据' }}
        </p>
      </div>

      <!-- 分组 -->
      <div v-else class="space-y-4">
        <div
          v-for="(group, idx) in digest?.groups ?? []"
          :key="group.rule_id ?? 'ungrouped'"
          class="fade-up overflow-hidden rounded-2xl border border-border bg-card shadow-sm transition-all duration-300 hover:shadow-lg"
          :style="{ animationDelay: `${360 + idx * 60}ms` }"
        >
          <div class="flex items-center justify-between border-b border-border bg-muted/40 px-5 py-3">
            <span class="text-sm font-semibold text-foreground">{{ group.display_name }}</span>
            <span class="rounded-full bg-muted px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
              {{ group.items.length }} 条
            </span>
          </div>
          <ul class="divide-y divide-border">
            <li v-for="item in group.items" :key="item.id" class="flex items-start gap-3 px-5 py-3 text-xs transition-colors hover:bg-accent/50">
              <span class="mt-0.5 w-9 shrink-0 font-mono text-[11px] text-muted-foreground">
                {{ item.rank > 0 ? `#${item.rank}` : '脱榜' }}
              </span>
              <div class="min-w-0 flex-1">
                <a
                  v-if="item.url"
                  :href="item.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="line-clamp-1 font-medium text-foreground transition-colors hover:text-primary"
                >
                  {{ item.title }}
                </a>
                <span v-else class="line-clamp-1 font-medium text-foreground">{{ item.title }}</span>
                <div class="mt-0.5 text-[11px] text-muted-foreground">
                  {{ sourceName(item.source_id) }} · 出现 {{ item.crawl_count }} 次 · {{ formatDateTime(item.last_crawl_time) }}
                </div>
              </div>
              <span class="shrink-0 rounded-full bg-muted px-2 py-0.5 font-mono text-[11px] font-semibold text-foreground">
                {{ item.weight.toFixed(1) }}
              </span>
            </li>
          </ul>
        </div>
      </div>
    </div>
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
