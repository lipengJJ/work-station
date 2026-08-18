<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { computed, onMounted, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';

import { message, Select } from 'ant-design-vue';

import { getHotlistDigestApi, listHotlistSourcesApi } from '#/api/core/hotlist';

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
async function fetchSources() {
  try {
    sources.value = await listHotlistSourcesApi();
  } catch {
    /* 静默降级 */
  }
}
function sourceName(sourceId: string) {
  return sources.value.find((s) => s.id === sourceId)?.name || sourceId;
}

const mode = ref<HotlistApi.DigestMode>('daily');
const sourceFilter = ref<string>('');
const digest = ref<HotlistApi.Digest | null>(null);
const loading = ref(false);

async function fetchDigest() {
  loading.value = true;
  try {
    digest.value = await getHotlistDigestApi({
      mode: mode.value,
      source_ids: sourceFilter.value || undefined,
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
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-[hsl(var(--background-deep))] p-6 select-none">
      <div class="mb-6 shrink-0 flex items-start justify-between gap-3">
        <div>
          <h1 class="text-xl font-extrabold text-[hsl(var(--foreground))]">热点聚合 · 摘要</h1>
          <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">按频率词规则分组的当日热点摘要，{{ currentHint }}</p>
        </div>
      </div>

      <div class="mb-4 shrink-0 flex items-center gap-1 border-b border-[hsl(var(--border))]">
        <button
          v-for="tab in MODE_TABS"
          :key="tab.value"
          class="border-b-2 px-3 py-2 text-xs font-semibold transition-colors"
          :class="
            mode === tab.value
              ? 'border-indigo-500 text-[hsl(var(--foreground))]'
              : 'border-transparent text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
          "
          @click="mode = tab.value"
        >
          {{ tab.label }}
        </button>
      </div>

      <div class="mb-4 shrink-0 flex flex-wrap items-center gap-2">
        <Select
          v-model:value="sourceFilter"
          allow-clear
          placeholder="全部来源"
          class="w-44"
          :options="[{ value: '', label: '全部来源' }, ...sources.map((s) => ({ value: s.id, label: s.name || s.id }))]"
        />
        <span v-if="digest" class="text-xs text-[hsl(var(--muted-foreground))]">
          {{ digest.stat_date }} · 共 {{ digest.total_items }} 条
        </span>
      </div>

      <div v-if="!loading && digest && digest.groups.length === 0" class="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] p-12 text-center">
        <p class="text-sm font-semibold text-[hsl(var(--foreground))]">暂无内容</p>
        <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
          {{ mode === 'incremental' ? '当前没有比上一批更新的条目' : '当天还没有抓到数据' }}
        </p>
      </div>

      <div v-else class="space-y-4">
        <div
          v-for="group in digest?.groups ?? []"
          :key="group.rule_id ?? 'ungrouped'"
          class="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] shadow-xl"
        >
          <div class="flex items-center justify-between border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] px-4 py-2.5">
            <span class="text-sm font-bold text-[hsl(var(--foreground))]">{{ group.display_name }}</span>
            <span class="text-[11px] text-[hsl(var(--muted-foreground))]">{{ group.items.length }} 条</span>
          </div>
          <ul class="divide-y divide-[hsl(var(--border))]">
            <li v-for="item in group.items" :key="item.id" class="flex items-start gap-3 px-4 py-2.5 text-xs">
              <span class="mt-0.5 shrink-0 font-mono text-[hsl(var(--muted-foreground))]">
                {{ item.rank > 0 ? `#${item.rank}` : '脱榜' }}
              </span>
              <div class="min-w-0 flex-1">
                <a
                  v-if="item.url"
                  :href="item.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="line-clamp-1 font-semibold text-[hsl(var(--foreground))] hover:text-indigo-400"
                >
                  {{ item.title }}
                </a>
                <span v-else class="line-clamp-1 font-semibold text-[hsl(var(--foreground))]">{{ item.title }}</span>
                <div class="mt-0.5 text-[11px] text-[hsl(var(--muted-foreground))]">
                  {{ sourceName(item.source_id) }} · 出现 {{ item.crawl_count }} 次 · {{ formatDateTime(item.last_crawl_time) }}
                </div>
              </div>
              <span class="shrink-0 font-mono text-[11px] text-[hsl(var(--muted-foreground))]">{{ item.weight.toFixed(1) }}</span>
            </li>
          </ul>
        </div>
      </div>
    </div>
  </Page>
</template>
