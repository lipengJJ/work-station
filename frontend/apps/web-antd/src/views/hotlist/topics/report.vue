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
import { ArrowLeft, ExternalLink, RefreshCw, Send, UploadCloud } from 'lucide-vue-next';

import {
  getReportApi,
  getReportCandidatesApi,
  notifyReportApi,
  publishReportApi,
} from '#/api/core/topics';

const route = useRoute();
const router = useRouter();
const reportId = computed(() => Number(route.params.reportId));

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
function renderMarkdown(md: string) {
  if (!md) return '';
  const items = itemsById.value;
  const lines = md.split(/\r?\n/);
  const html: string[] = [];
  let inList = false;
  let inQuote = false;

  const closeList = () => {
    if (inList) {
      html.push('</ul>');
      inList = false;
    }
  };
  const escapeHtml = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const linkify = (s: string) => {
    // [n] 或 [n][m] → 可点击引用；[text](url) → 链接；裸 URL → 链接
    let out = s.replace(/\[(\d+)\]/g, (_, n) => {
      const id = Number(n);
      const item = items.get(id);
      if (item && item.url) {
        return `<a href="${item.url}" target="_blank" rel="noopener" class="ref-link" title="${escapeHtml(item.title)}">[${n}]</a>`;
      }
      return `<span class="ref-missing" title="条目已被清理">[${n}]</span>`;
    });
    out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    out = out.replace(/(https?:\/\/[^\s<)]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
    out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
    return out;
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line.startsWith('```')) {
      closeList();
      html.push('<pre class="code-block">' + escapeHtml(line.slice(3)) + '</pre>');
      continue;
    }
    if (line.startsWith('>')) {
      closeList();
      if (!inQuote) {
        html.push('<blockquote>');
        inQuote = true;
      }
      html.push(linkify(escapeHtml(line.slice(1).trim())));
      continue;
    }
    if (inQuote) {
      html.push('</blockquote>');
      inQuote = false;
    }
    if (/^#{1,6}\s/.test(line)) {
      closeList();
      const level = line.match(/^#+/)![0].length;
      html.push(`<h${level}>${linkify(escapeHtml(line.replace(/^#+\s*/, '')))}</h${level}>`);
    } else if (/^[-*]\s/.test(line)) {
      if (!inList) {
        html.push('<ul>');
        inList = true;
      }
      html.push(`<li>${linkify(escapeHtml(line.replace(/^[-*]\s*/, '')))}</li>`);
    } else if (/^\d+\.\s/.test(line)) {
      if (!inList) {
        html.push('<ol>');
        inList = true;
      }
      html.push(`<li>${linkify(escapeHtml(line.replace(/^\d+\.\s*/, '')))}</li>`);
    } else if (line.trim() === '') {
      closeList();
    } else {
      closeList();
      html.push(`<p>${linkify(escapeHtml(line))}</p>`);
    }
  }
  closeList();
  if (inQuote) html.push('</blockquote>');
  return html.join('\n');
}

const contentHtml = computed(() => renderMarkdown(report.value?.content_md || ''));

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
            <li v-for="(h, i) in report.highlights" :key="i" class="text-sm leading-relaxed">
              {{ h }}
            </li>
          </ul>
        </div>

        <!-- 正文 -->
        <div class="markdown-body" v-html="contentHtml"></div>

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
                  v-if="record.url"
                  :href="record.url"
                  target="_blank"
                  rel="noopener"
                  class="inline-flex items-center gap-1"
                >
                  {{ record.title }}
                  <ExternalLink class="size-3 text-foreground/40" />
                </a>
                <span v-else>{{ record.title }}</span>
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
              <a v-if="record.url" :href="record.url" target="_blank" rel="noopener">
                {{ record.title }}
              </a>
              <span v-else>{{ record.title }}</span>
            </template>
          </template>
        </Table>
        <Empty v-else-if="!candidatesLoading" description="本期没有未入选条目" />
      </Spin>
    </Drawer>
  </Page>
</template>

<style scoped>
.markdown-body {
  line-height: 1.8;
  font-size: 14px;
}
.markdown-body :deep(h2) {
  margin: 28px 0 12px;
  font-size: 18px;
  border-bottom: 1px solid hsl(var(--border));
  padding-bottom: 6px;
}
.markdown-body :deep(h3) {
  margin: 20px 0 8px;
  font-size: 15px;
}
.markdown-body :deep(p) {
  margin: 10px 0;
}
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 22px;
  margin: 8px 0;
}
.markdown-body :deep(li) {
  margin: 4px 0;
}
.markdown-body :deep(blockquote) {
  border-left: 3px solid hsl(var(--border));
  padding-left: 12px;
  color: hsl(var(--muted-foreground));
  margin: 10px 0;
}
.markdown-body :deep(code) {
  background: hsl(var(--muted));
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 13px;
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
</style>
