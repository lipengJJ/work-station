<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';

import { message, Modal, Select, Tooltip } from 'ant-design-vue';
import { Copy, ExternalLink, RefreshCw, Rss, Search, X } from 'lucide-vue-next';

import { listRsshubNamespacesApi, listRsshubRoutesApi } from '#/api/core/hotlist';

// 本机 RSSHub 默认地址（见 ../../../rsshub/docker-compose.yml），只用来拼「完整订阅地址」
// 给用户复制，不影响接口请求本身——列表数据始终走后端 /api/hotlist/rsshub/* 代理。
const RSSHUB_BASE_URL = 'http://localhost:1200';

const CATEGORY_LABELS: Record<string, string> = {
  anime: '动漫',
  bbs: '论坛',
  blog: '博客',
  design: '设计',
  finance: '财经',
  forecast: '天气',
  game: '游戏',
  government: '政务',
  journal: '期刊',
  live: '直播',
  multimedia: '多媒体',
  'new-media': '新媒体',
  other: '其他',
  picture: '图片',
  'program-update': '软件更新',
  programming: '编程',
  reading: '阅读',
  shopping: '购物',
  'social-media': '社交媒体',
  sport: '体育',
  study: '学习',
  'traditional-media': '传统媒体',
  travel: '旅行',
  university: '高校',
};
function categoryLabel(c: string) {
  return CATEGORY_LABELS[c] || c;
}

// -------------------------------------------------------------- 站点图标 ----
// 试过直接热链各站点自己的 favicon.ico：并发对 20 个不同域名发请求很不稳定
// （不少站点的 favicon 请求被当成爬虫流量拦截返回 503，一度还把标签页拖到卡死），
// RSSHub 的 /api/namespace 本身也不带图标字段。改用零网络请求的色块首字母头像——
// 颜色由站点 key 哈希决定，同一个站点每次颜色都一样，纯本地生成，稳定不出错。
const AVATAR_COLORS = [
  '#f56a6a', '#f2994a', '#e0b32e', '#6fcf72', '#3fb6a8',
  '#4a9de8', '#7c6cf0', '#b56cf0', '#e868a8', '#7a8699',
];
function avatarColor(key: string) {
  let hash = 0;
  for (const ch of key) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}

function copyText(text: string) {
  navigator.clipboard?.writeText(text).then(
    () => message.success('已复制'),
    () => message.warning('复制失败，请手动复制'),
  );
}

// -------------------------------------------------------------- 搜索 / 筛选 ----
const searchQuery = ref('');
const debouncedSearchQuery = ref('');
let searchDebounceTimer: ReturnType<typeof setTimeout> | undefined;

watch(searchQuery, (v) => {
  clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => {
    debouncedSearchQuery.value = v.trim();
  }, 300);
});
function commitSearchNow() {
  clearTimeout(searchDebounceTimer);
  debouncedSearchQuery.value = searchQuery.value.trim();
}
function clearSearch() {
  searchQuery.value = '';
  commitSearchNow();
}

const categoryFilter = ref<string>('');
const allCategories = ref<string[]>([]);
const categoryOptions = computed(() => [
  { value: '', label: '全部分类' },
  ...allCategories.value.map((c) => ({ value: c, label: categoryLabel(c) })),
]);

// -------------------------------------------------------------- 站点列表 ----
const page = ref(1);
const pageSize = 20;
const total = ref(0);
const namespaces = ref<HotlistApi.RsshubNamespace[]>([]);
const loading = ref(false);
const loadError = ref('');
const fetchedAt = ref<null | number>(null);

async function fetchNamespaces(opts: { refresh?: boolean } = {}) {
  loading.value = true;
  loadError.value = '';
  try {
    const result = await listRsshubNamespacesApi({
      keyword: debouncedSearchQuery.value || undefined,
      category: categoryFilter.value || undefined,
      page: page.value,
      page_size: pageSize,
      refresh: opts.refresh || undefined,
    });
    namespaces.value = result.items;
    total.value = result.total;
    allCategories.value = result.categories;
    fetchedAt.value = result.fetched_at;
  } catch (e: any) {
    loadError.value = e.response?.data?.detail || e.message;
    namespaces.value = [];
    total.value = 0;
  } finally {
    loading.value = false;
  }
}

watch([debouncedSearchQuery, categoryFilter], () => {
  page.value = 1;
  fetchNamespaces();
});
watch(page, () => fetchNamespaces());

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
function goPage(p: number) {
  if (p < 1 || p > totalPages.value) return;
  page.value = p;
}

const refreshing = ref(false);
async function manualRefresh() {
  refreshing.value = true;
  try {
    await fetchNamespaces({ refresh: true });
    message.success('目录已刷新');
  } finally {
    refreshing.value = false;
  }
}

function formatFetchedAt(ts: null | number) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString();
}

onMounted(() => {
  fetchNamespaces();
});
onBeforeUnmount(() => {
  clearTimeout(searchDebounceTimer);
});

// -------------------------------------------------------------- 站点详情：路由列表 ----
const detailOpen = ref(false);
const detailLoading = ref(false);
const detailError = ref('');
const detailNamespace = ref<HotlistApi.RsshubNamespace | null>(null);
const detailRoutes = ref<HotlistApi.RsshubRoute[]>([]);

async function openNamespace(ns: HotlistApi.RsshubNamespace) {
  detailOpen.value = true;
  detailLoading.value = true;
  detailError.value = '';
  detailNamespace.value = ns;
  detailRoutes.value = [];
  try {
    const result = await listRsshubRoutesApi({ namespace: ns.namespace, page_size: 200 });
    detailRoutes.value = result.items;
  } catch (e: any) {
    detailError.value = e.response?.data?.detail || e.message;
  } finally {
    detailLoading.value = false;
  }
}
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-background-deep p-6 lg:p-8 select-none">
      <!-- 页头 -->
      <div class="fade-up mb-5 flex shrink-0 items-start gap-3">
        <div
          class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-primary/50 text-primary-foreground shadow-sm"
        >
          <Rss class="size-5" />
        </div>
        <div>
          <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-primary">RSSHub · Sites</p>
          <h1 class="display-font mt-1 text-3xl font-black tracking-tight text-foreground sm:text-4xl">
            RSSHub 路由
          </h1>
          <p class="mt-1.5 text-sm text-muted-foreground">
            浏览本机 RSSHub（{{ RSSHUB_BASE_URL }}）支持的站点，点开看具体路由，挑地址去「新建 RSS 源」订阅
          </p>
        </div>
      </div>

      <!-- 搜索行 -->
      <div class="fade-up mb-6 flex shrink-0 flex-col gap-3 lg:flex-row lg:items-stretch" style="animation-delay: 60ms">
        <div class="relative min-w-[280px] flex-1 lg:min-w-[360px]">
          <Search class="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索站点名称或 key…"
            class="h-12 w-full rounded-2xl border border-border bg-card pl-11 pr-10 text-sm text-foreground shadow-sm outline-none placeholder:text-muted-foreground focus:border-primary"
            @keyup.enter="commitSearchNow"
          />
          <button
            v-if="searchQuery"
            class="absolute right-3.5 top-1/2 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
            @click="clearSearch"
          >
            <X class="size-4" />
          </button>
        </div>
        <div class="flex flex-wrap items-center gap-2 lg:shrink-0">
          <Select v-model:value="categoryFilter" class="w-36" :options="categoryOptions" />
          <Tooltip :title="`目录缓存于 ${formatFetchedAt(fetchedAt)}，30 分钟自动更新`">
            <button
              :disabled="refreshing"
              class="flex h-12 items-center gap-1.5 rounded-2xl border border-border bg-card px-4 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
              @click="manualRefresh"
            >
              <RefreshCw class="size-3.5" :class="{ 'animate-spin': refreshing }" />
              刷新目录
            </button>
          </Tooltip>
        </div>
      </div>

      <!-- 站点表格 -->
      <div class="fade-up shrink-0 overflow-hidden rounded-2xl border border-border bg-card shadow-sm" style="animation-delay: 300ms">
        <div v-if="loadError" class="flex flex-col items-center justify-center gap-3 p-16 text-center">
          <div class="flex size-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
            <Rss class="size-5" />
          </div>
          <p class="text-sm font-medium text-foreground">加载失败</p>
          <p class="max-w-md text-xs text-muted-foreground">{{ loadError }}</p>
          <p class="text-xs text-muted-foreground">
            请确认本机 RSSHub 已启动（<code class="rounded bg-muted px-1 py-0.5">./start.sh</code> 会自动拉起）
          </p>
        </div>
        <div v-else-if="!loading && namespaces.length === 0" class="flex flex-col items-center justify-center gap-3 p-16 text-center">
          <div class="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
            <Rss class="size-5" />
          </div>
          <template v-if="debouncedSearchQuery || categoryFilter">
            <p class="text-sm font-medium text-foreground">没有找到匹配的站点</p>
            <button class="text-xs text-primary hover:underline" @click="clearSearch">清空搜索</button>
          </template>
          <template v-else>
            <p class="text-sm font-medium text-foreground">暂无数据</p>
          </template>
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="border-b border-border bg-muted/50 text-[11px] font-medium text-muted-foreground">
              <tr>
                <th class="px-4 py-3">站点</th>
                <th class="px-4 py-3">站点地址</th>
                <th class="px-4 py-3">路由数</th>
                <th class="px-4 py-3">分类</th>
                <th class="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              <tr
                v-for="ns in namespaces"
                :key="ns.namespace"
                class="cursor-pointer transition-colors hover:bg-accent/60"
                @click="openNamespace(ns)"
              >
                <td class="px-4 py-3">
                  <div class="flex items-center gap-2.5">
                    <div
                      class="flex size-6 shrink-0 items-center justify-center rounded-lg text-[11px] font-bold text-white"
                      :style="{ backgroundColor: avatarColor(ns.namespace) }"
                    >
                      {{ ns.namespace_name.slice(0, 1).toUpperCase() }}
                    </div>
                    <div>
                      <div class="font-medium text-foreground">{{ ns.namespace_name }}</div>
                      <div class="mt-0.5 font-mono text-[10px] text-muted-foreground">{{ ns.namespace }}</div>
                    </div>
                  </div>
                </td>
                <td class="px-4 py-3 text-muted-foreground">{{ ns.url || '—' }}</td>
                <td class="px-4 py-3 font-mono font-semibold text-foreground">{{ ns.route_count }}</td>
                <td class="px-4 py-3">
                  <div class="flex flex-wrap gap-1">
                    <span
                      v-for="c in ns.categories"
                      :key="c"
                      class="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary"
                    >
                      {{ categoryLabel(c) }}
                    </span>
                  </div>
                </td>
                <td class="px-4 py-3 text-right">
                  <span class="rounded-full px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary">
                    查看路由
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 分页 -->
      <div
        v-if="total > pageSize"
        class="fade-up mt-5 flex shrink-0 items-center justify-between text-xs text-muted-foreground"
        style="animation-delay: 360ms"
      >
        <span>共 {{ total }} 个站点</span>
        <div class="flex items-center gap-2">
          <button
            class="rounded-full border border-border bg-card px-3 py-1 transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="page <= 1"
            @click="goPage(page - 1)"
          >
            上一页
          </button>
          <span class="font-mono">{{ page }} / {{ totalPages }}</span>
          <button
            class="rounded-full border border-border bg-card px-3 py-1 transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="page >= totalPages"
            @click="goPage(page + 1)"
          >
            下一页
          </button>
        </div>
      </div>
    </div>

    <!-- 站点详情：该站点下的路由列表 -->
    <Modal v-model:open="detailOpen" :footer="null" width="820px">
      <template #title>
        <div v-if="detailNamespace" class="flex items-center gap-2">
          <div
            class="flex size-6 shrink-0 items-center justify-center rounded-lg text-[11px] font-bold text-white"
            :style="{ backgroundColor: avatarColor(detailNamespace.namespace) }"
          >
            {{ detailNamespace.namespace_name.slice(0, 1).toUpperCase() }}
          </div>
          <span>{{ detailNamespace.namespace_name }} · {{ detailNamespace.namespace }}</span>
        </div>
        <span v-else>路由</span>
      </template>
      <div v-if="detailLoading" class="py-8 text-center text-xs text-muted-foreground">加载中…</div>
      <div v-else-if="detailError" class="py-8 text-center text-xs text-destructive">{{ detailError }}</div>
      <div v-else class="max-h-[60vh] overflow-y-auto">
        <div
          v-for="route in detailRoutes"
          :key="route.full_path"
          class="border-b border-border py-3 last:border-b-0"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="text-sm font-medium text-foreground">{{ route.name }}</div>
              <div class="mt-0.5 font-mono text-[11px] text-muted-foreground">{{ route.full_path }}</div>
              <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
                <code class="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground">{{ route.example }}</code>
                <span
                  v-for="c in route.categories"
                  :key="c"
                  class="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary"
                >
                  {{ categoryLabel(c) }}
                </span>
                <span
                  v-for="cfg in route.require_config"
                  :key="cfg"
                  class="rounded-full bg-warning/15 px-2 py-0.5 font-mono text-[10px] font-medium text-warning"
                >
                  {{ cfg }}
                </span>
              </div>
              <div class="mt-1 text-[10px] text-muted-foreground">维护者：{{ route.maintainers.join(', ') || '—' }}</div>
            </div>
            <Tooltip title="复制完整订阅地址">
              <button
                class="shrink-0 rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                @click="copyText(`${RSSHUB_BASE_URL}${route.example}`)"
              >
                <Copy class="size-3.5" />
              </button>
            </Tooltip>
          </div>
        </div>
      </div>
      <div v-if="detailNamespace?.url" class="mt-3 flex items-center gap-1 text-[11px] text-muted-foreground">
        <ExternalLink class="size-3" />
        原站：{{ detailNamespace.url }}
      </div>
    </Modal>
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
