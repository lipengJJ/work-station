<script lang="ts" setup>
import type { SkillsApi } from '#/api/core/skills';

import { computed, onMounted, ref, watch } from 'vue';

import { Page } from '@vben/common-ui';

import { Drawer, message, Tabs, Tag, Tree } from 'ant-design-vue';
import { Blocks, FileText, Puzzle, Search, ShieldAlert } from 'lucide-vue-next';

import {
  getSkillDetailApi,
  getSkillFileContentApi,
  listSkillFilesApi,
  listSkillsApi,
  updateSkillFileContentApi,
} from '#/api/core/skills';

function formatDateTime(iso: string) {
  if (!iso) return '';
  return iso.slice(0, 16).replace('T', ' ');
}

const RISK_COLOR: Record<string, string> = {
  low: 'success',
  medium: 'warning',
  high: 'error',
  blocked: 'error',
};
const RISK_LABEL: Record<string, string> = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
  blocked: '已阻止',
};

// -------------------------------------------------------------- 列表 ----

const skills = ref<SkillsApi.SkillSummary[]>([]);
const loading = ref(false);
const searchQuery = ref('');
const categoryFilter = ref<string>();

const categories = computed(() => {
  const set = new Set(skills.value.map((s) => s.category).filter((c): c is string => !!c));
  return [...set];
});

const filteredSkills = computed(() => {
  const q = searchQuery.value.trim().toLowerCase();
  return skills.value.filter((s) => {
    if (categoryFilter.value && s.category !== categoryFilter.value) return false;
    if (!q) return true;
    return s.display_name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q);
  });
});

async function fetchSkills() {
  loading.value = true;
  try {
    skills.value = await listSkillsApi();
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    loading.value = false;
  }
}

onMounted(fetchSkills);

// -------------------------------------------------------------- 详情抽屉 ----

const drawerOpen = ref(false);
const detailLoading = ref(false);
const detail = ref<SkillsApi.SkillDetail>();
const activeTab = ref('overview');

async function openDetail(skill: SkillsApi.SkillSummary) {
  drawerOpen.value = true;
  detailLoading.value = true;
  detail.value = undefined;
  activeTab.value = 'overview';
  resetFileState();
  try {
    detail.value = await getSkillDetailApi(skill.skill_key);
    await fetchFileTree(skill.skill_key);
  } catch (e: any) {
    message.error(`加载 Skill 详情失败：${e.message}`);
  } finally {
    detailLoading.value = false;
  }
}

// -------------------------------------------------------------- 文件树 & 预览 ----

interface TreeDataNode {
  key: string;
  title: string;
  isLeaf: boolean;
  children?: TreeDataNode[];
}

const fileTree = ref<TreeDataNode[]>([]);
const selectedFilePath = ref<string>();
const fileContent = ref('');
const fileTruncated = ref(false);
const fileLoading = ref(false);
const fileSaving = ref(false);

function toTreeData(nodes: SkillsApi.FileNode[]): TreeDataNode[] {
  return nodes.map((n) => ({
    key: n.path,
    title: n.name,
    isLeaf: n.type === 'file',
    children: n.type === 'dir' ? toTreeData(n.children) : undefined,
  }));
}

function resetFileState() {
  fileTree.value = [];
  selectedFilePath.value = undefined;
  fileContent.value = '';
  fileTruncated.value = false;
}

async function fetchFileTree(skillKey: string) {
  try {
    const tree = await listSkillFilesApi(skillKey);
    fileTree.value = toTreeData(tree);
  } catch (e: any) {
    message.error(`加载文件列表失败：${e.message}`);
  }
}

async function onSelectFile(_keys: (number | string)[], info: { node: { isLeaf?: boolean; key: number | string } }) {
  if (!info.node.isLeaf || !detail.value) return;
  const path = String(info.node.key);
  selectedFilePath.value = path;
  fileLoading.value = true;
  fileContent.value = '';
  try {
    const result = await getSkillFileContentApi(detail.value.skill_key, path);
    fileContent.value = result.content;
    fileTruncated.value = result.truncated;
  } catch (e: any) {
    fileContent.value = '';
    message.error(`预览失败：${e.message}`);
  } finally {
    fileLoading.value = false;
  }
}

async function saveFileContent() {
  if (!detail.value || !selectedFilePath.value) return;
  fileSaving.value = true;
  try {
    const result = await updateSkillFileContentApi(
      detail.value.skill_key,
      selectedFilePath.value,
      fileContent.value,
    );
    if (result.manifest_error) {
      message.warning(`文件已保存，但解析失败：${result.manifest_error}`);
    } else if (result.validation && !result.validation.valid) {
      message.warning(`文件已保存，但校验未通过：${result.validation.errors.join('；')}`);
    } else {
      message.success('保存成功，已生成新版本');
    }
    // 刷新详情，同步最新的校验结果、版本号和展示信息
    detail.value = await getSkillDetailApi(detail.value.skill_key);
  } catch (error: any) {
    message.error(`保存失败：${error.message}`);
  } finally {
    fileSaving.value = false;
  }
}

watch(drawerOpen, (open) => {
  if (!open) {
    detail.value = undefined;
    resetFileState();
  }
});
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-[hsl(var(--background-deep))] p-6 select-none">
      <div class="mb-6 shrink-0">
        <h1 class="text-xl font-extrabold text-[hsl(var(--foreground))]">Skill 管理</h1>
        <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
          查看已登记的 Skill、在页面中直接编辑它们的文件内容；导入、启停等能力在后续阶段开放
        </p>
      </div>

      <div class="mb-4 shrink-0 flex flex-wrap items-center gap-2">
        <div class="relative">
          <Search class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-[hsl(var(--muted-foreground))]" />
          <input
            v-model="searchQuery"
            placeholder="搜索 Skill 名称或描述"
            class="w-64 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] py-1.5 pr-3 pl-8 text-xs text-[hsl(var(--foreground))] outline-none focus:border-indigo-500"
          />
        </div>
        <select
          v-model="categoryFilter"
          class="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs text-[hsl(var(--foreground))] outline-none focus:border-indigo-500"
        >
          <option :value="undefined">全部分类</option>
          <option v-for="c in categories" :key="c" :value="c">{{ c }}</option>
        </select>
      </div>

      <div class="shrink-0 overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] shadow-xl">
        <div v-if="!loading && filteredSkills.length === 0" class="flex flex-col items-center justify-center gap-3 p-12 text-center">
          <div class="flex h-14 w-14 items-center justify-center rounded-2xl border border-indigo-500/20 bg-indigo-500/10">
            <Puzzle class="h-7 w-7 text-indigo-400" />
          </div>
          <p class="text-sm font-semibold text-[hsl(var(--foreground))]">
            {{ searchQuery || categoryFilter ? '没有匹配的 Skill' : '还没有登记任何 Skill' }}
          </p>
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] font-mono text-[11px] text-[hsl(var(--muted-foreground))] uppercase">
              <tr>
                <th class="px-4 py-3">名称及描述</th>
                <th class="px-4 py-3">分类</th>
                <th class="px-4 py-3">版本</th>
                <th class="px-4 py-3">模板数</th>
                <th class="px-4 py-3">来源</th>
                <th class="px-4 py-3">风险</th>
                <th class="px-4 py-3">状态</th>
                <th class="px-4 py-3">更新时间</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-[hsl(var(--border))]">
              <tr
                v-for="s in filteredSkills"
                :key="s.skill_key"
                tabindex="0"
                class="cursor-pointer transition-colors hover:bg-[hsl(var(--accent))] focus:bg-[hsl(var(--accent))] focus:outline-none focus-visible:ring-1 focus-visible:ring-indigo-500"
                @click="openDetail(s)"
                @keyup.enter="openDetail(s)"
              >
                <td class="max-w-md px-4 py-4">
                  <div class="font-semibold text-[hsl(var(--foreground))]">{{ s.display_name }}</div>
                  <div class="mt-0.5 truncate text-[11px] text-[hsl(var(--muted-foreground))]">{{ s.description }}</div>
                </td>
                <td class="px-4 py-4 text-[hsl(var(--muted-foreground))]">{{ s.category || '—' }}</td>
                <td class="px-4 py-4 font-mono text-[hsl(var(--foreground))]">{{ s.version || '—' }}</td>
                <td class="px-4 py-4 font-mono text-[hsl(var(--foreground))]">{{ s.template_count }}</td>
                <td class="px-4 py-4 text-[hsl(var(--muted-foreground))]">{{ s.source_type }}</td>
                <td class="px-4 py-4">
                  <Tag :color="RISK_COLOR[s.risk_level]">{{ RISK_LABEL[s.risk_level] || s.risk_level }}</Tag>
                </td>
                <td class="px-4 py-4">
                  <Tag :color="s.enabled ? 'success' : 'default'">{{ s.enabled ? '已启用' : '已禁用' }}</Tag>
                </td>
                <td class="px-4 py-4 text-[hsl(var(--muted-foreground))]">{{ formatDateTime(s.updated_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <Drawer v-model:open="drawerOpen" width="720px" :title="detail?.display_name || '加载中…'">
      <div v-if="detailLoading" class="p-6 text-center text-sm text-[hsl(var(--muted-foreground))]">加载中…</div>
      <template v-else-if="detail">
        <div class="mb-4 flex flex-wrap items-center gap-2">
          <Tag :color="RISK_COLOR[detail.risk_level]">{{ RISK_LABEL[detail.risk_level] || detail.risk_level }}</Tag>
          <Tag :color="detail.enabled ? 'success' : 'default'">{{ detail.enabled ? '已启用' : '已禁用' }}</Tag>
          <Tag v-for="t in detail.tags" :key="t">{{ t }}</Tag>
          <span class="ml-auto font-mono text-xs text-[hsl(var(--muted-foreground))]">{{ detail.skill_key }} · v{{ detail.version }}</span>
        </div>

        <Tabs v-model:active-key="activeTab">
          <Tabs.TabPane key="overview">
            <template #tab>
              <span class="flex items-center gap-1.5"><Blocks class="h-3.5 w-3.5" />概览</span>
            </template>

            <p class="text-sm text-[hsl(var(--muted-foreground))]">{{ detail.description }}</p>

            <div v-if="detail.default_prompt" class="mt-4 rounded-xl border-l-2 border-indigo-500/50 bg-[hsl(var(--background-deep))] px-4 py-3 text-xs text-[hsl(var(--muted-foreground))] italic">
              {{ detail.default_prompt }}
            </div>

            <div v-if="detail.runtime" class="mt-4">
              <div class="mb-2 text-xs font-bold text-[hsl(var(--muted-foreground))]">运行时能力</div>
              <div class="flex flex-wrap gap-2 text-xs">
                <Tag v-if="detail.runtime.recommended_model" color="blue">推荐模型：{{ detail.runtime.recommended_model }}</Tag>
                <Tag :color="detail.runtime.tools.google_search ? 'success' : 'default'">
                  Google 搜索{{ detail.runtime.tools.google_search ? '' : '（未启用）' }}
                </Tag>
                <Tag :color="detail.runtime.tools.url_context ? 'success' : 'default'">
                  URL 上下文{{ detail.runtime.tools.url_context ? '' : '（未启用）' }}
                </Tag>
              </div>
            </div>

            <div v-if="detail.validation && (detail.validation.errors.length || detail.validation.warnings.length)" class="mt-4">
              <div class="mb-2 flex items-center gap-1.5 text-xs font-bold text-[hsl(var(--muted-foreground))]">
                <ShieldAlert class="h-3.5 w-3.5" />校验结果
              </div>
              <ul class="space-y-1 text-xs">
                <li v-for="(e, i) in detail.validation.errors" :key="`err-${i}`" class="text-rose-400">✕ {{ e }}</li>
                <li v-for="(w, i) in detail.validation.warnings" :key="`warn-${i}`" class="text-amber-400">⚠ {{ w }}</li>
              </ul>
            </div>

            <div v-if="detail.instruction" class="mt-4">
              <div class="mb-2 text-xs font-bold text-[hsl(var(--muted-foreground))]">SKILL.md 核心指令</div>
              <pre class="max-h-96 overflow-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3 text-[11px] whitespace-pre-wrap text-[hsl(var(--muted-foreground))]">{{ detail.instruction }}</pre>
            </div>
          </Tabs.TabPane>

          <Tabs.TabPane key="templates">
            <template #tab>
              <span class="flex items-center gap-1.5"><Puzzle class="h-3.5 w-3.5" />分析模板（{{ detail.templates.length }}）</span>
            </template>

            <div v-if="detail.templates.length === 0" class="p-6 text-center text-xs text-[hsl(var(--muted-foreground))]">
              该 Skill 没有 workbench.yaml 声明的模板，使用通用文本输入界面
            </div>
            <div v-else class="space-y-3">
              <div
                v-for="t in detail.templates"
                :key="t.template_key"
                class="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4"
              >
                <div class="font-semibold text-[hsl(var(--foreground))]">{{ t.name }}</div>
                <p v-if="t.description" class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">{{ t.description }}</p>
                <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-[hsl(var(--muted-foreground))]">
                  <span v-if="t.prompt_path">提示模板：{{ t.prompt_path }}</span>
                  <span v-if="t.output_template_path">输出模板：{{ t.output_template_path }}</span>
                </div>
              </div>
            </div>
          </Tabs.TabPane>

          <Tabs.TabPane key="files">
            <template #tab>
              <span class="flex items-center gap-1.5"><FileText class="h-3.5 w-3.5" />文件</span>
            </template>

            <div class="flex gap-4">
              <div class="w-56 shrink-0 overflow-auto rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-2">
                <Tree
                  :tree-data="fileTree"
                  :selected-keys="selectedFilePath ? [selectedFilePath] : []"
                  @select="onSelectFile"
                />
              </div>
              <div class="min-w-0 flex-1">
                <div v-if="!selectedFilePath" class="p-6 text-center text-xs text-[hsl(var(--muted-foreground))]">
                  点击左侧文件查看内容
                </div>
                <div v-else>
                  <div class="mb-2 flex items-center justify-between font-mono text-[11px] text-[hsl(var(--muted-foreground))]">
                    <span>{{ selectedFilePath }}</span>
                    <span v-if="fileTruncated" class="text-amber-400">内容过长，仅预览（不可编辑）</span>
                  </div>
                  <div v-if="fileLoading" class="p-6 text-center text-xs text-[hsl(var(--muted-foreground))]">加载中…</div>
                  <template v-else>
                    <textarea
                      v-model="fileContent"
                      :disabled="fileTruncated"
                      spellcheck="false"
                      class="max-h-[560px] min-h-[320px] w-full resize-y rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3 font-mono text-[11px] leading-relaxed whitespace-pre text-[hsl(var(--muted-foreground))] outline-none focus:border-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
                    ></textarea>
                    <div class="mt-2 flex items-center justify-between">
                      <span class="text-[11px] text-[hsl(var(--muted-foreground))]">修改后点击保存，系统会自动重新校验并生成新版本</span>
                      <button
                        :disabled="fileTruncated || fileSaving || fileContent.length === 0"
                        class="rounded-lg bg-indigo-500 px-4 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-50"
                        @click="saveFileContent"
                      >
                        {{ fileSaving ? '保存中…' : '保存' }}
                      </button>
                    </div>
                  </template>
                </div>
              </div>
            </div>
          </Tabs.TabPane>
        </Tabs>
      </template>
    </Drawer>
  </Page>
</template>
