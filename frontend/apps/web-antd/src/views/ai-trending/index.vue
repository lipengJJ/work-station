<script lang="ts" setup>
import type { AiTrendingApi } from '#/api/core/ai-trending';

import { computed, onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Alert,
  Badge,
  Button,
  Dropdown,
  Empty,
  Input,
  List,
  message,
  Modal,
  Pagination,
  Segmented,
  Select,
  Skeleton,
  Switch,
  Tabs,
  Tag,
} from 'ant-design-vue';
import {
  ArrowLeft,
  Bell,
  Flame,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Settings,
  Star,
} from 'lucide-vue-next';

import {
  createTopicApi,
  deleteTopicApi,
  getTrendingSourcesApi,
  listTopicItemsApi,
  listTopicsApi,
  listTrendingItemsApi,
  refreshTrendingApi,
  runTopicNowApi,
  updateTopicApi,
} from '#/api/core/ai-trending';
import TopicPushConfigModal from './components/TopicPushConfigModal.vue';

// ------------------------------------------------------------- 视图状态 ----
type ViewMode = 'topics' | 'detail' | 'all';
const viewMode = ref<ViewMode>('topics');

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

const INTERVAL_OPTIONS = [
  { value: 15, label: '每 15 分钟' },
  { value: 30, label: '每 30 分钟' },
  { value: 60, label: '每 1 小时' },
  { value: 180, label: '每 3 小时' },
  { value: 360, label: '每 6 小时' },
  { value: 720, label: '每 12 小时' },
  { value: 1440, label: '每天' },
];

const CHANNEL_LABEL: Record<string, string> = {
  wecom: '企业微信',
  dingtalk: '钉钉',
  feishu: '飞书',
  email: '邮件',
};

// ------------------------------------------------------------- 全部热点态 ----
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

// ------------------------------------------------------------- 主题列表态 ----
const topics = ref<AiTrendingApi.Topic[]>([]);
const topicsLoading = ref(false);

// ------------------------------------------------------------- 主题详情态 ----
const selectedTopic = ref<null | AiTrendingApi.Topic>(null);
const detailPage = ref<null | AiTrendingApi.TopicHitPage>(null);
const detailLoading = ref(false);
const detailSort = ref<'heat' | 'time'>('heat');
const detailPageNo = ref(1);
const detailError = ref('');

// ------------------------------------------------------------- 主题弹窗表单 ----
const INTERVAL_DEFAULT = 60;
function defaultTopicForm() {
  return {
    name: '',
    keywords: [] as string[],
    interval_minutes: INTERVAL_DEFAULT,
    enabled: true,
  };
}
const topicModalOpen = ref(false);
const editingTopicId = ref<null | number>(null);
const topicSaving = ref(false);
const topicForm = reactive(defaultTopicForm());

// ------------------------------------------------------------- 推送配置弹窗 ----
const pushModalOpen = ref(false);
const pushModalTopic = ref<null | AiTrendingApi.Topic>(null);

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

// ----------------------------------------------------------- 主题卡片工具 ----
/** 状态点：idle 灰 / running 蓝 / failed 红；停用单独置灰 */
function topicStatusInfo(topic: AiTrendingApi.Topic) {
  if (!topic.enabled) return { label: '已停用', dot: 'bg-slate-500', text: 'text-slate-400' };
  if (topic.status === 'running') return { label: '扫描中', dot: 'bg-blue-400 animate-pulse', text: 'text-blue-300' };
  if (topic.status === 'failed') return { label: '失败', dot: 'bg-rose-500', text: 'text-rose-400' };
  return { label: '就绪', dot: 'bg-slate-400', text: 'text-slate-300' };
}

function frequencyLabel(minutes: number): string {
  return INTERVAL_OPTIONS.find((o) => o.value === minutes)?.label ?? `每 ${minutes} 分钟`;
}

function nextRunText(topic: AiTrendingApi.Topic): string {
  if (!topic.enabled) return '未调度';
  return topic.next_run_at ? relTime(topic.next_run_at) : '未调度';
}

// ------------------------------------------------------------- 主题列表加载 ----
async function loadTopics() {
  topicsLoading.value = true;
  try {
    topics.value = await listTopicsApi();
  } catch (e: any) {
    message.error(`主题列表加载失败：${e?.message || ''}`);
  } finally {
    topicsLoading.value = false;
  }
}

// ------------------------------------------------------------- 主题详情 ----
async function loadSelectedTopic() {
  if (!selectedTopic.value) return;
  try {
    selectedTopic.value = await listTopicsApi().then((list) => {
      const found = list.find((t) => t.id === selectedTopic.value?.id);
      return found ?? selectedTopic.value;
    });
  } catch {
    // 详情头刷新失败不阻塞列表
  }
}

async function loadTopicItems() {
  if (!selectedTopic.value) return;
  detailLoading.value = true;
  detailError.value = '';
  try {
    detailPage.value = await listTopicItemsApi(selectedTopic.value.id, {
      sort: detailSort.value,
      page: detailPageNo.value,
      page_size: pageSize,
    });
  } catch (e: any) {
    detailPage.value = null;
    detailError.value = e?.message || '加载失败，请稍后重试';
  } finally {
    detailLoading.value = false;
  }
}

function openDetail(topic: AiTrendingApi.Topic) {
  selectedTopic.value = topic;
  detailPageNo.value = 1;
  detailSort.value = 'heat';
  viewMode.value = 'detail';
  void loadTopicItems();
  void loadSelectedTopic();
}

function backToTopics() {
  viewMode.value = 'topics';
  selectedTopic.value = null;
  detailPage.value = null;
  void loadTopics();
}

function onDetailSortChange(value: string | number) {
  detailSort.value = String(value) as 'heat' | 'time';
  detailPageNo.value = 1;
  void loadTopicItems();
}

function onDetailPageChange(next: number) {
  detailPageNo.value = next;
  void loadTopicItems();
}

// ------------------------------------------------------------- run-now ----
async function runNow(topic: AiTrendingApi.Topic) {
  try {
    const res = await runTopicNowApi(topic.id);
    message.success(res?.message || '已触发抓取');
    // 后台扫描约 10-30s，延迟轮询刷新状态/命中
    setTimeout(() => {
      void loadTopics();
      if (viewMode.value === 'detail' && selectedTopic.value?.id === topic.id) {
        void loadSelectedTopic();
        void loadTopicItems();
      }
    }, 4000);
  } catch (e: any) {
    message.error(e?.message || '触发失败');
  }
}

// ------------------------------------------------------------- 新建/编辑 ----
function openCreateModal() {
  Object.assign(topicForm, defaultTopicForm());
  editingTopicId.value = null;
  topicModalOpen.value = true;
}

function openEditModal(topic: AiTrendingApi.Topic) {
  Object.assign(topicForm, {
    name: topic.name,
    keywords: [...topic.keywords],
    interval_minutes: topic.interval_minutes,
    enabled: topic.enabled,
  });
  editingTopicId.value = topic.id;
  topicModalOpen.value = true;
}

async function submitTopicForm() {
  if (!topicForm.name.trim()) {
    message.error('请填写主题名称');
    return;
  }
  const keywords = topicForm.keywords.map((k) => k.trim()).filter(Boolean);
  if (!keywords.length) {
    message.error('请至少填写一个关键词');
    return;
  }
  topicSaving.value = true;
  try {
    if (editingTopicId.value) {
      const updated = await updateTopicApi(editingTopicId.value, {
        ...topicForm,
        keywords,
      });
      if (selectedTopic.value?.id === editingTopicId.value) {
        selectedTopic.value = updated;
      }
    } else {
      await createTopicApi({ ...topicForm, keywords });
    }
    topicModalOpen.value = false;
    message.success('已保存');
    void loadTopics();
  } catch (e: any) {
    message.error(e?.message || '保存失败');
  } finally {
    topicSaving.value = false;
  }
}

// ------------------------------------------------------------- 启停/删除 ----
async function toggleEnabled(topic: AiTrendingApi.Topic, enabled: boolean) {
  try {
    const updated = await updateTopicApi(topic.id, { enabled });
    topic.enabled = updated.enabled;
    topic.status = updated.status;
    topic.next_run_at = updated.next_run_at;
    if (selectedTopic.value?.id === topic.id) {
      selectedTopic.value = updated;
    }
  } catch (e: any) {
    message.error(e?.message || '操作失败');
  }
}

function deleteTopic(topic: AiTrendingApi.Topic) {
  Modal.confirm({
    title: '删除主题',
    content: `确定删除主题「${topic.name}」？将同时清空该主题的全部命中记录（不影响全局热点池）。`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      try {
        await deleteTopicApi(topic.id);
        message.success('已删除');
        if (viewMode.value === 'detail' && selectedTopic.value?.id === topic.id) {
          backToTopics();
        } else {
          void loadTopics();
        }
      } catch (e: any) {
        message.error(e?.message || '删除失败');
      }
    },
  });
}

// ------------------------------------------------------------- 推送配置 ----
function openPushConfig(topic: AiTrendingApi.Topic) {
  pushModalTopic.value = topic;
  pushModalOpen.value = true;
}

function onPushSaved() {
  void loadTopics();
  if (selectedTopic.value?.id === pushModalTopic.value?.id) {
    void loadSelectedTopic();
  }
}

// ------------------------------------------------------------- 全部热点 ----
function enterAllView() {
  viewMode.value = 'all';
  page.value = 1;
  void loadList();
}

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
  sort.value = String(value) as 'heat' | 'time';
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

function openDetailItem(item: AiTrendingApi.TrendingItem) {
  detailItem.value = item;
  modalOpen.value = true;
}

function openOriginal() {
  if (detailItem.value?.url) window.open(detailItem.value.url, '_blank');
}

// ----------------------------------------------------------- 共享列表计算 ----
const activePage = computed<null | { items: AiTrendingApi.TrendingItem[]; total: number; page: number; page_size: number }>(
  () => (viewMode.value === 'detail' ? detailPage.value : pageData.value),
);
const activeItems = computed(() => activePage.value?.items ?? []);
const activeLoading = computed(() =>
  viewMode.value === 'detail' ? detailLoading.value : loading.value,
);

function onActivePageChange(next: number) {
  if (viewMode.value === 'detail') onDetailPageChange(next);
  else onPageChange(next);
}

onMounted(() => {
  void Promise.all([loadTopics(), loadSources()]);
});
</script>

<template>
  <Page>
    <div class="flex w-full flex-col gap-4">
      <!-- ===================================================== 主题列表态 -->
      <template v-if="viewMode === 'topics'">
        <div class="flex items-center justify-between gap-3">
          <div class="flex items-center gap-2 text-lg font-semibold text-[hsl(var(--foreground))]">
            <Flame class="size-5 text-[hsl(var(--primary))]" />
            AI 热点主题
            <span class="text-xs font-normal text-[hsl(var(--muted-foreground))]">
              按关键词定向跟踪各源热点
            </span>
          </div>
          <div class="flex items-center gap-2">
            <Button @click="enterAllView">
              <Flame class="mr-1 size-4" />
              全部热点
            </Button>
            <Button type="primary" @click="openCreateModal">
              <Plus class="mr-1 size-4" />
              新建主题
            </Button>
          </div>
        </div>

        <!-- 加载失败错误态 -->
        <Alert
          v-if="errorMsg && viewMode === 'topics'"
          type="error"
          show-icon
          class="rounded-lg"
        >
          <template #message>
            <div class="flex flex-col gap-2">
              <span>加载失败：{{ errorMsg }}</span>
              <div>
                <Button size="small" :loading="topicsLoading" @click="loadTopics">重试</Button>
              </div>
            </div>
          </template>
        </Alert>

        <!-- 主题卡片网格 -->
        <div v-if="topicsLoading && !topics.length" class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          <Skeleton
            v-for="i in 3"
            :key="i"
            active
            :paragraph="{ rows: 4 }"
            class="rounded-xl border border-slate-700/50 bg-slate-900/60 p-4"
          />
        </div>

        <div
          v-else-if="topics.length"
          class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3"
        >
          <div
            v-for="topic in topics"
            :key="topic.id"
            class="cursor-pointer rounded-xl border border-slate-700/50 bg-slate-900/60 p-4 shadow-lg backdrop-blur transition-colors hover:border-slate-500/60"
            @click="openDetail(topic)"
          >
            <div class="flex items-start justify-between gap-2">
              <div class="flex min-w-0 items-center gap-2">
                <span class="mt-1 inline-block size-2 shrink-0 rounded-full" :class="topicStatusInfo(topic).dot" />
                <span class="min-w-0 flex-1 truncate font-medium text-[hsl(var(--foreground))]">
                  {{ topic.name }}
                </span>
              </div>
              <Dropdown>
                <Button size="small" type="text" class="!px-1" @click.stop>
                  <MoreHorizontal class="size-4" />
                </Button>
                <template #overlay>
                  <div class="rounded-lg border border-slate-700/50 bg-slate-900/90 p-1 shadow-xl">
                    <Button size="small" type="text" block class="!text-left" @click.stop="openEditModal(topic)">
                      编辑
                    </Button>
                    <Button size="small" type="text" danger block class="!text-left" @click.stop="deleteTopic(topic)">
                      删除
                    </Button>
                  </div>
                </template>
              </Dropdown>
            </div>

            <!-- 关键词 tags -->
            <div class="mt-2 flex flex-wrap gap-1">
              <Tag v-for="kw in topic.keywords.slice(0, 5)" :key="kw" class="!text-[10px] !py-0">
                {{ kw }}
              </Tag>
              <span
                v-if="topic.keywords.length > 5"
                class="text-[10px] text-[hsl(var(--muted-foreground))]"
              >
                +{{ topic.keywords.length - 5 }}
              </span>
            </div>

            <!-- 元信息 -->
            <div class="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[hsl(var(--muted-foreground))]">
              <span :class="topicStatusInfo(topic).text">{{ topicStatusInfo(topic).label }}</span>
              <span>{{ frequencyLabel(topic.interval_minutes) }}</span>
              <span>命中 {{ topic.hit_count }}</span>
              <span v-if="topic.last_run_at">最近 {{ relTime(topic.last_run_at) }}</span>
              <span>下次 {{ nextRunText(topic) }}</span>
            </div>

            <!-- 推送徽标 + 操作 -->
            <div class="mt-3 flex items-center justify-between gap-2 border-t border-slate-700/50 pt-3">
              <div class="flex items-center gap-2">
                <Switch
                  size="small"
                  :checked="topic.enabled"
                  @click.stop
                  @change="(v: string | number | boolean) => toggleEnabled(topic, Boolean(v))"
                />
                <span
                  v-if="topic.push.enabled"
                  class="inline-flex items-center gap-1 text-xs text-[hsl(var(--primary))]"
                >
                  <Bell class="size-3" />
                  {{ CHANNEL_LABEL[topic.push.channel] || topic.push.channel }}推送
                </span>
                <span v-else class="text-xs text-[hsl(var(--muted-foreground))]">
                  {{ topic.enabled ? '已启用' : '已停用' }}
                </span>
              </div>
              <div class="flex items-center gap-1">
                <Button size="small" @click.stop="() => runNow(topic)">
                  <RefreshCw class="mr-1 size-3" />
                  立即抓取
                </Button>
                <Button size="small" @click.stop="() => openPushConfig(topic)">
                  <Settings class="mr-1 size-3" />
                  推送配置
                </Button>
              </div>
            </div>
          </div>
        </div>

        <!-- 空态 -->
        <Empty v-else-if="!topicsLoading" class="rounded-xl border border-slate-700/50 bg-slate-900/60 py-16">
          <template #description>
            <div class="flex flex-col items-center gap-3">
              <span class="text-[hsl(var(--foreground))]">还没有跟踪主题</span>
              <span class="text-xs text-[hsl(var(--muted-foreground))]">
                新建主题后，系统会按关键词定向检索各源热点并自动汇总
              </span>
              <Button type="primary" @click="openCreateModal">
                <Plus class="mr-1 size-4" />
                新建主题
              </Button>
            </div>
          </template>
        </Empty>
      </template>

      <!-- ===================================================== 主题详情态 -->
      <template v-else-if="viewMode === 'detail'">
        <!-- 返回 + 主题信息头 -->
        <div class="rounded-xl border border-slate-700/50 bg-slate-900/60 p-4 shadow-lg backdrop-blur">
          <div class="flex items-center justify-between gap-3">
            <Button size="small" @click="backToTopics">
              <ArrowLeft class="mr-1 size-4" />
              返回主题列表
            </Button>
            <Button size="small" @click="selectedTopic && openPushConfig(selectedTopic)">
              <Settings class="mr-1 size-3" />
              推送配置
            </Button>
          </div>
          <div v-if="selectedTopic" class="mt-3 flex flex-col gap-2">
            <div class="flex flex-wrap items-center gap-2">
              <span class="inline-block size-2 rounded-full" :class="topicStatusInfo(selectedTopic).dot" />
              <span class="text-lg font-semibold text-[hsl(var(--foreground))]">
                {{ selectedTopic.name }}
              </span>
              <Tag v-if="!selectedTopic.enabled">已停用</Tag>
              <Tag
                v-if="selectedTopic.push.enabled"
                color="green"
                class="inline-flex items-center gap-1"
              >
                <Bell class="size-3" />
                {{ CHANNEL_LABEL[selectedTopic.push.channel] || selectedTopic.push.channel }}推送
              </Tag>
            </div>
            <div class="flex flex-wrap gap-1">
              <Tag v-for="kw in selectedTopic.keywords" :key="kw" class="!text-[10px] !py-0">
                {{ kw }}
              </Tag>
            </div>
            <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[hsl(var(--muted-foreground))]">
              <span :class="topicStatusInfo(selectedTopic).text">{{ topicStatusInfo(selectedTopic).label }}</span>
              <span>{{ frequencyLabel(selectedTopic.interval_minutes) }}</span>
              <span>命中 {{ selectedTopic.hit_count }}</span>
              <span v-if="selectedTopic.last_run_at">最近抓取 {{ formatDateTime(selectedTopic.last_run_at) }}</span>
              <span v-if="selectedTopic.last_run_message">{{ selectedTopic.last_run_message }}</span>
            </div>
            <div class="flex items-center gap-2">
              <Button size="small" type="primary" @click="runNow(selectedTopic)">
                <RefreshCw class="mr-1 size-3" />
                立即抓取
              </Button>
            </div>
          </div>
        </div>

        <!-- 详情排序 -->
        <div class="flex flex-wrap items-center justify-between gap-3">
          <Segmented
            :options="[
              { label: '热度', value: 'heat' },
              { label: '最新', value: 'time' },
            ]"
            :value="detailSort"
            class="!bg-slate-800"
            @change="onDetailSortChange"
          />
          <span v-if="detailPage" class="text-xs text-[hsl(var(--muted-foreground))]">
            共 {{ detailPage.total }} 条
          </span>
        </div>

        <Alert v-if="detailError" type="error" show-icon class="rounded-lg">
          <template #message>
            <div class="flex flex-col gap-2">
              <span>加载失败：{{ detailError }}</span>
              <div>
                <Button size="small" :loading="detailLoading" @click="loadTopicItems">重试</Button>
              </div>
            </div>
          </template>
        </Alert>
      </template>

      <!-- ===================================================== 全部热点态 -->
      <template v-else>
        <div class="flex items-center justify-between gap-3">
          <div class="flex items-center gap-2 text-lg font-semibold text-[hsl(var(--foreground))]">
            <Button size="small" @click="backToTopics">
              <ArrowLeft class="mr-1 size-4" />
              返回主题
            </Button>
            <Flame class="size-5 text-[hsl(var(--primary))]" />
            全部热点
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
      </template>

      <!-- ===================================================== 共享热点列表（详情态 + 全部热点态） -->
      <template v-if="viewMode !== 'topics'">
        <!-- 首屏骨架屏 -->
        <Skeleton
          v-if="activeLoading && !activePage"
          active
          :paragraph="{ rows: 6 }"
          class="rounded-xl border border-slate-700/50 bg-slate-900/60 p-5"
        />

        <!-- 列表 -->
        <List
          v-else-if="activeItems.length > 0"
          class="rounded-xl border border-slate-700/50 bg-slate-900/60"
          :data-source="activeItems"
          :loading="activeLoading"
          :pagination="false"
        >
          <template #renderItem="{ item }">
            <List.Item class="!px-5 !py-4">
              <div
                class="flex w-full cursor-pointer flex-col gap-1.5"
                @click="openDetailItem(item)"
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
          v-else-if="!activeLoading && activePage && activeItems.length === 0"
          class="rounded-xl border border-slate-700/50 bg-slate-900/60 py-16"
        >
          <template #description>
            <div class="flex flex-col items-center gap-3">
              <span class="text-[hsl(var(--foreground))]">
                {{ viewMode === 'detail' ? '该主题暂无命中热点' : '暂无热点数据' }}
              </span>
              <span class="text-xs text-[hsl(var(--muted-foreground))]">
                {{
                  viewMode === 'detail'
                    ? '点击「立即抓取」触发定向检索，约 10-30 秒后即可看到最新命中'
                    : '点击右上角「手动刷新」触发抓取，约 10-30 秒后即可看到最新热点'
                }}
              </span>
              <Button
                v-if="viewMode === 'detail' && selectedTopic"
                size="small"
                type="primary"
                @click="runNow(selectedTopic)"
              >
                <RefreshCw class="mr-1 size-3.5" />
                立即抓取
              </Button>
              <Button
                v-else
                size="small"
                ghost
                :loading="refreshing"
                @click="manualRefresh"
              >
                <RefreshCw class="mr-1 size-3.5" />
                手动刷新
              </Button>
            </div>
          </template>
        </Empty>

        <!-- 分页 -->
        <div
          v-if="activePage && activePage.total > activePage.page_size"
          class="flex justify-center"
        >
          <Pagination
            :current="activePage.page"
            :page-size="activePage.page_size"
            :total="activePage.total"
            :show-size-changer="false"
            @change="onActivePageChange"
          />
        </div>
      </template>
    </div>

    <!-- 热点条目详情弹窗 -->
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

    <!-- 新建/编辑主题弹窗 -->
    <Modal
      v-model:open="topicModalOpen"
      :title="editingTopicId ? '编辑主题' : '新建主题'"
      width="520px"
      :confirm-loading="topicSaving"
      ok-text="保存"
      cancel-text="取消"
      @ok="submitTopicForm"
    >
      <div class="flex flex-col gap-4 py-2">
        <div>
          <div class="mb-1 text-xs text-[hsl(var(--muted-foreground))]">主题名称</div>
          <Input
            v-model:value="topicForm.name"
            placeholder="如：AI Agent、大模型开源"
            :maxlength="128"
            allow-clear
          />
        </div>
        <div>
          <div class="mb-1 text-xs text-[hsl(var(--muted-foreground))]">
            关键词（任一命中即算，最多 20 个）
          </div>
          <Select
            v-model:value="topicForm.keywords"
            mode="tags"
            :token-separators="[',', '，', ' ']"
            placeholder="输入关键词后回车，如：大模型"
            class="w-full"
            allow-clear
          />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <div class="mb-1 text-xs text-[hsl(var(--muted-foreground))]">抓取频率</div>
            <Select
              v-model:value="topicForm.interval_minutes"
              :options="INTERVAL_OPTIONS"
              class="w-full"
            />
          </div>
          <div>
            <div class="mb-1 text-xs text-[hsl(var(--muted-foreground))]">启用</div>
            <Switch v-model:checked="topicForm.enabled" />
          </div>
        </div>
      </div>
    </Modal>

    <!-- 推送配置弹窗 -->
    <TopicPushConfigModal
      v-model:open="pushModalOpen"
      :topic-id="pushModalTopic?.id ?? 0"
      :topic-name="pushModalTopic?.name ?? ''"
      @saved="onPushSaved"
    />
  </Page>
</template>
