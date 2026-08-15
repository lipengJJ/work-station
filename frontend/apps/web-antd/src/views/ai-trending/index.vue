<script lang="ts" setup>
import type { AiTrendingApi } from '#/api/core/ai-trending';

import { computed, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Alert,
  Badge,
  Button,
  Empty,
  List,
  message,
  Modal,
  Pagination,
  Segmented,
  Skeleton,
  Tabs,
  Tag,
} from 'ant-design-vue';
import { Flame, RefreshCw, Star } from 'lucide-vue-next';

import {
  getTrendingSourcesApi,
  listTrendingItemsApi,
  refreshTrendingApi,
} from '#/api/core/ai-trending';

// ----------------------------------------------------------------- 状态 ----
const sourceKey = ref(''); // '' | hn | github | arxiv | hf(合并) | infoq | kr36
const category = ref(''); // '' | news | project | paper | model
const sort = ref<'heat' | 'time'>('heat');
const page = ref(1);
const pageSize = 20;

const loading = ref(false);
const errorMsg = ref('');
const pageData = ref<null | AiTrendingApi.TrendingItemPage>(null);
const sources = ref<AiTrendingApi.SourceStatus[]>([]);
const refreshing = ref(false);
const lastFetchedAt = ref<null | number>(null); // 最近一次成功拉取列表的时间戳

const detailItem = ref<null | AiTrendingApi.TrendingItem>(null);
const modalOpen = ref(false);

// ------------------------------------------------------------- 常量映射 ----
const SOURCE_TABS = [
  { key: '', label: '全部' },
  { key: 'hn', label: 'HN' },
  { key: 'github', label: 'GitHub' },
  { key: 'arxiv', label: 'arXiv' },
  { key: 'hf', label: 'HF' },
  { key: 'infoq', label: 'InfoQ' },
  { key: 'kr36', label: '36氪' },
];

const SOURCE_LABEL: Record<string, string> = {
  hn: 'Hacker News',
  github: 'GitHub',
  arxiv: 'arXiv',
  hf_models: 'HF 模型',
  hf_papers: 'HF 论文',
  infoq: 'InfoQ',
  kr36: '36氪',
};

const SOURCE_TAG_COLOR: Record<string, string> = {
  hn: 'orange',
  github: 'blue',
  arxiv: 'red',
  hf_models: 'purple',
  hf_papers: 'purple',
  infoq: 'green',
  kr36: 'cyan',
};

const CATEGORY_OPTIONS = [
  { label: '全部', value: '' },
  { label: '新闻', value: 'news' },
  { label: '项目', value: 'project' },
  { label: '论文', value: 'paper' },
  { label: '模型', value: 'model' },
];

const CATEGORY_LABEL: Record<string, string> = {
  news: '新闻',
  project: '项目',
  paper: '论文',
  model: '模型',
};

// --------------------------------------------------------------- 工具函数 ----
function relTime(iso: null | string): string {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '';
  const diff = Date.now() - t;
  const min = Math.floor(diff / 60000);
  if (min < 1) return '刚刚';
  if (min < 60) return `${min} 分钟前`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} 小时前`;
  const d = Math.floor(h / 24);
  return `${d} 天前`;
}

function formatDateTime(iso: null | string): string {
  if (!iso) return '未知';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '未知';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function sourceTagColor(source: string): string {
  return SOURCE_TAG_COLOR[source] ?? 'default';
}

function heatText(item: AiTrendingApi.TrendingItem): string {
  const m = item.heat_meta ?? {};
  if (item.source === 'hn') return `HN ${m.points ?? 0} 分`;
  if (item.source === 'github') return `★ ${m.stars_today ?? m.stars ?? 0}`;
  if (item.source === 'hf_models') return `HF ${m.trendingScore ?? 0}`;
  return `热度 ${item.heat_score}`;
}

/** 某来源（Tab）最近抓取是否失败：失败显示红色警示角标 */
function sourceFailed(key: string): boolean {
  if (!key) return false;
  const ids = key === 'hf' ? ['hf_models', 'hf_papers'] : [key];
  return ids.some((id) => {
    const s = sources.value.find((x) => x.source_id === id);
    return !!s && (s.last_status === 'failed' || s.fail_count > 0);
  });
}

const lastUpdatedText = computed(() => {
  if (lastFetchedAt.value) return relTime(new Date(lastFetchedAt.value).toISOString());
  const times = sources.value
    .map((s) => s.last_fetched_at)
    .filter((t): t is string => !!t);
  if (!times.length) return '暂无数据';
  const latest = times.sort().reverse()[0];
  return latest ? relTime(latest) : '暂无数据';
});

// --------------------------------------------------------------- 数据加载 ----
async function loadList() {
  loading.value = true;
  errorMsg.value = '';
  try {
    pageData.value = await listTrendingItemsApi({
      source: sourceKey.value || undefined,
      category: category.value || undefined,
      sort: sort.value,
      page: page.value,
      page_size: pageSize,
    });
    lastFetchedAt.value = Date.now();
  } catch (e: any) {
    pageData.value = null;
    errorMsg.value = e?.message || '加载失败，请稍后重试';
  } finally {
    loading.value = false;
  }
}

async function loadSources() {
  try {
    sources.value = await getTrendingSourcesApi();
  } catch {
    // 来源状态加载失败不影响列表展示
  }
}

function onSourceChange(key: string | number) {
  sourceKey.value = String(key);
  page.value = 1;
  void loadList();
}

function onCategoryChange(value: string | number) {
  category.value = String(value);
  page.value = 1;
  void loadList();
}

function onSortChange(value: string | number) {
  sort.value = (String(value) as 'heat' | 'time');
  page.value = 1;
  void loadList();
}

function onPageChange(next: number) {
  page.value = next;
  void loadList();
}

async function manualRefresh() {
  refreshing.value = true;
  try {
    const res = await refreshTrendingApi();
    message.success(res?.message || '已触发刷新');
    // 后台全量抓取约 10-30s，延迟 ~5s 后重新拉取列表与来源状态
    setTimeout(() => {
      void Promise.all([loadList(), loadSources()]).finally(() => {
        refreshing.value = false;
      });
    }, 5000);
  } catch (e: any) {
    refreshing.value = false;
    message.error(e?.message || '刷新失败');
  }
}

function openDetail(item: AiTrendingApi.TrendingItem) {
  detailItem.value = item;
  modalOpen.value = true;
}

function openOriginal() {
  if (detailItem.value?.url) window.open(detailItem.value.url, '_blank');
}

onMounted(() => {
  void Promise.all([loadList(), loadSources()]);
});
</script>

<template>
  <Page>
    <div class="mx-auto flex w-full max-w-5xl flex-col gap-4">
      <!-- 顶部标题 + 上次更新 + 手动刷新 -->
      <div class="flex items-center justify-between gap-3">
        <div class="flex items-center gap-2 text-lg font-semibold text-[hsl(var(--foreground))]">
          <Flame class="size-5 text-[hsl(var(--primary))]" />
          AI 开发热点
          <span class="text-xs font-normal text-[hsl(var(--muted-foreground))]">
            上次更新：{{ lastUpdatedText }}
          </span>
        </div>
        <Button type="primary" :loading="refreshing" @click="manualRefresh">
          <RefreshCw class="mr-1 size-4" />
          手动刷新
        </Button>
      </div>

      <!-- 加载失败错误态 -->
      <Alert
        v-if="errorMsg"
        type="error"
        show-icon
        class="rounded-lg"
      >
        <template #message>
          <div class="flex flex-col gap-2">
            <span>加载失败：{{ errorMsg }}</span>
            <span class="text-xs text-[hsl(var(--muted-foreground))]">
              接口暂时不可用（未登录 / 服务重启中），可点击重试或稍后再试。
            </span>
            <div>
              <Button size="small" :loading="loading" @click="loadList">重试</Button>
            </div>
          </div>
        </template>
      </Alert>

      <!-- 来源 Tab + 类型/排序筛选 -->
      <div class="rounded-xl border border-slate-700/50 bg-slate-900/60 p-4 shadow-lg backdrop-blur">
        <Tabs
          :active-key="sourceKey"
          class="!text-[hsl(var(--muted-foreground))]"
          @change="onSourceChange"
        >
          <Tabs.TabPane v-for="tab in SOURCE_TABS" :key="tab.key">
            <template #tab>
              <span class="inline-flex items-center gap-1">
                {{ tab.label }}
                <Badge
                  v-if="sourceFailed(tab.key)"
                  color="red"
                  class="translate-y-[-2px]"
                />
              </span>
            </template>
          </Tabs.TabPane>
        </Tabs>
        <div class="mt-2 flex flex-wrap items-center gap-4 border-t border-slate-700/50 pt-3">
          <Segmented
            :options="CATEGORY_OPTIONS"
            :value="category"
            class="!bg-slate-800"
            @change="onCategoryChange"
          />
          <Segmented
            :options="[
              { label: '热度', value: 'heat' },
              { label: '最新', value: 'time' },
            ]"
            :value="sort"
            class="!bg-slate-800"
            @change="onSortChange"
          />
          <span v-if="pageData" class="text-xs text-[hsl(var(--muted-foreground))]">
            共 {{ pageData.total }} 条
          </span>
        </div>
      </div>

      <!-- 首屏骨架屏 -->
      <Skeleton
        v-if="loading && !pageData"
        active
        :paragraph="{ rows: 6 }"
        class="rounded-xl border border-slate-700/50 bg-slate-900/60 p-5"
      />

      <!-- 列表 -->
      <List
        v-else-if="pageData && pageData.items.length > 0"
        class="rounded-xl border border-slate-700/50 bg-slate-900/60"
        :data-source="pageData.items"
        :loading="loading"
        :pagination="false"
      >
        <template #renderItem="{ item }">
          <List.Item class="!px-5 !py-4">
            <div
              class="flex w-full cursor-pointer flex-col gap-1.5"
              @click="openDetail(item)"
            >
              <div class="flex items-center gap-2">
                <Tag :color="sourceTagColor(item.source)">
                  {{ SOURCE_LABEL[item.source] || item.source }}
                </Tag>
                <Tag v-if="item.category" class="!mr-0">
                  {{ CATEGORY_LABEL[item.category] || item.category }}
                </Tag>
                <span class="min-w-0 flex-1 truncate font-medium text-[hsl(var(--foreground))]">
                  {{ item.title }}
                </span>
              </div>
              <div
                v-if="item.summary"
                class="line-clamp-2 text-xs text-[hsl(var(--muted-foreground))]"
              >
                {{ item.summary }}
              </div>
              <div class="flex items-center gap-3 text-xs text-[hsl(var(--muted-foreground))]">
                <span class="inline-flex items-center gap-1">
                  <Star class="size-3.5 text-yellow-500" />
                  {{ heatText(item) }}
                </span>
                <span>{{ relTime(item.published_at) }}</span>
                <span v-if="item.tags && item.tags.length" class="flex flex-wrap gap-1">
                  <Tag
                    v-for="tag in item.tags.slice(0, 3)"
                    :key="tag"
                    class="!text-[10px] !py-0"
                  >
                    {{ tag }}
                  </Tag>
                </span>
              </div>
            </div>
          </List.Item>
        </template>
      </List>

      <!-- 空态 -->
      <Empty
        v-else-if="!loading && pageData && pageData.items.length === 0"
        class="rounded-xl border border-slate-700/50 bg-slate-900/60 py-16"
      >
        <template #description>
          <div class="flex flex-col items-center gap-3">
            <span class="text-[hsl(var(--foreground))]">暂无热点数据</span>
            <span class="text-xs text-[hsl(var(--muted-foreground))]">
              点击右上角「手动刷新」触发抓取，约 10-30 秒后即可看到最新热点
            </span>
            <Button size="small" ghost :loading="refreshing" @click="manualRefresh">
              <RefreshCw class="mr-1 size-3.5" />
              手动刷新
            </Button>
          </div>
        </template>
      </Empty>

      <!-- 分页 -->
      <div
        v-if="pageData && pageData.total > pageSize"
        class="flex justify-center"
      >
        <Pagination
          :current="page"
          :page-size="pageSize"
          :total="pageData.total"
          :show-size-changer="false"
          @change="onPageChange"
        />
      </div>
    </div>

    <!-- 详情弹窗 -->
    <Modal
      v-model:open="modalOpen"
      :title="detailItem?.title"
      width="680px"
      :footer="null"
    >
      <div v-if="detailItem" class="flex flex-col gap-3 py-2">
        <div class="flex flex-wrap items-center gap-2">
          <Tag :color="sourceTagColor(detailItem.source)">
            {{ SOURCE_LABEL[detailItem.source] || detailItem.source }}
          </Tag>
          <Tag v-if="detailItem.category">
            {{ CATEGORY_LABEL[detailItem.category] || detailItem.category }}
          </Tag>
          <span class="text-xs text-[hsl(var(--muted-foreground))]">
            热度 {{ detailItem.heat_score }} · {{ formatDateTime(detailItem.published_at) }}
          </span>
        </div>
        <div class="rounded-lg bg-slate-800/70 px-3 py-2 text-sm leading-relaxed text-[hsl(var(--foreground))]">
          {{ detailItem.summary || '（无摘要）' }}
        </div>
        <div v-if="detailItem.tags && detailItem.tags.length" class="flex flex-wrap gap-1">
          <Tag v-for="tag in detailItem.tags" :key="tag">{{ tag }}</Tag>
        </div>
        <div class="break-all font-mono text-xs text-[hsl(var(--muted-foreground))]">
          {{ detailItem.url }}
        </div>
        <Button type="primary" block @click="openOriginal">
          跳转原文（新窗口）
        </Button>
      </div>
    </Modal>
  </Page>
</template>
