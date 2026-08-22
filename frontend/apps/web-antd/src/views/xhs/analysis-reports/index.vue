<script lang="ts" setup>
import type { XhsApi } from '#/api/core/xhs';

import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';

import { message, Modal, Tag } from 'ant-design-vue';
import { FileText, Search } from 'lucide-vue-next';

import { deleteXhsReportApi, listXhsAnalysisProjectsApi, listXhsReportsApi } from '#/api/core/xhs';

const router = useRouter();

function formatDateTime(iso: string) {
  if (!iso) return '';
  return iso.slice(0, 16).replace('T', ' ');
}

const reports = ref<XhsApi.ReportListItem[]>([]);
const loading = ref(false);
const total = ref(0);
const page = ref(1);
const pageSize = 20;

const searchQuery = ref('');
const projectFilter = ref<number>();
const sort = ref<'created_asc' | 'created_desc'>('created_desc');

const projects = ref<XhsApi.AnalysisProject[]>([]);

async function fetchProjects() {
  try {
    projects.value = await listXhsAnalysisProjectsApi();
  } catch {
    // 项目筛选下拉加载失败不影响报告列表本身，静默忽略
  }
}

async function fetchReports() {
  loading.value = true;
  try {
    const data = await listXhsReportsApi({
      query: searchQuery.value || undefined,
      project_id: projectFilter.value,
      sort: sort.value,
      page: page.value,
      page_size: pageSize,
    });
    reports.value = data.items;
    total.value = data.total;
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    loading.value = false;
  }
}

let debounce: ReturnType<typeof setTimeout> | undefined;
watch([searchQuery, projectFilter, sort], () => {
  if (debounce) clearTimeout(debounce);
  debounce = setTimeout(() => {
    page.value = 1;
    fetchReports();
  }, 300);
});

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
function goPage(p: number) {
  if (p < 1 || p > totalPages.value) return;
  page.value = p;
  fetchReports();
}

function openReport(report: XhsApi.ReportListItem) {
  router.push(`/xhs/analysis-reports/${report.id}`);
}

function removeReport(report: XhsApi.ReportListItem) {
  Modal.confirm({
    title: `确定删除报告《${report.title}》吗？`,
    content: '此操作不可恢复。',
    okType: 'danger',
    onOk: async () => {
      try {
        await deleteXhsReportApi(report.id);
        reports.value = reports.value.filter((r) => r.id !== report.id);
        total.value -= 1;
        message.success('已删除');
      } catch (e: any) {
        message.error(`删除失败：${e.message}`);
      }
    },
  });
}

onMounted(() => {
  fetchProjects();
  fetchReports();
});
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-[hsl(var(--background-deep))] p-6 select-none">
      <div class="mb-6 shrink-0">
        <h1 class="text-xl font-extrabold text-[hsl(var(--foreground))]">分析报告</h1>
        <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">在「AI 分析」里把满意的分析结论保存为报告，这里统一查看和管理</p>
      </div>

      <div class="mb-4 shrink-0 flex flex-wrap items-center gap-2">
        <div class="relative">
          <Search class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
          <input
            v-model="searchQuery"
            placeholder="搜索报告标题"
            class="w-64 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] py-1.5 pr-3 pl-8 text-xs text-[hsl(var(--foreground))] outline-none focus:border-primary"
          />
        </div>
        <select
          v-model="projectFilter"
          class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs text-[hsl(var(--foreground))] outline-none focus:border-primary"
        >
          <option :value="undefined">全部项目</option>
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <select
          v-model="sort"
          class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs text-[hsl(var(--foreground))] outline-none focus:border-primary"
        >
          <option value="created_desc">最新生成优先</option>
          <option value="created_asc">最早生成优先</option>
        </select>
      </div>

      <div class="shrink-0 overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] shadow-xl">
        <div v-if="!loading && reports.length === 0" class="flex flex-col items-center justify-center gap-3 p-12 text-center">
          <div class="flex h-14 w-14 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10">
            <FileText class="h-7 w-7 text-primary" />
          </div>
          <p class="text-sm font-semibold text-[hsl(var(--foreground))]">
            {{ searchQuery || projectFilter ? '没有匹配的报告' : '还没有保存过报告' }}
          </p>
          <p v-if="!searchQuery && !projectFilter" class="text-xs text-[hsl(var(--muted-foreground))]">
            在「AI 分析」页面完成一次分析后，点击「保存为报告」即可
          </p>
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] font-mono text-[11px] text-[hsl(var(--muted-foreground))] uppercase">
              <tr>
                <th class="px-4 py-3">报告名称及摘要</th>
                <th class="px-4 py-3">模板</th>
                <th class="px-4 py-3">关联项目</th>
                <th class="px-4 py-3">来源数量</th>
                <th class="px-4 py-3">生成时间</th>
                <th class="px-4 py-3">状态</th>
                <th class="px-4 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-[hsl(var(--border))]">
              <tr
                v-for="r in reports"
                :key="r.id"
                tabindex="0"
                class="cursor-pointer transition-colors hover:bg-[hsl(var(--accent))] focus:bg-[hsl(var(--accent))] focus:outline-none focus-visible:ring-1 focus-visible:ring-primary"
                @click="openReport(r)"
                @keyup.enter="openReport(r)"
              >
                <td class="max-w-md px-4 py-4">
                  <div class="font-semibold text-[hsl(var(--foreground))]">{{ r.title }}</div>
                  <div class="mt-0.5 truncate text-[11px] text-[hsl(var(--muted-foreground))]">{{ r.summary }}</div>
                </td>
                <td class="px-4 py-4 text-[hsl(var(--muted-foreground))]">{{ r.template || '—' }}</td>
                <td class="px-4 py-4 text-[hsl(var(--muted-foreground))]">{{ r.project_name }}</td>
                <td class="px-4 py-4 font-mono text-[hsl(var(--foreground))]">{{ r.source_count }}</td>
                <td class="px-4 py-4 text-[hsl(var(--muted-foreground))]">{{ formatDateTime(r.created_at) }}</td>
                <td class="px-4 py-4">
                  <Tag color="success">{{ r.status }}</Tag>
                </td>
                <td class="px-4 py-4 text-right" @click.stop>
                  <button class="text-[11px] text-[hsl(var(--muted-foreground))] hover:text-destructive" @click="removeReport(r)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="total > pageSize" class="mt-4 shrink-0 flex items-center justify-between text-xs text-[hsl(var(--muted-foreground))]">
        <span>共 {{ total }} 份报告</span>
        <div class="flex items-center gap-2">
          <button class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-2 py-1 disabled:opacity-40" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
          <span>{{ page }} / {{ totalPages }}</span>
          <button class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-2 py-1 disabled:opacity-40" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
        </div>
      </div>
    </div>
  </Page>
</template>
