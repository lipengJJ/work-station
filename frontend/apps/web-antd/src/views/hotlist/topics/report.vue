<script lang="ts" setup>
import type { TopicsApi } from '#/api/core/topics';

import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';

import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Empty,
  message,
  Spin,
  Statistic,
  Table,
  Tag,
  Tooltip,
} from 'ant-design-vue';
import { ArrowLeft, FileText, RefreshCw, Send, UploadCloud } from 'lucide-vue-next';

import {
  getReportApi,
  getReportCandidatesApi,
  notifyReportApi,
  publishReportApi,
} from '#/api/core/topics';
import { buildToc, escapeHtml, makeLinkify, parseSections, renderBody } from '#/views/hotlist/shared/reportContent';

const route = useRoute();
const router = useRouter();
// 路由参数可能是 "undefined"/空/重复段，Number() 会得到 NaN——非法 id 直接回主题列表，
// 避免把 /reports/NaN 发到后端触发「unable to parse string as an integer」
const reportId = computed(() => {
  const raw = route.params.reportId;
  const n = Array.isArray(raw) ? Number(raw[0]) : Number(raw);
  return Number.isInteger(n) && n > 0 ? n : 0;
});

function backToTopics() {
  router.replace('/hotlist/topics');
}

const report = ref<TopicsApi.ReportDetail | null>(null);
const loading = ref(true);
const publishLoading = ref(false);
const notifyLoading = ref(false);
const candidatesOpen = ref(false);
const candidates = ref<TopicsApi.Candidate[]>([]);
const candidatesLoading = ref(false);
const candidatesTotal = ref(0);

const itemsById = computed(() => {
  const map = new Map<number, TopicsApi.ReportItemRef>();
  for (const item of report.value?.items || []) map.set(item.id, item);
  return map;
});

function formatDateTime(iso: null | string) {
  if (!iso) return '—';
  return iso.slice(0, 16).replace('T', ' ');
}

function coverageHint(coverage: number) {
  if (coverage < 0.05) return '引用覆盖率过低：AI 淹没在噪音里，建议调低 max_items 或收紧源';
  if (coverage > 0.6) return '引用覆盖率偏高：考虑调高 shortlist_size';
  return '覆盖率正常';
}

// -------------------------------------------------------------- 加载 ----
async function fetchReport() {
  if (reportId.value === 0) {
    message.warning('报告 id 无效，已返回主题列表');
    backToTopics();
    return;
  }
  loading.value = true;
  try {
    report.value = await getReportApi(reportId.value);
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    loading.value = false;
  }
}

// -------------------------------------------------------------- 操作 ----
async function publish() {
  publishLoading.value = true;
  try {
    const res = await publishReportApi(reportId.value);
    if (res.ok) {
      message.success('发布成功');
      fetchReport();
    } else {
      message.error(`发布失败：${res.error}`);
      fetchReport();
    }
  } catch (e: any) {
    message.error(`发布失败：${e.message}`);
  } finally {
    publishLoading.value = false;
  }
}

async function notify() {
  notifyLoading.value = true;
  try {
    const res = await notifyReportApi(reportId.value);
    if (res.ok) {
      message.success(res.message);
    } else {
      message.warning(res.message);
    }
  } catch (e: any) {
    message.error(`推送失败：${e.message}`);
  } finally {
    notifyLoading.value = false;
  }
}

async function openCandidates() {
  candidatesOpen.value = true;
  candidatesLoading.value = true;
  try {
    const res = await getReportCandidatesApi(reportId.value);
    candidates.value = res.items;
    candidatesTotal.value = res.total_unreferenced;
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    candidatesLoading.value = false;
  }
}

// -------------------------------------------------------------- markdown ----
// 解析/渲染逻辑抽到了 shared/reportContent.ts（跟「日报」读者视图共用同一份）。
const linkify = computed(() => makeLinkify(itemsById.value));
const parsedSections = computed(() => parseSections(report.value?.content_md || ''));
const bodyHtml = computed(() => renderBody(parsedSections.value, linkify.value));
const highlightHtmlList = computed(() =>
  (report.value?.highlights || []).map((h) => linkify.value(escapeHtml(h))),
);
const toc = computed(() => buildToc(parsedSections.value));
const tocTotalArticles = computed(() => toc.value.reduce((sum, r) => sum + r.count, 0));

// 条目状态：新出现 / 持续 / 已消退（相对上一期）
function itemStatus(item: TopicsApi.ReportItemRef): null | 'new' | 'kept' {
  if (!report.value?.prev_item_ids?.length) return null;
  if (!report.value.prev_item_ids.includes(item.id)) return 'new';
  return 'kept';
}

const candidateColumns = [
  { title: '标题', dataIndex: 'title', key: 'title' },
  { title: '来源', dataIndex: 'source_name', key: 'source_name', width: 140 },
  { title: '权重', dataIndex: 'weight', key: 'weight', width: 80 },
];

onMounted(fetchReport);
</script>

<template>
  <Page>
    <template #title>
      <div class="flex items-center gap-2">
        <Button type="text" class="!px-1" @click="router.back()">
          <template #icon><ArrowLeft class="size-4" /></template>
        </Button>
        <span>{{ report?.topic_name || '报告' }} · {{ report?.period_key || '…' }}</span>
        <Tag v-if="report" :color="report.status === 'success' ? 'green' : report.status === 'running' ? 'processing' : 'error'">
          {{ report.status === 'success' ? '成功' : report.status === 'running' ? '生成中' : '失败' }}
        </Tag>
      </div>
    </template>

    <Spin :spinning="loading">
      <template v-if="report">
        <!-- 失败状态 -->
        <Alert
          v-if="report.status === 'failed'"
          type="error"
          show-icon
          class="mb-4"
          message="报告生成失败"
          :description="report.error || '未知错误'"
        />

        <!-- 顶部信息条 -->
        <div v-if="report.status === 'success'" class="mb-4">
          <div class="mb-2 flex flex-wrap items-center gap-2">
            <Button type="primary" :loading="publishLoading" @click="publish">
              <template #icon><UploadCloud class="size-4" /></template>
              {{ report.publish_status === 'success' ? '重新发布' : '发布到对象存储' }}
            </Button>
            <Button :loading="notifyLoading" @click="notify">
              <template #icon><Send class="size-4" /></template>
              重新推送摘要
            </Button>
            <Button @click="fetchReport">
              <template #icon><RefreshCw class="size-4" /></template>
              刷新
            </Button>
            <Tag v-if="report.publish_status === 'success'" color="green">已发布</Tag>
            <Tag v-else-if="report.publish_status === 'failed'" color="red">发布失败</Tag>
          </div>
          <Alert
            v-if="report.publish_status === 'failed'"
            type="warning"
            show-icon
            message="发布失败不影响报告阅读"
            :description="report.error || '检查 S3 配置（系统设置 → API 配置 → hotlist_s3_*）'"
          />
        </div>

        <!-- 概要 -->
        <div v-if="report.status === 'success'" class="mb-4 grid grid-cols-2 gap-4 md:grid-cols-4">
          <div class="rounded-lg border border-border/60 p-3">
            <Statistic title="候选条目" :value="report.candidate_ids.length" />
          </div>
          <div class="rounded-lg border border-border/60 p-3">
            <Statistic title="引用条目" :value="report.item_ids.length" />
          </div>
          <div class="rounded-lg border border-border/60 p-3">
            <Tooltip :title="coverageHint(report.coverage)">
              <Statistic title="引用覆盖率" :value="report.coverage * 100" :precision="1" suffix="%" />
            </Tooltip>
          </div>
          <div class="rounded-lg border border-border/60 p-3">
            <Statistic
              title="AI 成本"
              :value="report.ai_call_count"
              suffix="次"
              :formatter="() => `${report!.prompt_tokens + report!.completion_tokens} tok · ${report!.ai_call_count} 次`"
            />
          </div>
        </div>

        <!-- 核心结论 -->
        <div
          v-if="report.highlights.length > 0"
          class="mb-4 rounded-lg border border-primary/30 bg-primary/5 p-4"
        >
          <div class="mb-2 text-sm font-semibold text-primary">核心结论</div>
          <ul class="space-y-2">
            <!-- eslint-disable-next-line vue/no-v-html -- 引用 [n] 需要渲染成可点击的站内链接，跟正文用同一套 linkify -->
            <li v-for="(h, i) in highlightHtmlList" :key="i" class="text-sm leading-relaxed" v-html="h"></li>
          </ul>
        </div>

        <!-- 今日看点：分类总览，数字编号 + 篇数 + 首条标题预览 -->
        <div v-if="toc.length > 0" class="mb-4 rounded-lg border border-border/60 p-4">
          <div class="mb-3 flex items-center justify-between">
            <span class="text-sm font-semibold">今日看点</span>
            <span class="text-xs text-muted-foreground">{{ tocTotalArticles }} 篇报道</span>
          </div>
          <div>
            <div
              v-for="row in toc"
              :key="row.index"
              class="toc-row"
            >
              <span class="toc-index">{{ row.index }}</span>
              <div class="toc-body">
                <div class="toc-name">
                  <span class="font-semibold">{{ row.name }}</span>
                  <span class="toc-count">{{ row.count }}</span>
                </div>
                <div class="toc-preview">{{ row.preview }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 正文 -->
        <!-- eslint-disable-next-line vue/no-v-html -- 报告正文是本站按固定模板生成的可信内容 -->
        <div class="markdown-body prose prose-sm dark:prose-invert max-w-none prose-img:rounded-md" v-html="bodyHtml"></div>

        <!-- 引用条目 -->
        <div v-if="report.status === 'success'" class="mt-8">
          <div class="mb-2 flex items-center justify-between">
            <span class="text-sm font-semibold">引用条目（{{ report.items.length }}）</span>
            <Button size="small" type="link" @click="openCandidates">
              漏检抽查（未入选 {{ report.candidate_ids.length - report.item_ids.length }} 条）
            </Button>
          </div>
          <Table
            :data-source="report.items"
            :pagination="false"
            size="small"
            row-key="id"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'title'">
                <a
                  :href="`/hotlist/items/${record.id}`"
                  target="_blank"
                  rel="noopener"
                  class="inline-flex items-center gap-1"
                >
                  {{ record.title }}
                  <FileText class="size-3 text-foreground/40" />
                </a>
                <Tag v-if="itemStatus(record as TopicsApi.ReportItemRef) === 'new'" color="blue" class="ml-2">新出现</Tag>
                <Tag v-else-if="itemStatus(record as TopicsApi.ReportItemRef) === 'kept'" color="default" class="ml-2">持续</Tag>
              </template>
            </template>
            <Table.Column key="title" title="标题" data-index="title" />
            <Table.Column key="source" title="来源" data-index="source_name" width="140" />
            <Table.Column key="weight" title="权重" data-index="weight" width="90" />
          </Table>
        </div>

        <!-- 元信息 -->
        <Descriptions class="mt-8" size="small" :column="4" bordered>
          <Descriptions.Item label="策略">{{ report.strategy }}</Descriptions.Item>
          <Descriptions.Item label="Skill">{{ report.skill_key || '内置 Prompt' }}</Descriptions.Item>
          <Descriptions.Item label="模型">{{ report.model || '—' }}</Descriptions.Item>
          <Descriptions.Item label="生成时间">{{ formatDateTime(report.created_at) }}</Descriptions.Item>
        </Descriptions>
      </template>
      <Empty v-else-if="!loading" description="报告不存在" />
    </Spin>

    <!-- 漏检抽查抽屉 -->
    <Drawer
      v-model:open="candidatesOpen"
      title="漏检抽查"
      width="560"
      :extra="`未入选共 ${candidatesTotal} 条 · 随机抽样 ${candidates.length} 条`"
    >
      <Alert
        class="mb-4"
        type="info"
        show-icon
        message="随机抽样的未入选条目，人工判断有没有该进而没进的"
      />
      <Spin :spinning="candidatesLoading">
        <Table
          v-if="candidates.length > 0"
          :data-source="candidates"
          :columns="candidateColumns"
          :pagination="false"
          size="small"
          row-key="id"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'title'">
              <a :href="`/hotlist/items/${record.id}`" target="_blank" rel="noopener">
                {{ record.title }}
              </a>
            </template>
          </template>
        </Table>
        <Empty v-else-if="!candidatesLoading" description="本期没有未入选条目" />
      </Spin>
    </Drawer>
  </Page>
</template>

<style scoped>
/* 段落/列表/引用块/代码/图片这些通用排版交给 prose（@tailwindcss/typography，
   见 internal/tailwind-config/src/theme.css）统一兜底，这里只保留跟 prose 默认
   样式不一样的、有意做的定制：h2/h3 的独立视觉分量，以及下面全是本站自创、
   prose 完全不认识的类（section-header/article-card/source-tag/ref-link/toc-*）。 */
.markdown-body :deep(h2) {
  border-bottom: 1px solid hsl(var(--border));
  padding-bottom: 6px;
}
/* h3 现在是"列表式"格式下每条新闻自己的标题，密度比以前的叙事段落高很多，
   需要比原来更强的视觉分量才能跟正文分清——加粗 + 左侧色条 + 单独留白。 */
.markdown-body :deep(h3) {
  padding-left: 10px;
  border-left: 3px solid hsl(var(--primary) / 0.6);
}
.markdown-body :deep(.section-header + .article-card h3) {
  margin-top: 14px;
}
.markdown-body :deep(a) {
  color: hsl(var(--primary));
}
.markdown-body :deep(.ref-link) {
  font-weight: 600;
  color: hsl(var(--primary));
  background: hsl(var(--primary) / 0.1);
  padding: 0 3px;
  border-radius: 3px;
}
.markdown-body :deep(.ref-missing) {
  color: hsl(var(--muted-foreground));
}

/* 分类小节标题：编号 + 分类名 + 篇数，替代原来纯 <h2>，跟 AIHOT 日报风格的
   编号分类头对齐；只用于「有三级小节」的分类（今日速览/值得关注/数据来源这类
   没有小节的仍然走普通 <h2>，见下面 .markdown-body :deep(h2)）。 */
.markdown-body :deep(.section-header) {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 32px 0 14px;
  padding-bottom: 8px;
  border-bottom: 1px solid hsl(var(--border));
}
.markdown-body :deep(.section-header:first-of-type) {
  margin-top: 0;
}
.markdown-body :deep(.section-index) {
  font-family: ui-monospace, monospace;
  font-size: 13px;
  font-weight: 700;
  color: hsl(var(--primary));
}
.markdown-body :deep(.section-name) {
  font-size: 17px;
  font-weight: 700;
}
.markdown-body :deep(.section-count) {
  margin-left: auto;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}
.markdown-body :deep(.article-card) {
  margin-bottom: 18px;
}
.markdown-body :deep(.article-title-link) {
  color: inherit;
  text-decoration: none;
}
.markdown-body :deep(.article-title-link:hover) {
  text-decoration: underline;
}
.markdown-body :deep(h3 .ref-link) {
  margin-left: 6px;
}
.markdown-body :deep(.source-tag) {
  display: inline-block;
  margin: 2px 0 4px 10px;
  padding: 1px 8px;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
  background: hsl(var(--muted));
  border-radius: 999px;
}

/* 今日看点：分类总览卡片，编号 + 分类名 + 篇数 + 首条标题预览，行间细分隔线 */
.toc-row {
  display: flex;
  gap: 14px;
  padding: 10px 0;
  border-bottom: 1px solid hsl(var(--border) / 0.6);
}
.toc-row:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.toc-row:first-child {
  padding-top: 0;
}
.toc-index {
  flex-shrink: 0;
  font-family: ui-monospace, monospace;
  font-size: 13px;
  font-weight: 700;
  color: hsl(var(--primary));
}
.toc-body {
  min-width: 0;
}
.toc-name {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 14px;
}
.toc-count {
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}
.toc-preview {
  margin-top: 2px;
  font-size: 13px;
  color: hsl(var(--muted-foreground));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
