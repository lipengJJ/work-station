// 主题报告正文（daily.md Skill 模板产出的 Markdown）的解析 + 渲染，抽成公共模块——
// 「热点聚合 / 主题订阅」的报告详情页（topics/report.vue，运营视角，带发布/推送等
// 操作）和「热点聚合 / 日报」的读者视图（daily/index.vue，仿 AIHOT 排版）用的是
// 同一份数据格式，解析逻辑不该抄两份。
//
// 报告正文严格遵循 Skill 模板（skills/topic-weekly-digest/assets/prompts/daily.md）
// 的固定结构：`## 分组名` 下每条新闻是独立的 `### 标题 [id]` 三级小节；`## 今日速览`
// / `## 值得关注` / `## 数据来源` 这几个特殊小节没有三级小节，走普通段落/列表渲染。

export interface ParsedArticle {
  id: null | number;
  title: string;
  source: string;
  paragraphs: string[];
}

export interface ParsedSection {
  name: string;
  articles: ParsedArticle[];
  rawLines: string[];
}

export interface TocRow {
  index: string;
  name: string;
  count: number;
  preview: string;
}

/** linkify() 只需要引用条目的 id -> title，跟哪个页面的具体类型无关。 */
export interface LinkifyItem {
  title: string;
}

export function parseSections(md: string): ParsedSection[] {
  const lines = md.split(/\r?\n/);
  const sections: ParsedSection[] = [];
  let current: null | ParsedSection = null;
  let article: null | ParsedArticle = null;

  const flushArticle = () => {
    if (current && article) current.articles.push(article);
    article = null;
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (/^##\s/.test(line)) {
      flushArticle();
      current = { name: line.replace(/^##\s*/, '').trim(), articles: [], rawLines: [] };
      sections.push(current);
      continue;
    }
    if (!current) continue;
    if (/^###\s/.test(line)) {
      flushArticle();
      const text = line.replace(/^###\s*/, '').trim();
      const m = text.match(/^(.*?)\s*\[(\d+)\]\s*$/);
      article = m
        ? { id: Number(m[2]), title: m[1]!.trim(), source: '', paragraphs: [] }
        : { id: null, title: text, source: '', paragraphs: [] };
      continue;
    }
    if (article) {
      if (line.trim() !== '') article.paragraphs.push(line.trim());
    } else {
      current.rawLines.push(raw);
    }
  }
  flushArticle();

  // 从每篇文章最后一段末尾的“来源：xxx。”里把来源名剥出来，单独当标签展示，不在
  // 段落正文里重复出现一遍。
  for (const section of sections) {
    for (const item of section.articles) {
      const lastIdx = item.paragraphs.length - 1;
      if (lastIdx < 0) continue;
      const last = item.paragraphs[lastIdx]!;
      const m = last.match(/来源[:：]\s*([^\s。.，,]+)[。.]?\s*$/);
      if (m) {
        item.source = m[1]!;
        item.paragraphs[lastIdx] = last.slice(0, m.index).trimEnd();
      }
    }
  }
  return sections;
}

/** “今日看点”总览：只统计带三级小节的分类（今日速览/值得关注/数据来源这类没有
 * 小节的直接跳过），index/count/preview 供概览卡片展示。 */
export function buildToc(sections: ParsedSection[]): TocRow[] {
  const rows: TocRow[] = [];
  let idx = 0;
  for (const section of sections) {
    if (section.articles.length === 0) continue;
    idx += 1;
    rows.push({
      index: String(idx).padStart(2, '0'),
      name: section.name,
      count: section.articles.length,
      preview: section.articles[0]?.title || '',
    });
  }
  return rows;
}

export const escapeHtml = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// 引用 [n] 一律指向站内文章详情页（/hotlist/items/:id），不再跳去原文外链——
// 原文外链只在文章详情页里作为一个明确的“查看原文”按钮单独放出来。
export function makeLinkify(items: Map<number, LinkifyItem>) {
  return (s: string) => {
    let out = s.replace(/\[(\d+)\]/g, (_, n) => {
      const id = Number(n);
      const item = items.get(id);
      if (item) {
        return `<a href="/hotlist/items/${id}" target="_blank" rel="noopener" class="ref-link" title="${escapeHtml(item.title)}">[${n}]</a>`;
      }
      return `<span class="ref-missing" title="条目已被清理">[${n}]</span>`;
    });
    out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    // 排除前面紧跟 href=" 的裸 URL：避免把上面两步已生成的 <a href="URL" ...> 里的
    // URL 文本再匹配一次，导致嵌套插入 <a> 破坏原有标签的属性结构。
    out = out.replace(/(?<!href=")(https?:\/\/[^\s<)"]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
    out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
    return out;
  };
}

function renderLegacyLines(rawLines: string[], linkify: (s: string) => string) {
  const out: string[] = [];
  let inList = false;
  const closeList = () => {
    if (inList) {
      out.push('</ul>');
      inList = false;
    }
  };
  for (const raw of rawLines) {
    const line = raw.trimEnd();
    if (/^[-*]\s/.test(line)) {
      if (!inList) {
        out.push('<ul>');
        inList = true;
      }
      out.push(`<li>${linkify(escapeHtml(line.replace(/^[-*]\s*/, '')))}</li>`);
    } else if (line.trim() === '') {
      closeList();
    } else {
      closeList();
      out.push(`<p>${linkify(escapeHtml(line))}</p>`);
    }
  }
  closeList();
  return out.join('\n');
}

export interface RenderBodyOptions {
  /** 自定义来源标签渲染（不传就是原来那个单个灰色小胶囊）；返回空串等于不渲染。 */
  renderSourceTag?: (article: ParsedArticle) => string;
  /** 标题旁边要不要再放一个 [id] 引用徽标——标题本身已经是可点击链接了，徽标是
   * 冗余的第二个入口，默认保留（report.vue 的运营视角用它标出"这条有真实
   * 引用 id"），日报读者视图不需要，传 false 关掉。 */
  showTitleRefBadge?: boolean;
  /** 每个编号分类（含标题+旗下文章卡片）要不要整体包一层容器 div（class
   * "section-box"），配合外部 CSS 做成跟"今日看点"同一种圆角卡片背景；不传
   * 就是原来 report.vue 那种直接摊在页面背景上的扁平排版。 */
  wrapSections?: boolean;
}

export function renderBody(
  sections: ParsedSection[],
  linkify: (s: string) => string,
  options: RenderBodyOptions = {},
) {
  const renderSourceTag =
    options.renderSourceTag ??
    ((article: ParsedArticle) =>
      article.source ? `<span class="source-tag">${escapeHtml(article.source)}</span>` : '');
  const showTitleRefBadge = options.showTitleRefBadge ?? true;
  const wrapSections = options.wrapSections ?? false;

  const html: string[] = [];
  let newsIdx = 0;
  for (const section of sections) {
    if (section.articles.length > 0) {
      newsIdx += 1;
      if (wrapSections) html.push('<div class="section-box">');
      html.push(
        '<div class="section-header">' +
          `<span class="section-index">${String(newsIdx).padStart(2, '0')}</span>` +
          `<span class="section-name">${escapeHtml(section.name)}</span>` +
          `<span class="section-count">${section.articles.length} 篇</span>` +
          '</div>',
      );
      for (const item of section.articles) {
        const href = item.id ? `/hotlist/items/${item.id}` : '';
        html.push('<div class="article-card">');
        html.push('<h3>');
        if (href) {
          html.push(
            `<a href="${href}" target="_blank" rel="noopener" class="article-title-link">${linkify(escapeHtml(item.title))}</a>`,
          );
          if (showTitleRefBadge) {
            html.push(`<a href="${href}" target="_blank" rel="noopener" class="ref-link">[${item.id}]</a>`);
          }
        } else {
          html.push(`<span>${linkify(escapeHtml(item.title))}</span>`);
        }
        html.push('</h3>');
        const tag = renderSourceTag(item);
        if (tag) html.push(tag);
        for (const p of item.paragraphs) {
          if (p.trim()) html.push(`<p>${linkify(escapeHtml(p))}</p>`);
        }
        html.push('</div>');
      }
      if (wrapSections) html.push('</div>');
    } else if (section.rawLines.some((l) => l.trim() !== '')) {
      html.push(`<h2>${escapeHtml(section.name)}</h2>`);
      html.push(renderLegacyLines(section.rawLines, linkify));
    }
  }
  return html.join('\n');
}
