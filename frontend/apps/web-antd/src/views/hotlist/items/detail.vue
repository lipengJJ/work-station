<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';

import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';

import { Alert, Button, Empty, Spin, Tag } from 'ant-design-vue';
import { ArrowLeft, ExternalLink } from 'lucide-vue-next';
import MarkdownIt from 'markdown-it';

import {
  getHotlistItemDetailApi,
  getHotlistItemFulltextApi,
  listHotlistSourcesApi,
} from '#/api/core/hotlist';

// 跟报告详情页同一种用法：markdown-it 默认 html:false，裸 HTML 会被转义，
// 全文来自外部不可信站点，v-html 是安全的。
const md = new MarkdownIt({ breaks: true, linkify: true });
// 微信图片 CDN（mmbiz.qpic.cn）按 Referer 做防盗链：带上我们自己站点的 Referer 会被
// 换成一张「不可引用」的占位图，不带 Referer 才能拿到真图——浏览器发起图片请求时
// 默认会带上完整 Referer，所以要显式把 <img> 标成 no-referrer。
const defaultImageRule = md.renderer.rules.image;
md.renderer.rules.image = (tokens, idx, options, env, self) => {
  tokens[idx]!.attrSet('referrerpolicy', 'no-referrer');
  return defaultImageRule!(tokens, idx, options, env, self);
};

const route = useRoute();
const router = useRouter();
const itemId = computed(() => {
  const raw = route.params.id;
  const n = Array.isArray(raw) ? Number(raw[0]) : Number(raw);
  return Number.isInteger(n) && n > 0 ? n : 0;
});

const loading = ref(true);
const item = ref<HotlistApi.Item | null>(null);
const sourceName = ref('');
const fulltext = ref<HotlistApi.ItemFulltext | null>(null);

interface TocItem {
  id: string;
  level: number;
  text: string;
}

// 公众号正文没有真的 <h1-6>，后端靠"整块只有一个加粗、没别的文字"这个视觉约定
// 识别出小节标题，转成 ## 标记（见 fulltext_service._extract_wechat_markdown）；
// 这里解析 markdown-it 的 token 流给每个标题标签塞一个 id，同时收集目录条目——
// 直接操作 token 而不是渲染完再从 HTML 里挖，是因为 id 得先塞进 token 才能让
// 渲染出的 <h2 id="..."> 和目录锚点对上。
function renderWithToc(source: string): { html: string; toc: TocItem[] } {
  const tokens = md.parse(source, {});
  const toc: TocItem[] = [];
  let seq = 0;
  for (const [i, token] of tokens.entries()) {
    if (token.type !== 'heading_open') continue;
    const id = `heading-${seq++}`;
    token.attrSet('id', id);
    const inline = tokens[i + 1];
    const text = inline?.type === 'inline' ? inline.content : '';
    if (text) toc.push({ id, level: Number(token.tag.slice(1)), text });
  }
  return { html: md.renderer.render(tokens, md.options, {}), toc };
}

const rendered = computed(() =>
  fulltext.value?.status === 'success'
    ? renderWithToc(fulltext.value.content)
    : { html: '', toc: [] },
);
const contentHtml = computed(() => rendered.value.html);
const toc = computed(() => rendered.value.toc);

// 目录高亮跟随滚动位置：哪个标题当前进入了视口上方的观察带，就点亮哪一条——
// 跟 xhs 分析报告详情页（views/xhs/analysis-reports/detail.vue）同一套写法。
const activeHeadingId = ref('');
let scrollSpy: IntersectionObserver | undefined;

function setupScrollSpy() {
  scrollSpy?.disconnect();
  if (toc.value.length === 0) return;
  const elements = toc.value
    .map((t) => document.getElementById(t.id))
    .filter((el): el is HTMLElement => !!el);
  if (elements.length === 0) return;
  scrollSpy = new IntersectionObserver(
    (entries) => {
      const visible = entries.filter((e) => e.isIntersecting);
      if (visible.length > 0) activeHeadingId.value = visible[0]!.target.id;
    },
    { rootMargin: '-64px 0px -70% 0px' },
  );
  for (const el of elements) scrollSpy.observe(el);
}

function scrollToHeading(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

onBeforeUnmount(() => scrollSpy?.disconnect());

const statusText = computed(() => {
  const r = fulltext.value;
  if (!r) return '';
  if (r.status === 'skipped') return `未抓取全文：${r.error || '来源限制'}`;
  if (r.status === 'failed') return `全文抓取失败：${r.error || '未知原因'}`;
  return '';
});

function formatDateTime(iso: null | string) {
  if (!iso) return '—';
  return iso.slice(0, 16).replace('T', ' ');
}

async function load() {
  if (itemId.value === 0) return;
  loading.value = true;
  try {
    const [detail, sources] = await Promise.all([
      getHotlistItemDetailApi(itemId.value),
      listHotlistSourcesApi(),
    ]);
    item.value = detail.item;
    sourceName.value =
      sources.find((s) => s.id === detail.item.source_id)?.name || detail.item.source_id;
    // 全文单独请求：缓存没有就现抓，跟主题报告 L2 共用同一份缓存，不阻塞条目信息展示
    fulltext.value = await getHotlistItemFulltextApi(itemId.value);
  } finally {
    loading.value = false;
  }
  await nextTick();
  setupScrollSpy();
}

onMounted(load);
</script>

<template>
  <Page :auto-content-height="true">
    <template #title>
      <div class="flex items-center gap-2">
        <Button type="text" class="!px-1" @click="router.back()">
          <template #icon><ArrowLeft class="size-4" /></template>
        </Button>
        <span>文章详情</span>
      </div>
    </template>

    <Spin :spinning="loading">
      <!-- 阅读列宽固定（跟 Medium/Pocket/Safari Reader 一类阅读视图同一个思路）：
           这个页面是给人正儿八经读一篇文章的，不是报告页那种信息密度优先的摘要列表，
           不该让文字随窗口宽度无限拉伸——那样每行字数太多反而更难读。目录能不能测出来
           全看来源文章有没有遵循"加粗独立成段"这个约定，测不出来就没有侧栏，不是 bug。 -->
      <div v-if="item" class="mx-auto flex max-w-5xl gap-10">
        <div class="min-w-0 flex-1">
          <div class="mb-5">
            <h1 class="mb-2 text-xl font-semibold leading-snug">{{ item.title }}</h1>
            <div class="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
              <Tag v-if="sourceName" color="default">{{ sourceName }}</Tag>
              <span v-if="item.published_at">发布于 {{ formatDateTime(item.published_at) }}</span>
              <a
                v-if="item.url"
                :href="item.url"
                target="_blank"
                rel="noopener"
                class="inline-flex items-center gap-1 text-primary hover:underline"
              >
                查看原文 <ExternalLink class="size-3.5" />
              </a>
            </div>
          </div>

          <!-- eslint-disable-next-line vue/no-v-html -- markdown-it 默认 html:false，裸 HTML 会被转义，全文来自外部不可信站点 -->
          <div v-if="contentHtml" class="prose dark:prose-invert prose-img:mx-auto prose-img:max-h-[70vh] prose-img:rounded-md prose-img:object-contain" v-html="contentHtml"></div>
          <template v-else>
            <Alert type="info" show-icon :message="statusText || '暂无全文'" class="mb-4" />
            <p v-if="item.summary" class="text-sm leading-relaxed text-foreground/80">
              {{ item.summary }}
            </p>
          </template>
        </div>

        <aside v-if="toc.length > 0" class="hidden w-56 shrink-0 xl:block">
          <div class="sticky top-6">
            <div class="mb-3 text-sm font-semibold">本文目录</div>
            <nav class="space-y-2.5 text-sm">
              <a
                v-for="t in toc"
                :key="t.id"
                :href="`#${t.id}`"
                class="block truncate border-l-2 pl-3 leading-snug transition-colors"
                :class="
                  activeHeadingId === t.id
                    ? 'border-primary font-semibold text-primary'
                    : 'border-border text-muted-foreground hover:border-primary hover:text-primary'
                "
                :style="{ paddingLeft: `${12 + Math.max(0, t.level - 2) * 12}px` }"
                :title="t.text"
                @click.prevent="scrollToHeading(t.id)"
              >
                {{ t.text }}
              </a>
            </nav>
          </div>
        </aside>
      </div>
      <Empty v-else-if="!loading" description="条目不存在" />
    </Spin>
  </Page>
</template>
