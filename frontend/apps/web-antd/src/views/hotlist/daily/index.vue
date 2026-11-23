<script lang="ts" setup>
import type { TopicsApi } from '#/api/core/topics';

import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';

import { Empty, Spin } from 'ant-design-vue';

import { getReportApi, listTopicReportsApi, listTopicsApi } from '#/api/core/topics';
import {
  buildToc,
  escapeHtml,
  makeLinkify,
  type ParsedArticle,
  parseSections,
  renderBody,
} from '#/views/hotlist/shared/reportContent';

// 「日报」读者视图：布局严格照抄一份 AIHOT 风格的设计稿（Claude Design 项目
// 235bbfb9，AIHOT 日报周报.dc.html）——344px 侧栏 + 主栏两栏结构、52px 大标题、
// 2px 粗分割线、0 圆角的"modernist"卡片、日期列表用 inset box-shadow 做左侧
// 强调条。配色换成本站自己的主题变量（primary/foreground/muted/border），
// 不搬设计稿原本的红色调；字体也沿用本站全局字体，没有额外引入 Archivo。
// 跟「主题订阅 → 报告详情」（topics/report.vue）是同一份数据、两种呈现：
// 那边是运营视角（发布/推送/漏检抽查），这里是纯读者视角，不放操作按钮。

const route = useRoute();
const router = useRouter();

const topic = ref<null | TopicsApi.Topic>(null);
const reports = ref<TopicsApi.Report[]>([]);
const listLoading = ref(true);
const report = ref<null | TopicsApi.ReportDetail>(null);
const detailLoading = ref(true);

type PeriodTab = 'daily' | 'monthly' | 'weekly';
const PERIOD_TABS: { key: PeriodTab; label: string }[] = [
  { key: 'daily', label: '日报' },
  { key: 'weekly', label: '周报' },
  { key: 'monthly', label: '月报' },
];
const activePeriod = ref<PeriodTab>('daily');

const DAILY_KEY_RE = /^\d{4}-\d{2}-\d{2}$/;
const WEEKLY_KEY_RE = /^\d{4}-W\d{2}$/;
// 月报在数据模型里还不存在（主题只有 daily/weekly 两档周期），选中这个 tab
// 就是空列表——不编造假数据，走空状态。

function matchesPeriod(periodKey: string, tab: PeriodTab): boolean {
  if (tab === 'daily') return DAILY_KEY_RE.test(periodKey);
  if (tab === 'weekly') return WEEKLY_KEY_RE.test(periodKey);
  return false;
}

// 历史报告里两种 period_key 格式可能混着（主题的 digest_period 中途改过），
// 靠格式本身判断比信主题当前配置更可靠。
const periodReports = computed(() =>
  reports.value
    .filter((r) => r.status === 'success' && matchesPeriod(r.period_key, activePeriod.value))
    .sort((a, b) => (a.period_key < b.period_key ? 1 : -1)),
);

function previewOf(r: TopicsApi.Report): string {
  for (const section of parseSections(r.content_md)) {
    if (section.articles.length > 0) return section.articles[0]!.title;
  }
  return r.summary || '';
}

function dateLabelOf(periodKey: string, tab: PeriodTab): string {
  if (tab === 'daily') {
    const day = periodKey.split('-')[2];
    return `${Number(day)} 日`;
  }
  return periodKey.replace(/^\d{4}-/, ''); // "2026-W34" -> "W34"
}

function groupKeyOf(periodKey: string, tab: PeriodTab): string {
  // 日报按"年-月"分组；周报数据量小，按"年"分组就够用。
  return tab === 'daily' ? periodKey.slice(0, 7) : periodKey.slice(0, 4);
}

function groupLabelOf(periodKey: string, tab: PeriodTab): string {
  const year = periodKey.slice(0, 4);
  if (tab === 'daily') return `${year} 年 ${Number(periodKey.slice(5, 7))} 月`;
  return `${year} 年`;
}

interface IssueRow {
  dateLabel: string;
  preview: string;
  report: TopicsApi.Report;
}
interface IssueGroup {
  label: string;
  rows: IssueRow[];
}
const issueGroups = computed<IssueGroup[]>(() => {
  const order: string[] = [];
  const groups = new Map<string, IssueGroup>();
  for (const r of periodReports.value) {
    const key = groupKeyOf(r.period_key, activePeriod.value);
    if (!groups.has(key)) {
      groups.set(key, { label: groupLabelOf(r.period_key, activePeriod.value), rows: [] });
      order.push(key);
    }
    groups
      .get(key)!
      .rows.push({
        dateLabel: dateLabelOf(r.period_key, activePeriod.value),
        preview: previewOf(r),
        report: r,
      });
  }
  return order.map((key) => groups.get(key)!);
});
// 侧栏顶部那行“2026 年 8 月 · 29”——取当前 tab 下最新一期所在的分组。
const headGroup = computed(() => issueGroups.value[0]);

const selectedReportId = computed(() => {
  const raw = route.params.reportId;
  const n = Array.isArray(raw) ? Number(raw[0]) : Number(raw);
  return Number.isInteger(n) && n > 0 ? n : 0;
});

function selectReport(id: number) {
  if (id !== selectedReportId.value) router.push(`/hotlist/daily/${id}`);
}

function selectPeriod(tab: PeriodTab) {
  if (tab === activePeriod.value) return;
  activePeriod.value = tab;
  const first = periodReports.value[0];
  if (first) {
    selectReport(first.id);
  } else {
    // 这个周期下没有报告（比如月报还没有数据模型支撑）——把已经加载的旧报告
    // 清掉，不然主栏会显示"标题栏说月报，正文却是上个周期内容"这种错位。
    report.value = null;
  }
}

async function loadList() {
  listLoading.value = true;
  try {
    const topics = await listTopicsApi();
    topic.value =
      topics.find((t) => t.enabled && t.digest_period === 'daily') || topics[0] || null;
    if (!topic.value) return;
    const page = await listTopicReportsApi(topic.value.id, { page_size: 100 });
    reports.value = page.reports;
    if (!selectedReportId.value && periodReports.value.length > 0) {
      router.replace(`/hotlist/daily/${periodReports.value[0]!.id}`);
    }
  } finally {
    listLoading.value = false;
  }
}

async function loadDetail(id: number) {
  if (!id) {
    report.value = null;
    return;
  }
  detailLoading.value = true;
  try {
    report.value = await getReportApi(id);
    // 直接改地址栏跳到某个 reportId 时，把 tab 高亮同步成这份报告实际的周期
    // 格式，不然可能出现"选中的是日报，高亮却停在周报"这种不一致。
    if (WEEKLY_KEY_RE.test(report.value.period_key)) activePeriod.value = 'weekly';
    else if (DAILY_KEY_RE.test(report.value.period_key)) activePeriod.value = 'daily';
  } finally {
    detailLoading.value = false;
  }
}

watch(selectedReportId, (id) => loadDetail(id), { immediate: true });
onMounted(loadList);

const archiveYearRange = computed(() => {
  const years = reports.value
    .filter((r) => r.status === 'success')
    .map((r) => r.period_key.slice(0, 4))
    .filter(Boolean)
    .sort();
  if (years.length === 0) return '';
  const min = years[0]!;
  const max = years.at(-1)!;
  return min === max ? min : `${min} — ${max}`;
});

// -------------------------------------------------------------- 正文渲染 ----
const itemsById = computed(() => {
  const map = new Map<number, TopicsApi.ReportItemRef>();
  for (const item of report.value?.items || []) map.set(item.id, item);
  return map;
});
const linkify = computed(() => makeLinkify(itemsById.value));
const parsedSections = computed(() => parseSections(report.value?.content_md || ''));

// 来源标签做成两段式（分类小徽标 + 具体来源名），参照设计稿；分类只能从引用
// 条目的 URL host 推断（公众号/GitHub/X/Hugging Face/网页），不编造"官方"
// 这类无法验证的标注。
function deriveSourceType(url: string): string {
  try {
    const host = new URL(url).hostname.replace(/^www\./, '');
    if (host === 'mp.weixin.qq.com') return '公众号';
    if (host === 'github.com') return 'GitHub';
    if (host === 'x.com' || host === 'twitter.com') return 'X';
    if (host === 'huggingface.co') return 'Hugging Face';
    return host || '网页';
  } catch {
    return '网页';
  }
}
function renderSourceTag(article: ParsedArticle): string {
  if (!article.source) return '';
  const item = article.id ? itemsById.value.get(article.id) : undefined;
  const type = item?.url ? deriveSourceType(item.url) : '';
  const typeBadge = type ? `<span class="source-type-badge">${escapeHtml(type)}</span>` : '';
  return `<span class="source-tag-group">${typeBadge}<span class="source-name">来源：${escapeHtml(article.source)}</span></span>`;
}

// “今日速览”在 Skill 模板里就只有一行统计文字（要点已经被后端抽到 highlights
// 里单独处理）——单独起一个 H2 小节渲染出来太单薄，改成从正文里摘掉，并进
// “今日看点”卡片的头部当一行元信息；“值得关注”正常走原来的渲染，“数据来源”
// 整节直接不要了——读者视图里引用 [n] 本身已经可以点进条目详情页查看原文，
// 文末再罗列一遍链接是重复信息。
const overviewLine = computed(() => {
  const section = parsedSections.value.find((s) => s.name.endsWith('速览'));
  return section?.rawLines.join('').trim() || '';
});
const bodySections = computed(() =>
  parsedSections.value.filter(
    (s) => !s.name.endsWith('速览') && !s.name.includes('数据来源'),
  ),
);
const bodyHtml = computed(() =>
  renderBody(bodySections.value, linkify.value, {
    renderSourceTag,
    showTitleRefBadge: false,
    wrapSections: true,
  }),
);
const toc = computed(() => buildToc(parsedSections.value));
const tocTotalArticles = computed(() => toc.value.reduce((sum, r) => sum + r.count, 0));
const readingMinutes = computed(() =>
  Math.max(1, Math.round((report.value?.content_md.length || 0) / 400)),
);

const periodMeta = computed(() => {
  const tab = activePeriod.value;
  if (tab === 'weekly')
    return { masthead: '周报', en: 'WEEKLY', cadence: 'WEEKLY · 每周更新', overviewTitle: '本周看点' };
  if (tab === 'monthly')
    return { masthead: '月报', en: 'MONTHLY', cadence: 'MONTHLY · 每月更新', overviewTitle: '本月看点' };
  return { masthead: '日报', en: 'DAILY', cadence: 'DAILY · 每日更新', overviewTitle: '今日看点' };
});

// -------------------------------------------------------------- 日期格式 ----
function formatChineseDate(periodKey: string): string {
  if (WEEKLY_KEY_RE.test(periodKey)) {
    const [y, w] = periodKey.split('-W');
    return `${y}年 第${Number(w)}周`;
  }
  const d = new Date(`${periodKey}T00:00:00`);
  if (Number.isNaN(d.getTime())) return periodKey;
  const week = '日一二三四五六'[d.getDay()];
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 星期${week}`;
}
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <template #title>日报</template>

    <div class="daily-shell">
      <!-- 左：期号导航（周期 tab + 按月/年分组的日期列表） -->
      <aside class="daily-aside">
        <div class="daily-brand">
          <span class="daily-brand-name">{{ topic?.name || 'AI' }}</span>
          <span class="daily-brand-sub">EDITORIAL DESK</span>
        </div>

        <div class="daily-tabs">
          <button
            v-for="t in PERIOD_TABS"
            :key="t.key"
            type="button"
            class="daily-tab"
            :class="{ 'daily-tab-active': t.key === activePeriod }"
            @click="selectPeriod(t.key)"
          >
            {{ t.label }}
          </button>
        </div>

        <div v-if="headGroup" class="daily-group-label">
          <span>{{ headGroup.label }}</span>
          <span>{{ headGroup.rows.length }}</span>
        </div>

        <div class="daily-issue-list">
          <Spin :spinning="listLoading" />
          <Empty
            v-if="!listLoading && periodReports.length === 0"
            :description="activePeriod === 'monthly' ? '月报暂未支持' : '暂无报告'"
            class="mt-10"
          />
          <template v-for="group in issueGroups" :key="group.label">
            <div
              v-for="row in group.rows"
              :key="row.report.id"
              class="daily-issue-row"
              :class="{ 'daily-issue-row-active': row.report.id === selectedReportId }"
              role="button"
              tabindex="0"
              @click="selectReport(row.report.id)"
              @keydown.enter="selectReport(row.report.id)"
            >
              <span class="daily-issue-date">{{ row.dateLabel }}</span>
              <span class="daily-issue-title">{{ row.preview }}</span>
            </div>
          </template>
        </div>

        <div class="daily-archive">
          <span>ARCHIVE</span>
          <span>{{ archiveYearRange }}</span>
        </div>
      </aside>

      <!-- 右：选中那期的正文 -->
      <main class="daily-main">
        <Spin :spinning="detailLoading">
          <template v-if="report">
            <div class="daily-content">
              <div class="daily-vol">
                VOL.{{ report.period_key }} · {{ report.item_ids.length }} STORIES ·
                {{ (topic?.name || '').toUpperCase() }} {{ periodMeta.en }}
              </div>
              <h1 class="daily-masthead">
                {{ topic?.name }}<span class="daily-masthead-accent"> {{ periodMeta.masthead }}</span>
              </h1>
              <div class="daily-dateline">
                <span>{{ formatChineseDate(report.period_key) }}</span>
                <span class="daily-cadence">{{ periodMeta.cadence }}</span>
              </div>

              <!-- 今日看点 -->
              <section v-if="toc.length > 0" class="daily-overview">
                <div class="daily-overview-head">
                  <h2>{{ periodMeta.overviewTitle }}</h2>
                  <span>{{ tocTotalArticles }} 篇报道 · 约 {{ readingMinutes }} 分钟</span>
                </div>
                <div v-if="overviewLine" class="daily-overview-line">{{ overviewLine }}</div>
                <div
                  v-for="row in toc"
                  :key="row.index"
                  class="daily-overview-row"
                >
                  <span class="daily-overview-num">{{ row.index }}</span>
                  <div class="daily-overview-body">
                    <span class="daily-overview-name">{{ row.name }}</span>
                    <span class="daily-overview-lead">{{ row.preview }}</span>
                  </div>
                  <span class="daily-overview-count">{{ row.count }} 篇</span>
                </div>
              </section>

              <!-- 正文 -->
              <!-- eslint-disable-next-line vue/no-v-html -- 报告正文是本站按固定模板生成的可信内容 -->
              <div class="markdown-body" v-html="bodyHtml"></div>
            </div>
          </template>
          <Empty v-else-if="!detailLoading" description="选择左侧日期查看报告" class="mt-10" />
        </Spin>
      </main>
    </div>
  </Page>
</template>

<style scoped>
/* 布局严格照抄设计稿的两栏结构：344px 固定侧栏 + 自适应主栏，各自独立滚动。
   配色全部换成本站主题变量，不用设计稿原本的红色调；圆角统一去掉（0px），
   分割线按设计稿的粗细区分：结构性分割用 2px 前景色，列表项之间用 1px 边框色。 */
.daily-shell {
  display: grid;
  grid-template-columns: 344px 1fr;
  height: 100%;
  min-height: 0;
}

/* -------------------------------------------------- 左侧栏 ---------------- */
.daily-aside {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: hsl(var(--muted) / 0.4);
}
.daily-brand {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 20px 24px 16px;
}
.daily-brand-name {
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.daily-brand-sub {
  font-size: 10px;
  letter-spacing: 0.18em;
  color: hsl(var(--muted-foreground));
}
.daily-tabs {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  margin: 0 24px 20px;
  padding: 3px;
  border-radius: 10px;
  background: hsl(var(--muted));
}
.daily-tab {
  appearance: none;
  cursor: pointer;
  font: inherit;
  font-size: 14px;
  font-weight: 600;
  padding: 9px 0;
  text-align: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: hsl(var(--muted-foreground));
}
.daily-tab:hover:not(.daily-tab-active) {
  background: hsl(var(--primary) / 0.08);
}
.daily-tab-active {
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
}
.daily-group-label {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 16px 24px 10px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.daily-group-label span:last-child {
  font-size: 11px;
  font-weight: 400;
  letter-spacing: 0.14em;
  color: hsl(var(--muted-foreground));
}
.daily-issue-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.daily-issue-row {
  display: grid;
  grid-template-columns: 56px 1fr;
  gap: 12px;
  align-items: start;
  margin: 2px 24px;
  padding: 11px 8px;
  border-radius: 10px;
  cursor: pointer;
}
.daily-issue-row:hover:not(.daily-issue-row-active) {
  background: hsl(var(--primary) / 0.06);
}
.daily-issue-row-active {
  background: hsl(var(--primary) / 0.1);
  box-shadow: inset 3px 0 0 hsl(var(--primary));
}
.daily-issue-date {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: hsl(var(--muted-foreground));
}
.daily-issue-row-active .daily-issue-date {
  color: hsl(var(--primary));
}
.daily-issue-title {
  font-size: 13px;
  line-height: 1.5;
  text-align: left;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}
.daily-archive {
  padding: 12px 24px;
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  letter-spacing: 0.12em;
  color: hsl(var(--muted-foreground));
}

/* -------------------------------------------------- 主栏 ------------------ */
.daily-main {
  min-height: 0;
  overflow-y: auto;
}
.daily-content {
  max-width: 860px;
  margin: 0 auto;
  padding: 32px 24px 64px;
}
.daily-vol {
  font-size: 11px;
  letter-spacing: 0.24em;
  color: hsl(var(--muted-foreground));
  margin-bottom: 12px;
}
.daily-masthead {
  font-size: 36px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: -0.02em;
  margin: 0;
}
.daily-masthead-accent {
  color: hsl(var(--primary));
}
.daily-dateline {
  display: flex;
  gap: 20px;
  align-items: baseline;
  margin: 10px 0 28px;
  font-size: 13px;
  color: hsl(var(--muted-foreground));
}
.daily-cadence {
  letter-spacing: 0.16em;
  font-size: 11px;
}

/* -------------------------------------------------- 今日看点 -------------- */
.daily-overview {
  border-radius: 14px;
  background: hsl(var(--muted) / 0.5);
  margin-bottom: 24px;
}
.daily-overview-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 16px 24px 4px;
}
.daily-overview-head h2 {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}
.daily-overview-head span {
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}
.daily-overview-line {
  padding: 10px 24px;
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}
.daily-overview-row {
  display: grid;
  grid-template-columns: 40px 1fr 48px;
  gap: 12px;
  padding: 13px 24px;
}
.daily-overview-num {
  font-size: 13px;
  font-weight: 600;
  color: hsl(var(--primary));
  letter-spacing: 0.06em;
  padding-top: 3px;
  font-family: ui-monospace, monospace;
}
.daily-overview-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.daily-overview-name {
  font-size: 14px;
  font-weight: 600;
}
.daily-overview-lead {
  font-size: 13px;
  line-height: 1.5;
  color: hsl(var(--muted-foreground));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.daily-overview-count {
  font-size: 13px;
  color: hsl(var(--muted-foreground));
  text-align: right;
  padding-top: 4px;
}

/* -------------------------------------------------- 正文（编号分类 + 文章卡片）--- */
.markdown-body :deep(h2) {
  font-size: 20px;
  font-weight: 600;
  margin: 32px 0 14px;
}
.markdown-body :deep(p) {
  font-size: 14px;
  line-height: 1.7;
  color: hsl(var(--muted-foreground));
  margin: 0 0 12px;
}
.markdown-body :deep(ul) {
  padding-left: 20px;
  margin: 8px 0;
}
.markdown-body :deep(img) {
  max-width: 100%;
  height: auto;
  margin: 8px 0;
}
.markdown-body :deep(li) {
  font-size: 14px;
  line-height: 1.7;
  margin: 4px 0;
}
.markdown-body :deep(a) {
  color: hsl(var(--primary));
}
.markdown-body :deep(.ref-link) {
  font-weight: 600;
  color: hsl(var(--primary));
  background: hsl(var(--primary) / 0.1);
  padding: 0 5px;
  border-radius: 999px;
}
.markdown-body :deep(.ref-missing) {
  color: hsl(var(--muted-foreground));
}
.markdown-body :deep(.section-box) {
  border-radius: 14px;
  background: hsl(var(--muted) / 0.5);
  padding: 20px 24px 4px;
  margin: 24px 0;
}
.markdown-body :deep(.section-box:first-child) {
  margin-top: 0;
}
.markdown-body :deep(.section-header) {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding-bottom: 4px;
}
.markdown-body :deep(.section-box .article-card:last-child) {
  border-bottom: 0;
}
.markdown-body :deep(.section-index) {
  font-family: ui-monospace, monospace;
  font-size: 17px;
  font-weight: 800;
  color: hsl(var(--primary));
}
.markdown-body :deep(.section-name) {
  font-size: 21px;
  font-weight: 600;
}
.markdown-body :deep(.section-count) {
  margin-left: auto;
  font-size: 13px;
  color: hsl(var(--muted-foreground));
}
.markdown-body :deep(.article-card) {
  padding: 18px 0;
  border-bottom: 1px dashed hsl(var(--border) / 0.7);
}
.markdown-body :deep(.article-card h3) {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.35;
  margin: 0 0 8px;
  color: hsl(var(--foreground));
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
.markdown-body :deep(.source-tag-group) {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.markdown-body :deep(.source-type-badge) {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  padding: 3px 9px;
  border-radius: 999px;
  background: hsl(var(--primary) / 0.15);
  color: hsl(var(--primary));
}
.markdown-body :deep(.source-name) {
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

</style>
