<script lang="ts" setup>
import type { XhsApi } from '#/api/core/xhs';

import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';

import { Drawer, Empty, message } from 'ant-design-vue';
import { ArrowLeft, BookOpen, Calendar, Download, FileText, ListTree, Sparkles } from 'lucide-vue-next';
import MarkdownIt from 'markdown-it';
import html2canvas from 'html2canvas';
import { jsPDF } from 'jspdf';

import { buildXhsMediaProxyUrl, getXhsReportApi } from '#/api/core/xhs';

const route = useRoute();
const router = useRouter();

const md = new MarkdownIt({ breaks: true, linkify: true });

interface TocItem {
  id: string;
  text: string;
  level: number;
}

const bodyHtml = ref('');
const toc = ref<TocItem[]>([]);

/**
 * markdown-it 渲染出来的标题没有 id，没法做目录跳转/高亮。用一个临时 DOM 节点解析渲染后
 * 的 HTML（而不是用正则），给每个 h2/h3/h4 顺序编号生成 id、顺带提取纯文本做目录——
 * 比手写正则解析标签更不容易出错（标题里可能带粗体/链接等内联标签）。
 * 引用徽标（"引用笔记：[N]"）替换逻辑和 AI 分析页 renderAnalysisHtml 一致：只把正则
 * 捕获到的纯数字塞进 span，不存在 XSS 风险。
 */
function buildBodyAndToc(markdown: string) {
  let html = md.render(markdown || '');
  html = html.replace(/(引用笔记[:：]\s*)((?:\[\d+\]\s*)+)/g, (_match, label: string, nums: string) => {
    const badges = [...nums.matchAll(/\d+/g)]
      .map((m) => `<span class="cite-badge" data-note-index="${m[0]}">${m[0]}</span>`)
      .join('');
    return `${label}${badges}`;
  });

  const container = document.createElement('div');
  container.innerHTML = html;
  const headings = container.querySelectorAll('h2, h3, h4');
  const items: TocItem[] = [];
  headings.forEach((h, idx) => {
    const id = `report-heading-${idx}`;
    h.id = id;
    items.push({ id, text: h.textContent || '', level: Number(h.tagName.slice(1)) });
  });
  bodyHtml.value = container.innerHTML;
  toc.value = items;
}

function formatDateTime(iso: string) {
  if (!iso) return '';
  return iso.slice(0, 16).replace('T', ' ');
}

// ------------------------------------------------------------- PDF 导出 ----

const exportingPdf = ref(false);

// A4 @96dpi 的页面与内容区尺寸（px）
const PDF_PAGE_W = 794;
const PDF_PAGE_H = 1123;
const PDF_PAD_X = 56;
const PDF_PAD_TOP = 48;
const PDF_PAD_BOTTOM = 48;
const PDF_CONTENT_H = PDF_PAGE_H - PDF_PAD_TOP - PDF_PAD_BOTTOM; // 1027
// 页底剩余空间小于该值时，下一个标题块强制换页，避免标题孤悬页尾
const PDF_ORPHAN_H = 70;

/**
 * PDF 专用渲染：和页面正文同源（同一个 markdown-it 实例），但不生成目录 id，
 * 并把正文图片替换为占位块——XHS 图片走跨域代理，canvas 绘制跨域图可能触发
 * SecurityError 导致整份 PDF 导出失败，文字内容才是报告主体，图片回网页看。
 */
function buildPdfBodyHtml(markdown: string) {
  let html = md.render(markdown || '');
  html = html.replaceAll(/(引用笔记[:：]\s*)((?:\[\d+\]\s*)+)/g, (_match, label: string, nums: string) => {
    const badges = [...nums.matchAll(/\d+/g)]
      .map((m) => `<span class="pdf-cite-badge">${m[0]}</span>`)
      .join('');
    return `${label}${badges}`;
  });
  html = html.replaceAll(/<img[^>]*>/g, '<div class="pdf-img-placeholder">图片（详见网页版）</div>');
  return html;
}

/**
 * 块级分页：把 .pdf-body 下的内容拆成"不可切分"的块序列（段落/标题/列表/表格等），
 * 每个块整体归入某一页，保证任何一行文字都不会在页边界被硬切。
 * 超高的块（如很长的表格）会进一步按行拆分。
 */
function collectPdfUnits(bodyEl: HTMLElement): HTMLElement[] {
  const units: HTMLElement[] = [];
  for (const child of [...bodyEl.children] as HTMLElement[]) {
    collectUnit(child, units);
  }
  return units;
}

function collectUnit(el: HTMLElement, out: HTMLElement[]) {
  const h = unitHeight(el);
  if (h <= PDF_CONTENT_H) {
    out.push(el);
    return;
  }
  // 超高块：表格按行拆成多个独立表格；其它块尝试拆子元素，实在拆不动就整块保留
  if (el.tagName === 'TABLE') {
    for (const t of splitLongTable(el as HTMLTableElement)) out.push(t);
    return;
  }
  const children = [...el.children] as HTMLElement[];
  if (children.length > 0) {
    for (const c of children) collectUnit(c, out);
  } else {
    out.push(el);
  }
}

/** 把超页高的表格按行分组，每组克隆成一个独立表格（保留表头），保证行不被切断。 */
function splitLongTable(table: HTMLTableElement): HTMLElement[] {
  const rows = [...table.rows];
  if (rows.length === 0) return [table];
  const headRows = table.tHead ? [...table.tHead.rows] : [];
  const bodyRows = rows.filter((r) => !headRows.includes(r));
  const groups: HTMLTableRowElement[][] = [];
  let cur: HTMLTableRowElement[] = [];
  let curH = 0;
  for (const tr of bodyRows) {
    const h = tr.getBoundingClientRect().height + 1;
    if (cur.length > 0 && curH + h > PDF_CONTENT_H) {
      groups.push(cur);
      cur = [];
      curH = 0;
    }
    cur.push(tr);
    curH += h;
  }
  if (cur.length > 0) groups.push(cur);

  return groups.map((group) => {
    const clone = table.cloneNode(false) as HTMLTableElement;
    if (table.tHead) clone.append(table.tHead.cloneNode(true));
    const tbody = document.createElement('tbody');
    for (const tr of group) tbody.append(tr.cloneNode(true));
    clone.append(tbody);
    return clone;
  });
}

function isHeading(el: HTMLElement) {
  return /^H[1-4]$/.test(el.tagName);
}

/** 块的实际占用高度 = 布局高度 + 上下 margin（getBoundingClientRect 不含 margin）。 */
function unitHeight(el: HTMLElement) {
  const rect = el.getBoundingClientRect();
  const cs = window.getComputedStyle(el);
  const mt = Number.parseFloat(cs.marginTop) || 0;
  const mb = Number.parseFloat(cs.marginBottom) || 0;
  return rect.height + mt + mb;
}

/** 贪心分页：按块高度顺序累加，超过可用高度就换页；页尾空间过小时标题强制换页。 */
function paginateUnits(units: HTMLElement[]): HTMLElement[][] {
  const pages: HTMLElement[][] = [];
  let cur: HTMLElement[] = [];
  let curH = 0;
  for (let i = 0; i < units.length; i++) {
    const u = units[i];
    if (!u) continue;
    const h = unitHeight(u);
    const isHeadingEl = isHeading(u);
    const wouldOverflow = cur.length > 0 && curH + h > PDF_CONTENT_H;
    const orphanTitle = isHeadingEl && cur.length > 0 && PDF_CONTENT_H - curH < PDF_ORPHAN_H;
    // keep-with-next：标题与后一个块绑定，避免标题孤悬页首/页尾
    const bindsNext = isHeadingEl && i + 1 < units.length;
    const nextUnit = units[i + 1];
    const boundH = bindsNext && nextUnit ? h + unitHeight(nextUnit) : h;
    const overflowBound = cur.length > 0 && curH + boundH > PDF_CONTENT_H;
    if (wouldOverflow || orphanTitle || overflowBound) {
      if (cur.length > 0) pages.push(cur);
      cur = [];
      curH = 0;
    }
    cur.push(u);
    curH += h;
  }
  if (cur.length > 0) pages.push(cur);
  return pages;
}

const PDF_HEADER_HTML = `<style>
  .pdf-root { font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; font-size: 14px; line-height: 1.8; color: #1f2937; }
  .pdf-kicker { font-size: 12px; font-weight: 600; color: var(--primary); letter-spacing: 0.06em; margin-bottom: 6px; }
  .pdf-title { font-size: 24px; font-weight: 700; line-height: 1.4; margin: 0 0 10px; }
  .pdf-meta { font-size: 12px; color: #6b7280; margin-bottom: 16px; }
  .pdf-question { margin: 0 0 8px; padding: 10px 14px; border-left: 3px solid #4f46e5; background: #f5f5ff; color: #6b7280; font-style: italic; border-radius: 0 6px 6px 0; }
  .pdf-hr { border: none; border-top: 1px solid #e5e7eb; margin: 20px 0; }
  .pdf-body h2 { font-size: 19px; font-weight: 700; margin: 26px 0 12px; padding-top: 14px; border-top: 1px solid #f3f4f6; }
  .pdf-body h2:first-child { margin-top: 0; padding-top: 0; border-top: none; }
  .pdf-body h3 { font-size: 16px; font-weight: 700; margin: 20px 0 10px; }
  .pdf-body h4 { font-size: 14.5px; font-weight: 700; margin: 16px 0 8px; }
  .pdf-body p { margin: 0 0 12px; }
  .pdf-body ul, .pdf-body ol { margin: 0 0 12px; padding-left: 22px; }
  .pdf-body li { margin: 3px 0; }
  .pdf-body strong { font-weight: 700; }
  .pdf-body blockquote { margin: 0 0 12px; padding: 4px 14px; border-left: 3px solid #d1d5db; color: #6b7280; }
  .pdf-body code { padding: 1px 5px; border-radius: 4px; background: #f3f4f6; font-size: 0.9em; }
  .pdf-body pre { margin: 0 0 12px; padding: 12px 14px; border-radius: 8px; background: #f9fafb; overflow: hidden; }
  .pdf-body pre code { background: none; padding: 0; }
  .pdf-body table { border-collapse: collapse; width: 100%; margin: 0 0 12px; font-size: 13px; }
  .pdf-body th, .pdf-body td { border: 1px solid #e5e7eb; padding: 6px 10px; text-align: left; }
  .pdf-body th { background: #f9fafb; font-weight: 700; }
  .pdf-body a { color: var(--primary); text-decoration: none; }
  .pdf-body hr { border: none; border-top: 1px solid #e5e7eb; margin: 18px 0; }
  .pdf-cite-badge { display: inline-block; min-width: 16px; height: 16px; line-height: 16px; padding: 0 3px; margin: 0 2px; border-radius: 999px; background: #eef2ff; color: var(--primary); font-size: 11px; font-weight: 700; text-align: center; }
  .pdf-img-placeholder { margin: 8px 0; padding: 18px 0; border: 1px dashed #d1d5db; border-radius: 8px; color: #9ca3af; text-align: center; font-size: 12px; }
</style>`;

async function downloadPdf() {
  if (!report.value || exportingPdf.value) return;
  exportingPdf.value = true;
  const holder = document.createElement('div');
  const pages: HTMLElement[][] = [];
  try {
    const r = report.value;
    holder.id = 'pdf-export-holder';
    // 离屏渲染：fixed 在视口外，宽度 794px ≈ A4 96dpi 内容宽，白底黑字文档样式
    holder.style.cssText = `position:fixed;left:-99999px;top:0;width:${PDF_PAGE_W}px;background:#ffffff;z-index:-1;padding:${PDF_PAD_TOP}px ${PDF_PAD_X}px ${PDF_PAD_BOTTOM}px;box-sizing:border-box;`;
    holder.innerHTML = `${PDF_HEADER_HTML}<div class="pdf-root">
      <div class="pdf-kicker">AI 分析报告</div>
      <h1 class="pdf-title">${escapeHtml(r.title)}</h1>
      <div class="pdf-meta">
        ${escapeHtml(r.project_name)}${r.template ? ` · ${escapeHtml(r.template)}` : ''} · ${formatDateTime(r.created_at)} · 来源 ${r.source_notes.length} 篇笔记 · 模型 ${escapeHtml(r.model)}
      </div>
      <blockquote class="pdf-question">${escapeHtml(r.question)}</blockquote>
      <hr class="pdf-hr" />
      <div class="pdf-body">${buildPdfBodyHtml(r.result)}</div>
      <p style="font-size:11px;color:#9ca3af;margin-top:24px;">本报告由 AI 生成，数据来源于生成时的笔记集合；引用编号对应报告内来源笔记的顺序。</p>
    </div>`;
    document.body.append(holder);
    await document.fonts.ready;

    // 块级分页：正文拆成不可切分的块，整块归页，避免行被硬切
    const root = holder.querySelector('.pdf-root') as HTMLElement;
    const bodyEl = root.querySelector('.pdf-body') as HTMLElement;
    // 头部块（标题/元信息/问题/分隔线）参与第一页分页；尾部说明单独放文档末尾
    const children = [...root.children] as HTMLElement[];
    const footerEl = children.find((el) => el !== bodyEl && el.tagName === 'P' && !el.className) as HTMLElement | undefined;
    const headerEls = children.filter((el) => el !== bodyEl && el !== footerEl);
    const bodyUnits = collectPdfUnits(bodyEl);

    // 第一页 = 头部 + 尽量多的正文块；后续页 = 纯正文块。
    // 用同一套分页算法统一处理，保证页面顺序正确、无残留空页。
    const bodyPages = paginateUnits(bodyUnits);
    const firstUnits: HTMLElement[] = [...headerEls];
    if (bodyPages.length > 0) {
      const firstBodyPage = bodyPages[0];
      if (firstBodyPage) firstUnits.push(...firstBodyPage);
    }
    const firstPages = paginateUnits(firstUnits);
    for (const p of firstPages) pages.push(p);
    for (let i = 1; i < bodyPages.length; i++) {
      const p = bodyPages[i];
      if (p) pages.push(p);
    }
    // 尾部说明追加到最后一页
    if (footerEl && pages.length > 0) {
      const lastPage = pages[pages.length - 1];
      if (lastPage) lastPage.push(footerEl);
    }

    const PdfDocument = jsPDF;
    const pdf = new PdfDocument({ orientation: 'portrait', unit: 'pt', format: 'a4' });
    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = pdf.internal.pageSize.getHeight();

    for (let i = 0; i < pages.length; i++) {
      const pageUnits = pages[i];
      if (!pageUnits) continue;
      // 每页独立克隆块，避免共享 DOM；固定 A4 高度，内容不足留白，
      // 保证每页 canvas 尺寸一致（字号不因页面内容多少而缩放）。
      // 样式依赖 .pdf-root 祖先（字体/颜色）和 .pdf-body 祖先（正文排版），
      // 克隆块必须完整包在这两层里才能正确套用样式。
      const pageEl = document.createElement('div');
      pageEl.style.cssText = `position:fixed;left:-99999px;top:0;width:${PDF_PAGE_W}px;height:${PDF_PAGE_H}px;background:#ffffff;z-index:-1;padding:${PDF_PAD_TOP}px ${PDF_PAD_X}px ${PDF_PAD_BOTTOM}px;box-sizing:border-box;`;
      const pageRoot = document.createElement('div');
      pageRoot.className = 'pdf-root';
      const pageBody = document.createElement('div');
      pageBody.className = 'pdf-body';
      for (const u of pageUnits) pageBody.append(u.cloneNode(true));
      pageRoot.append(pageBody);
      pageEl.append(pageRoot);
      document.body.append(pageEl);

      const canvas = await html2canvas(pageEl, {
        scale: 3,
        useCORS: true,
        backgroundColor: '#ffffff',
        logging: false,
      });
      pageEl.remove();
      if (i > 0) pdf.addPage();
      pdf.addImage(canvas.toDataURL('image/jpeg', 0.92), 'JPEG', 0, 0, pageWidth, pageHeight);
      // 及时释放每页 canvas 内存，长报告多页时不至于撑爆内存
      canvas.width = 0;
      canvas.height = 0;
    }

    const safeTitle = r.title.replaceAll(/[\\/:*?"<>|]/g, '_').slice(0, 80) || '分析报告';
    pdf.save(`${safeTitle}.pdf`);
    message.success('PDF 已生成并下载');
  } catch (error: any) {
    message.error(`导出 PDF 失败：${error.message}`);
  } finally {
    holder.remove();
    exportingPdf.value = false;
  }
}

function escapeHtml(text: string) {
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

const report = ref<XhsApi.ReportDetail>();
const loading = ref(true);
const loadError = ref('');

// 中文阅读大致 300-400 字/分钟，取 350 做一个粗略估算，只是给读者一个心理预期，不追求精确
const readingMinutes = computed(() => {
  if (!report.value) return 1;
  return Math.max(1, Math.round(report.value.result.length / 350));
});

async function fetchReport() {
  const id = Number(route.params.id);
  if (!id) return;
  loading.value = true;
  loadError.value = '';
  try {
    report.value = await getXhsReportApi(id);
    buildBodyAndToc(report.value.result);
    await nextTick();
    setupScrollSpy();
  } catch (e: any) {
    loadError.value = e.message || '加载失败';
  } finally {
    loading.value = false;
  }
}

function openInXhs(url: string) {
  window.open(url, '_blank', 'noopener,noreferrer');
}
function coverOf(note: XhsApi.ReportSourceNote) {
  return note.video_cover || note.image_list[0] || '';
}
function coverProxied(note: XhsApi.ReportSourceNote) {
  const url = coverOf(note);
  if (!url) return '';
  return buildXhsMediaProxyUrl(url, {
    noteId: note.note_id,
    kind: note.video_cover ? 'cover' : 'image',
    index: note.video_cover ? undefined : 0,
  });
}

const evidenceDrawerOpen = ref(false);
const evidenceNote = ref<XhsApi.ReportSourceNote>();

function onBodyClick(e: MouseEvent) {
  const target = e.target as HTMLElement;
  const idxAttr = target?.dataset?.noteIndex;
  if (!idxAttr || !report.value) return;
  const note = report.value.source_notes[Number(idxAttr) - 1];
  if (note) {
    evidenceNote.value = note;
    evidenceDrawerOpen.value = true;
  } else {
    message.info('未找到对应的证据笔记');
  }
}

// ------------------------------------------------------------------ 目录 ----

const activeHeadingId = ref('');
let observer: IntersectionObserver | undefined;

function setupScrollSpy() {
  observer?.disconnect();
  if (toc.value.length === 0) return;
  const elements = toc.value
    .map((item) => document.getElementById(item.id))
    .filter((el): el is HTMLElement => !!el);
  if (elements.length === 0) return;

  observer = new IntersectionObserver(
    (entries) => {
      const visible = entries.filter((e) => e.isIntersecting);
      if (visible.length > 0) {
        activeHeadingId.value = visible[0]!.target.id;
      }
    },
    { rootMargin: '-64px 0px -70% 0px' },
  );
  for (const el of elements) observer.observe(el);
}

function scrollToHeading(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function backToList() {
  router.push('/xhs/analysis-reports');
}

onMounted(() => {
  fetchReport();
});
onBeforeUnmount(() => {
  observer?.disconnect();
});
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-[hsl(var(--background-deep))] p-6 select-none">
      <div class="mb-4 flex items-center justify-between">
        <button class="flex w-fit items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]" @click="backToList">
          <ArrowLeft class="h-3.5 w-3.5" />
          返回报告列表
        </button>
        <button
          v-if="report"
          :disabled="exportingPdf"
          class="flex items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary transition-colors hover:bg-primary/20 disabled:cursor-not-allowed disabled:opacity-50"
          @click="downloadPdf"
        >
          <Download class="h-3.5 w-3.5" />
          {{ exportingPdf ? '生成中…' : '下载 PDF' }}
        </button>
      </div>

      <div v-if="loadError" class="mx-auto w-full max-w-[960px] rounded-xl border border-destructive/30 bg-destructive/10 p-6 text-sm text-destructive">
        {{ loadError }}
      </div>
      <div v-else-if="loading" class="mx-auto w-full max-w-[960px] text-center text-sm text-[hsl(var(--muted-foreground))]">加载中…</div>

      <div v-else-if="report" class="mx-auto flex w-full max-w-[1160px] items-start gap-8">
        <!-- 正文：博客式阅读栏 -->
        <article class="min-w-0 flex-1 max-w-[800px]">
          <div class="mb-3 flex items-center gap-1.5 text-xs font-semibold text-primary">
            <Sparkles class="h-3.5 w-3.5" />
            <span>AI 分析报告</span>
          </div>
          <h1 class="text-[28px] leading-snug font-extrabold text-[hsl(var(--foreground))]">{{ report.title }}</h1>

          <div class="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-[hsl(var(--muted-foreground))]">
            <span class="flex items-center gap-1">
              <FileText class="h-3.5 w-3.5" />
              {{ report.project_name }}
            </span>
            <span v-if="report.template" class="flex items-center gap-1">
              <ListTree class="h-3.5 w-3.5" />
              {{ report.template }}
            </span>
            <span class="flex items-center gap-1">
              <Calendar class="h-3.5 w-3.5" />
              {{ formatDateTime(report.created_at) }}
            </span>
            <span class="flex items-center gap-1">
              <BookOpen class="h-3.5 w-3.5" />
              约 {{ readingMinutes }} 分钟阅读 · 来源 {{ report.source_notes.length }} 篇笔记
            </span>
          </div>

          <div class="mt-6 rounded-xl border-l-2 border-primary/50 bg-[hsl(var(--background-deep))] px-4 py-3 text-xs text-[hsl(var(--muted-foreground))] italic">
            {{ report.question }}
          </div>

          <!-- eslint-disable-next-line vue/no-v-html -- markdown-it 默认 html:false 会转义裸 HTML，注入的徽标 span 只包含正则捕获的纯数字 -->
          <div
            class="markdown-body mt-8"
            @click="onBodyClick"
            v-html="bodyHtml"
          ></div>

          <p class="mt-6 border-t border-[hsl(var(--border))] pt-4 text-[11px] text-[hsl(var(--muted-foreground))]">
            证据编号对应报告生成时项目内笔记的展示顺序，点击正文中的编号徽标可在右侧查看对应笔记。
          </p>
        </article>

        <!-- 目录：吸顶，标题数量太少就不占地方了 -->
        <aside v-if="toc.length >= 2" class="sticky top-6 hidden w-[220px] shrink-0 lg:block">
          <div class="mb-2 text-[11px] font-bold tracking-wide text-[hsl(var(--muted-foreground))] uppercase">目录</div>
          <nav class="flex flex-col gap-1 border-l border-[hsl(var(--border))] pl-3 text-xs">
            <a
              v-for="item in toc"
              :key="item.id"
              class="truncate transition-colors"
              :class="[
                item.level === 3 ? 'pl-3' : item.level === 4 ? 'pl-6' : '',
                activeHeadingId === item.id ? 'font-semibold text-primary' : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--muted-foreground))]',
              ]"
              @click="scrollToHeading(item.id)"
            >
              {{ item.text }}
            </a>
          </nav>
        </aside>
      </div>
    </div>

    <!-- 来源证据抽屉 -->
    <Drawer v-model:open="evidenceDrawerOpen" title="来源证据" width="420px">
      <template v-if="evidenceNote">
        <div class="mb-3 h-40 w-full overflow-hidden rounded-lg bg-[hsl(var(--muted))]">
          <img
            v-if="coverOf(evidenceNote)"
            :src="coverProxied(evidenceNote)"
            class="h-full w-full object-cover"
          />
          <div v-else class="flex h-full items-center justify-center text-xs text-[hsl(var(--muted-foreground))]">无封面</div>
        </div>
        <div class="text-base font-bold text-[hsl(var(--foreground))]">{{ evidenceNote.title || '无标题' }}</div>
        <div class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">{{ evidenceNote.nickname }} · {{ evidenceNote.upload_time }}</div>
        <p class="mt-3 text-xs whitespace-pre-wrap text-[hsl(var(--muted-foreground))]">{{ evidenceNote.desc }}</p>
        <div class="mt-3 flex items-center gap-3 text-xs text-[hsl(var(--muted-foreground))]">
          <span>♥ {{ evidenceNote.liked_count }}</span>
          <span>★ {{ evidenceNote.collected_count }}</span>
          <span>💬 {{ evidenceNote.comment_count }}</span>
        </div>
        <button
          v-if="evidenceNote.note_url"
          class="mt-4 rounded-lg border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-bold text-primary hover:bg-primary/20"
          @click="openInXhs(evidenceNote.note_url)"
        >
          在小红书查看原文
        </button>
      </template>
      <Empty v-else description="没有更多信息" />
    </Drawer>
  </Page>
</template>

<style scoped>
.markdown-body {
  font-size: 15px;
  line-height: 1.85;
  color: #cbd5e1;
}
.markdown-body :deep(h2) {
  margin: 32px 0 16px;
  padding-top: 8px;
  border-top: 1px solid #1e2433;
  font-size: 20px;
  font-weight: 800;
  color: #f1f5f9;
}
.markdown-body :deep(h2:first-child) {
  margin-top: 0;
  padding-top: 0;
  border-top: none;
}
.markdown-body :deep(h3) {
  margin: 24px 0 12px;
  font-size: 17px;
  font-weight: 700;
  color: #e2e8f0;
}
.markdown-body :deep(h4) {
  margin: 18px 0 8px;
  font-size: 15px;
  font-weight: 700;
  color: #e2e8f0;
}
.markdown-body :deep(p) {
  margin: 0 0 14px;
}
.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0 0 14px;
  padding-left: 22px;
}
.markdown-body :deep(li) {
  margin: 4px 0;
}
.markdown-body :deep(li > p) {
  margin: 0;
}
.markdown-body :deep(strong) {
  color: #f1f5f9;
  font-weight: 700;
}
.markdown-body :deep(em) {
  color: #a5b4fc;
  font-style: normal;
}
.markdown-body :deep(blockquote) {
  margin: 0 0 14px;
  padding: 4px 16px;
  border-left: 3px solid #4f46e5;
  background: rgba(79, 70, 229, 0.08);
  color: #94a3b8;
  border-radius: 0 8px 8px 0;
}
.markdown-body :deep(hr) {
  margin: 24px 0;
  border: none;
  border-top: 1px solid #1e2433;
}
.markdown-body :deep(code) {
  padding: 1px 6px;
  border-radius: 4px;
  background: #161c2a;
  color: #a5b4fc;
  font-size: 0.9em;
}
.markdown-body :deep(a) {
  color: #818cf8;
  text-decoration: underline;
}
.markdown-body :deep(.cite-badge) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  margin: 0 2px;
  border-radius: 999px;
  background: rgba(99, 102, 241, 0.2);
  color: #a5b4fc;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}
.markdown-body :deep(.cite-badge:hover) {
  background: rgba(99, 102, 241, 0.35);
}
</style>
