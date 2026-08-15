<script lang="ts" setup>
import type { SkillsApi } from '#/api/core/skills';
import type { XhsApi } from '#/api/core/xhs';

import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';

import {
  Alert,
  Avatar,
  Button,
  Card,
  Carousel,
  Checkbox,
  Col,
  Drawer,
  Empty,
  Form,
  FormItem,
  Image,
  Input,
  message,
  Modal,
  Radio,
  RadioGroup,
  Row,
  Select,
  Switch,
  Tag,
  Typography,
} from 'ant-design-vue';
import { PanelLeftOpen } from 'lucide-vue-next';
import MarkdownIt from 'markdown-it';

import { getChatConfigApi, setChatConfigApi } from '#/api/core/chat';
import type { ChatApi } from '#/api/core/chat';
import { listSkillsApi, listSkillTemplatesApi } from '#/api/core/skills';
import {
  addXhsProjectNotesApi,
  appendXhsReportApi,
  buildXhsMediaProxyUrl,
  createXhsAnalysisProjectApi,
  deleteXhsAnalysisProjectApi,
  deleteXhsProjectAnalysisApi,
  getXhsNoteTaskNotesApi,
  listXhsAnalysisProjectsApi,
  listXhsAnalysisTemplatesApi,
  listXhsNoteTasksApi,
  listXhsProjectAnalysesApi,
  listXhsProjectNotesApi,
  listXhsReportsApi,
  removeXhsProjectNoteApi,
  renameXhsAnalysisProjectApi,
  saveXhsAnalysisReportApi,
  saveXhsCombinedReportApi,
  setXhsProjectAnalysisFeedbackApi,
  streamXhsProjectAnalysisApi,
} from '#/api/core/xhs';
import { groupNotesByRecency } from '#/utils/note-grouping';

const router = useRouter();

const TextArea = Input.TextArea;

const STATUS_LABEL: Record<string, string> = {
  running: '分析中',
  success: '已完成',
  failed: '失败',
};
const STATUS_COLOR: Record<string, string> = {
  running: 'processing',
  success: 'success',
  failed: 'error',
};

// 后端存的是不带时区偏移的 UTC 字符串，直接按字符串截断展示，不走 new Date() 解析——
// 避免被浏览器当成本地时间再转一遍导致时间对不上。
function formatDateTime(iso: string) {
  if (!iso) return '';
  return iso.slice(0, 16).replace('T', ' ');
}
function statusLabel(s: string) {
  return STATUS_LABEL[s] ?? s;
}
function statusColor(s: string) {
  return STATUS_COLOR[s] ?? 'default';
}

const md = new MarkdownIt({ breaks: true, linkify: true });

/**
 * 渲染 Markdown，并把"引用笔记：[2][8]"这种约定格式转成可点击的编号徽标。
 * 只对紧跟在"引用笔记："后面的 [数字] 做替换，注入的内容只有数字本身（来自正则捕获），
 * 不会把笔记正文里的任意文本当成 HTML 插入，不存在 XSS 风险。
 */
function renderAnalysisHtml(text: string) {
  let html = md.render(text || '');
  html = html.replace(/(引用笔记[:：]\s*)((?:\[\d+\]\s*)+)/g, (_match, label: string, nums: string) => {
    const badges = [...nums.matchAll(/\d+/g)]
      .map((m) => `<span class="cite-badge" data-note-index="${m[0]}">${m[0]}</span>`)
      .join('');
    return `${label}${badges}`;
  });
  return html;
}

// ------------------------------------------------------------- 项目列表 ----

const projects = ref<XhsApi.AnalysisProject[]>([]);
const projectsLoading = ref(false);
const projectSearch = ref('');

const filteredProjects = computed(() => {
  const q = projectSearch.value.trim().toLowerCase();
  if (!q) return projects.value;
  return projects.value.filter((p) => p.name.toLowerCase().includes(q));
});

async function fetchProjects() {
  projectsLoading.value = true;
  try {
    projects.value = await listXhsAnalysisProjectsApi();
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    projectsLoading.value = false;
  }
}

const createModalOpen = ref(false);
const newProjectName = ref('');
const creating = ref(false);

function openCreateModal() {
  newProjectName.value = '';
  createModalOpen.value = true;
}

async function submitCreateProject() {
  const name = newProjectName.value.trim();
  if (!name) {
    message.error('请输入项目名称');
    return;
  }
  creating.value = true;
  try {
    const project = await createXhsAnalysisProjectApi(name);
    createModalOpen.value = false;
    message.success('已创建');
    await fetchProjects();
    openProject(project);
  } catch (e: any) {
    message.error(`创建失败：${e.message}`);
  } finally {
    creating.value = false;
  }
}

function removeProject(project: XhsApi.AnalysisProject) {
  Modal.confirm({
    title: `确定删除项目「${project.name}」吗？`,
    content: '项目里的笔记引用和分析历史都会被删除，此操作不可恢复。',
    okType: 'danger',
    onOk: async () => {
      try {
        await deleteXhsAnalysisProjectApi(project.id);
        projects.value = projects.value.filter((p) => p.id !== project.id);
        if (selectedProject.value?.id === project.id) {
          selectedProject.value = undefined;
          notes.value = [];
          analyses.value = [];
        }
        message.success('已删除');
      } catch (e: any) {
        message.error(`删除失败：${e.message}`);
      }
    },
  });
}

const renameModalOpen = ref(false);
const renameValue = ref('');
const renaming = ref(false);

function openRenameModal() {
  if (!selectedProject.value) return;
  renameValue.value = selectedProject.value.name;
  renameModalOpen.value = true;
}

async function submitRename() {
  const projectId = selectedProject.value?.id;
  const name = renameValue.value.trim();
  if (!projectId || !name) {
    message.error('请输入项目名称');
    return;
  }
  renaming.value = true;
  try {
    const updated = await renameXhsAnalysisProjectApi(projectId, name);
    if (selectedProject.value) selectedProject.value.name = updated.name;
    const row = projects.value.find((p) => p.id === projectId);
    if (row) row.name = updated.name;
    renameModalOpen.value = false;
    message.success('已重命名');
  } catch (e: any) {
    message.error(`重命名失败：${e.message}`);
  } finally {
    renaming.value = false;
  }
}

// ------------------------------------------------------------- 项目详情 ----

const selectedProject = ref<XhsApi.AnalysisProject>();
// 项目列表选定项目后不再常驻左栏，改成按需弹出的抽屉，把宽度让给对话区
const projectDrawerOpen = ref(false);
const notes = ref<XhsApi.Note[]>([]);
const notesLoading = ref(false);
const noteSearch = ref('');
const notesTab = ref<'all' | 'selected'>('all');
// 当前"选中用于分析"的笔记子集，默认全选（等价于对项目全部笔记做分析）
const selectedNoteIds = ref<Set<string>>(new Set());

const filteredNotes = computed(() => {
  const q = noteSearch.value.trim().toLowerCase();
  if (!q) return notes.value;
  return notes.value.filter(
    (n) => n.title.toLowerCase().includes(q) || n.desc.toLowerCase().includes(q),
  );
});
const notesForTab = computed(() => {
  if (notesTab.value === 'all') return filteredNotes.value;
  return filteredNotes.value.filter((n) => selectedNoteIds.value.has(n.note_id));
});
// 仅用于展示分组：编号（noteIndexOf）还是按 notes（项目原始顺序）算，跟 Gemini 看到的编号对得上
const groupedNotesForTab = computed(() => groupNotesByRecency(notesForTab.value));
function noteIndexOf(noteId: string) {
  return notes.value.findIndex((n) => n.note_id === noteId) + 1;
}
function toggleSelectedNote(noteId: string) {
  const next = new Set(selectedNoteIds.value);
  if (next.has(noteId)) {
    next.delete(noteId);
  } else {
    next.add(noteId);
  }
  selectedNoteIds.value = next;
}
function clearSelection() {
  selectedNoteIds.value = new Set();
}

async function fetchProjectNotes(projectId: number) {
  notesLoading.value = true;
  try {
    notes.value = await listXhsProjectNotesApi(projectId);
    selectedNoteIds.value = new Set(notes.value.map((n) => n.note_id));
  } catch (e: any) {
    message.error(`加载笔记失败：${e.message}`);
  } finally {
    notesLoading.value = false;
  }
}

function openProject(project: XhsApi.AnalysisProject) {
  selectedProject.value = project;
  notes.value = [];
  noteSearch.value = '';
  notesTab.value = 'all';
  questionInput.value = '';
  fetchProjectNotes(project.id);
  fetchAnalyses(project.id);
  projectDrawerOpen.value = false;
}

function coverOf(note: XhsApi.Note) {
  return note.video_cover || note.image_list[0] || '';
}
function coverProxied(note: XhsApi.Note) {
  const url = coverOf(note);
  if (!url) return '';
  return buildXhsMediaProxyUrl(url, {
    noteId: note.note_id,
    kind: note.video_cover ? 'cover' : 'image',
    index: note.video_cover ? undefined : 0,
  });
}
function galleryProxied(note: XhsApi.Note, index: number) {
  return buildXhsMediaProxyUrl(note.image_list[index] ?? '', { noteId: note.note_id, kind: 'image', index });
}
function videoProxied(note: XhsApi.Note) {
  if (!note.video_addr) return '';
  return buildXhsMediaProxyUrl(note.video_addr, { noteId: note.note_id, kind: 'video' });
}
function openInXhs(url: string) {
  window.open(url, '_blank', 'noopener,noreferrer');
}

const detailModalOpen = ref(false);
const detailNote = ref<XhsApi.Note>();

function openDetail(note: XhsApi.Note) {
  detailNote.value = note;
  detailModalOpen.value = true;
}

function onThreadClick(e: MouseEvent) {
  const target = e.target as HTMLElement;
  const idxAttr = target?.dataset?.noteIndex;
  if (!idxAttr) return;
  const note = notes.value[Number(idxAttr) - 1];
  if (note) {
    openDetail(note);
  } else {
    message.info('未找到对应的笔记，可能已被移出项目');
  }
}

function removeNoteFromProject(note: XhsApi.Note) {
  const projectId = selectedProject.value?.id;
  if (!projectId) return;
  Modal.confirm({
    title: `确定把《${note.title || '无标题'}》移出项目吗？`,
    content: '只是从这个分析项目里移除，原采集任务里的笔记数据不受影响。',
    okType: 'danger',
    onOk: async () => {
      try {
        await removeXhsProjectNoteApi(projectId, note.note_id);
        notes.value = notes.value.filter((n) => n.note_id !== note.note_id);
        const next = new Set(selectedNoteIds.value);
        next.delete(note.note_id);
        selectedNoteIds.value = next;
        if (selectedProject.value) selectedProject.value.note_count -= 1;
        detailModalOpen.value = false;
        message.success('已移出项目');
      } catch (e: any) {
        message.error(`移出失败：${e.message}`);
      }
    },
  });
}

// -------------------------------------------------------------- 添加笔记 ----

const addNotesModalOpen = ref(false);
const sourceTasks = ref<XhsApi.CollectTask[]>([]);
const sourceTasksLoading = ref(false);
const sourceTaskId = ref<number>();
const sourceNotes = ref<XhsApi.Note[]>([]);
const sourceNotesLoading = ref(false);
const pickNoteIds = ref<Set<string>>(new Set());
const adding = ref(false);

const allSourcePicked = computed(
  () => sourceNotes.value.length > 0 && pickNoteIds.value.size === sourceNotes.value.length,
);

async function openAddNotesModal() {
  addNotesModalOpen.value = true;
  sourceTaskId.value = undefined;
  sourceNotes.value = [];
  pickNoteIds.value = new Set();
  sourceTasksLoading.value = true;
  try {
    const page = await listXhsNoteTasksApi({ page_size: 200 });
    sourceTasks.value = page.items;
  } catch (e: any) {
    message.error(`加载采集任务失败：${e.message}`);
  } finally {
    sourceTasksLoading.value = false;
  }
}

async function onSourceTaskChange(taskId: number) {
  sourceTaskId.value = taskId;
  sourceNotes.value = [];
  pickNoteIds.value = new Set();
  sourceNotesLoading.value = true;
  try {
    const data = await getXhsNoteTaskNotesApi(taskId, { page_size: 500 });
    sourceNotes.value = data.items;
  } catch (e: any) {
    message.error(`加载笔记失败：${e.message}`);
  } finally {
    sourceNotesLoading.value = false;
  }
}

function togglePickNote(noteId: string) {
  const next = new Set(pickNoteIds.value);
  if (next.has(noteId)) {
    next.delete(noteId);
  } else {
    next.add(noteId);
  }
  pickNoteIds.value = next;
}

function toggleSelectAllSource() {
  pickNoteIds.value = allSourcePicked.value
    ? new Set()
    : new Set(sourceNotes.value.map((n) => n.note_id));
}

async function submitAddNotes() {
  const projectId = selectedProject.value?.id;
  if (!projectId || !sourceTaskId.value || pickNoteIds.value.size === 0) return;
  adding.value = true;
  try {
    const addedIds = [...pickNoteIds.value];
    notes.value = await addXhsProjectNotesApi(projectId, sourceTaskId.value, addedIds);
    selectedNoteIds.value = new Set([...selectedNoteIds.value, ...addedIds]);
    if (selectedProject.value) selectedProject.value.note_count = notes.value.length;
    addNotesModalOpen.value = false;
    message.success('已添加到项目');
  } catch (e: any) {
    message.error(`添加失败：${e.message}`);
  } finally {
    adding.value = false;
  }
}

// -------------------------------------------------------------- 分析模板 ----

const templates = ref<XhsApi.AnalysisTemplate[]>([]);
const selectedTemplateId = ref('general');

async function fetchTemplates() {
  try {
    templates.value = await listXhsAnalysisTemplatesApi();
    if (templates.value.length && !templates.value.some((t) => t.id === selectedTemplateId.value)) {
      selectedTemplateId.value = templates.value[0]!.id;
    }
  } catch (e: any) {
    message.error(`加载分析模板失败：${e.message}`);
  }
}

const templateOptions = computed(() => templates.value.map((t) => ({ value: t.id, label: t.label })));
const quickPrompts = computed(
  () => templates.value.find((t) => t.id === selectedTemplateId.value)?.quick_prompts ?? [],
);

// -------------------------------------------------------------- Skill（可选） ----
// 不选 Skill 就走上面内置的写死模板（general/travel/ideas），选了 Skill 就把选中的笔记
// 当业务上下文注入 Skill 的规则，两条路径互斥，由后端 skill_key 是否传值决定。

const skills = ref<SkillsApi.SkillSummary[]>([]);
const selectedSkillKey = ref<string>();
const skillTemplates = ref<SkillsApi.SkillTemplate[]>([]);
const selectedSkillTemplateKey = ref<string>();
const enableSearch = ref(false);

const skillOptions = computed(() => skills.value.map((s) => ({ value: s.skill_key, label: s.display_name })));
const skillTemplateOptions = computed(() =>
  skillTemplates.value.map((t) => ({ value: t.template_key, label: t.name })),
);

async function fetchSkills() {
  try {
    skills.value = await listSkillsApi({ enabled: true });
  } catch (e: any) {
    message.error(`加载 Skill 列表失败：${e.message}`);
  }
}

watch(selectedSkillKey, async (skillKey) => {
  selectedSkillTemplateKey.value = undefined;
  skillTemplates.value = [];
  if (!skillKey) return;
  try {
    skillTemplates.value = await listSkillTemplatesApi(skillKey);
  } catch (e: any) {
    message.error(`加载 Skill 模板失败：${e.message}`);
  }
});

// -------------------------------------------------------------- 模型设置 ----
// AI 分析和 AI 助手（聊天）共用同一份 Gemini Key/模型/思考模式配置（后端 app/gemini/config.py），
// 这里直接复用 chat 的配置接口，不用另存一份。

const modelModalOpen = ref(false);
const modelConfig = ref<ChatApi.Config>({
  provider: 'gemini',
  configured: false,
  model: '',
  thinking_enabled: false,
  providers: [],
});
const modelForm = reactive<{
  provider: string;
  api_key: string;
  model: string;
  thinking_enabled: boolean;
}>({ provider: 'gemini', api_key: '', model: '', thinking_enabled: false });
const modelSaving = ref(false);
// 厂商元数据来自后端注册表（label/预设模型/思考模式支持），不存在时兜底第一个
const currentProviderMeta = computed(
  () =>
    modelConfig.value.providers.find((p) => p.key === modelForm.provider) ??
    modelConfig.value.providers[0],
);
const modelProviderLabel = computed(
  () => currentProviderMeta.value?.label ?? modelForm.provider,
);
const modelPresets = computed(() => currentProviderMeta.value?.presets ?? []);

async function fetchModelConfig() {
  try {
    modelConfig.value = await getChatConfigApi();
  } catch (e: any) {
    message.error(`加载模型配置失败：${e.message}`);
  }
}

function openModelModal() {
  modelForm.api_key = '';
  modelForm.provider = modelConfig.value.provider;
  modelForm.model = modelConfig.value.model;
  modelForm.thinking_enabled = modelConfig.value.thinking_enabled;
  modelModalOpen.value = true;
}

function changeModelProvider(provider: string) {
  modelForm.provider = provider;
  const meta = modelConfig.value.providers.find((p) => p.key === provider);
  modelForm.model = modelConfig.value.model;
  modelForm.thinking_enabled = meta?.supports_thinking
    ? modelConfig.value.thinking_enabled
    : false;
}

async function submitModelConfig() {
  const apiKey = modelForm.api_key.trim();
  if (!modelConfig.value.configured && !apiKey) {
    message.error(`请填写 ${modelProviderLabel.value} API Key`);
    return;
  }
  modelSaving.value = true;
  try {
    modelConfig.value = await setChatConfigApi({
      provider: modelForm.provider,
      api_key: apiKey || undefined,
      model: modelForm.model.trim() || modelConfig.value.model,
      thinking_enabled: modelForm.thinking_enabled,
    });
    modelModalOpen.value = false;
    message.success('已保存');
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    modelSaving.value = false;
  }
}

// -------------------------------------------------------------- AI 分析 ----

const analyses = ref<XhsApi.NoteAnalysis[]>([]);
// 后端按创建时间倒序返回（方便别处取"最新一条"），聊天式展示要按时间正序从上往下念
const orderedAnalyses = computed(() => [...analyses.value].reverse());
const analysesLoading = ref(false);
const questionInput = ref('');
const analyzing = ref(false);
const streamingEntry = ref<undefined | { question: string; text: string }>();
const threadRef = ref<HTMLElement>();
// 笔记多、走 Skill/思考模式时 Gemini 有时会跑很久甚至触发后端 5 分钟读超时，之前没有
// 任何办法中途退出——卡住的这条既不在 analyses 列表里（还没存），也没有 error，只能干等。
// 用 AbortController 中断底层 fetch，配合下面 cancelAnalysis 让用户随时能把这轮"删掉"。
let analysisAbortController: AbortController | undefined;

// 选中的笔记如果就是全部笔记，等价于不传 note_ids（用项目全部笔记）
const effectiveNoteIds = computed(() =>
  selectedNoteIds.value.size === notes.value.length ? undefined : [...selectedNoteIds.value],
);

async function scrollThreadToBottom() {
  await nextTick();
  const el = threadRef.value;
  if (el) el.scrollTop = el.scrollHeight;
}

async function fetchAnalyses(projectId: number) {
  analysesLoading.value = true;
  try {
    analyses.value = await listXhsProjectAnalysesApi(projectId);
    await scrollThreadToBottom();
  } catch (e: any) {
    message.error(`加载分析记录失败：${e.message}`);
  } finally {
    analysesLoading.value = false;
  }
}

async function runAnalysis(rawQuestion: string) {
  const projectId = selectedProject.value?.id;
  const question = rawQuestion.trim();
  if (!projectId || !question || analyzing.value) return;
  if (selectedNoteIds.value.size === 0) {
    message.error('请至少在右侧选择一篇笔记再分析');
    return;
  }

  analyzing.value = true;
  streamingEntry.value = { question, text: '' };
  analysisAbortController = new AbortController();
  await scrollThreadToBottom();

  try {
    await streamXhsProjectAnalysisApi(
      projectId,
      question,
      {
        onDelta: (delta) => {
          if (streamingEntry.value) streamingEntry.value.text += delta;
          scrollThreadToBottom();
        },
        onError: (err) => {
          message.error(err);
        },
        onEnd: () => {
          analyzing.value = false;
          streamingEntry.value = undefined;
          fetchAnalyses(projectId);
        },
      },
      {
        noteIds: effectiveNoteIds.value,
        template: selectedTemplateId.value,
        skillKey: selectedSkillKey.value,
        skillTemplateKey: selectedSkillTemplateKey.value,
        enableSearch: enableSearch.value,
      },
      analysisAbortController.signal,
    );
  } catch (e: any) {
    // 用户主动取消（AbortController.abort()）触发的是这里的 reject，不是真的失败，
    // 不需要弹错误提示——cancelAnalysis 已经处理过状态重置和提示了
    if (e.name !== 'AbortError') {
      message.error(`分析失败：${e.message}`);
      analyzing.value = false;
      streamingEntry.value = undefined;
    }
  }
}

function cancelAnalysis() {
  analysisAbortController?.abort();
  analyzing.value = false;
  streamingEntry.value = undefined;
  message.info('已取消，这轮没有保存');
}

function startAnalysis() {
  const question = questionInput.value;
  questionInput.value = '';
  runAnalysis(question);
}

function handleEnter(e: KeyboardEvent) {
  if (e.shiftKey) return;
  e.preventDefault();
  startAnalysis();
}

function useQuickPrompt(prompt: string) {
  runAnalysis(prompt);
}

function regenerate(analysis: XhsApi.NoteAnalysis) {
  runAnalysis(analysis.question);
}

function removeAnalysis(analysis: XhsApi.NoteAnalysis) {
  const projectId = selectedProject.value?.id;
  if (!projectId) return;
  Modal.confirm({
    title: '确定删除这条分析记录吗？',
    content: '此操作不可恢复。',
    okType: 'danger',
    onOk: async () => {
      try {
        await deleteXhsProjectAnalysisApi(projectId, analysis.id);
        analyses.value = analyses.value.filter((a) => a.id !== analysis.id);
        message.success('已删除');
      } catch (e: any) {
        message.error(`删除失败：${e.message}`);
      }
    },
  });
}

async function setFeedback(analysis: XhsApi.NoteAnalysis, feedback: 'down' | 'up') {
  const projectId = selectedProject.value?.id;
  if (!projectId) return;
  const next = analysis.feedback === feedback ? null : feedback;
  try {
    const updated = await setXhsProjectAnalysisFeedbackApi(projectId, analysis.id, next);
    const idx = analyses.value.findIndex((a) => a.id === analysis.id);
    if (idx !== -1) analyses.value[idx] = updated;
  } catch (e: any) {
    message.error(`操作失败：${e.message}`);
  }
}

async function copyResult(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    message.success('已复制');
  } catch {
    message.error('复制失败，可能是浏览器不支持或未授权剪贴板权限');
  }
}

// 之前"导出报告"只是把当前对话拼成 markdown 在浏览器本地下载，不会存进后端、分析报告
// 列表里也看不到。改成和单条"保存为报告"一样走后端持久化；多轮对话不是每轮都要存，
// 弹窗里勾选要包含哪几轮，并且支持存成新报告或追加到一份已有报告后面。
const saveCombinedReportModalOpen = ref(false);
const saveCombinedReportTitle = ref('');
const saveCombinedReportMode = ref<'append' | 'new'>('new');
const selectedAnalysisIdsForReport = ref<Set<number>>(new Set());
const existingReports = ref<XhsApi.ReportListItem[]>([]);
const existingReportsLoading = ref(false);
const appendTargetReportId = ref<number>();
const savingCombinedReport = ref(false);

const successfulAnalyses = computed(() => orderedAnalyses.value.filter((a) => a.status === 'success'));

function toggleReportAnalysis(id: number) {
  const next = new Set(selectedAnalysisIdsForReport.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  selectedAnalysisIdsForReport.value = next;
}

async function openSaveCombinedReportModal() {
  if (!selectedProject.value) return;
  saveCombinedReportTitle.value = `${selectedProject.value.name} 完整分析报告`;
  saveCombinedReportMode.value = 'new';
  appendTargetReportId.value = undefined;
  // 默认全选，用户可以取消勾掉不想存进报告的那几轮
  selectedAnalysisIdsForReport.value = new Set(successfulAnalyses.value.map((a) => a.id));
  saveCombinedReportModalOpen.value = true;

  existingReportsLoading.value = true;
  try {
    const res = await listXhsReportsApi({ project_id: selectedProject.value.id, page_size: 100 });
    existingReports.value = res.items;
  } catch {
    existingReports.value = [];
  } finally {
    existingReportsLoading.value = false;
  }
}

async function confirmSaveCombinedReport() {
  const projectId = selectedProject.value?.id;
  if (!projectId) return;
  const analysisIds = [...selectedAnalysisIdsForReport.value];
  if (analysisIds.length === 0) {
    message.error('请至少选择一轮分析');
    return;
  }
  const noteIds = notes.value.map((n) => n.note_id);
  savingCombinedReport.value = true;
  try {
    let report;
    if (saveCombinedReportMode.value === 'append') {
      if (!appendTargetReportId.value) {
        message.error('请选择要追加到哪份报告');
        return;
      }
      report = await appendXhsReportApi(appendTargetReportId.value, noteIds, analysisIds);
      message.success('已追加到报告');
    } else {
      if (!saveCombinedReportTitle.value.trim()) {
        message.error('请输入报告标题');
        return;
      }
      report = await saveXhsCombinedReportApi(projectId, saveCombinedReportTitle.value.trim(), noteIds, analysisIds);
      message.success('已整理为报告');
    }
    saveCombinedReportModalOpen.value = false;
    router.push(`/xhs/analysis-reports/${report.id}`);
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    savingCombinedReport.value = false;
  }
}

// ---------------------------------------------------------- 保存为报告 ----

const saveReportModalOpen = ref(false);
const saveReportTarget = ref<XhsApi.NoteAnalysis>();
const saveReportTitle = ref('');
const savingReport = ref(false);

function openSaveReportModal(a: XhsApi.NoteAnalysis) {
  saveReportTarget.value = a;
  saveReportTitle.value = a.question.length > 60 ? `${a.question.slice(0, 60)}…` : a.question;
  saveReportModalOpen.value = true;
}

async function confirmSaveReport() {
  const projectId = selectedProject.value?.id;
  const analysis = saveReportTarget.value;
  if (!projectId || !analysis) return;
  if (!saveReportTitle.value.trim()) {
    message.error('请输入报告标题');
    return;
  }
  // 证据编号约定和 noteIndexOf/onThreadClick 一致：按项目当前笔记顺序编号，
  // 不是本轮实际选中的子集——历史分析没有落库当时用的笔记子集，只能用这个和现有
  // 引用徽标口径一致的近似值，不能假装能精确复原。
  const noteIds = notes.value.map((n) => n.note_id);
  savingReport.value = true;
  try {
    const report = await saveXhsAnalysisReportApi(projectId, analysis.id, saveReportTitle.value.trim(), noteIds);
    saveReportModalOpen.value = false;
    message.success('已保存为报告');
    router.push(`/xhs/analysis-reports/${report.id}`);
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    savingReport.value = false;
  }
}

onMounted(() => {
  fetchProjects();
  fetchTemplates();
  fetchModelConfig();
  fetchSkills();
});
</script>

<template>
  <Page :auto-content-height="false">
    <!-- 未选择项目：项目列表就是主内容，全宽展示，不占用对话区宽度 -->
    <Card v-if="!selectedProject" size="small" title="AI 分析">
      <template #extra>
        <Button size="small" type="primary" @click="openCreateModal">新建</Button>
      </template>
      <Input v-model:value="projectSearch" placeholder="搜索项目" allow-clear style="margin-bottom: 12px; max-width: 320px" />
      <Empty v-if="!projectsLoading && !filteredProjects.length" description="暂无分析项目，新建一个开始吧" />
      <Row v-else :gutter="[12, 12]">
        <Col v-for="project in filteredProjects" :key="project.id" :xs="24" :sm="12" :md="8" :lg="6">
          <Card size="small" hoverable style="cursor: pointer" @click="openProject(project)">
            <div style="font-weight: 500">{{ project.name }}</div>
            <div style="margin-top: 4px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
              <Tag color="blue">{{ project.note_count }} 篇</Tag>
              <Typography.Text type="secondary" style="font-size: 12px">
                {{ formatDateTime(project.created_at) }}
              </Typography.Text>
            </div>
          </Card>
        </Col>
      </Row>
    </Card>

    <!-- 已选择项目：对话区（更宽）+ 来源笔记，项目列表改成按需弹出的抽屉 -->
    <Row v-else :gutter="16">
      <Col :span="18">
        <Card size="small">
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px">
            <Button size="small" @click="projectDrawerOpen = true">
              <PanelLeftOpen style="width: 14px; height: 14px; margin-right: 4px; vertical-align: -2px" />
              切换项目
            </Button>
            <strong style="font-size: 16px">{{ selectedProject.name }}</strong>
            <a @click="openRenameModal">✏️</a>
            <Tag color="blue">{{ selectedProject.note_count }} 篇笔记</Tag>
            <Select
              v-model:value="selectedTemplateId"
              size="small"
              style="width: 200px"
              :disabled="!!selectedSkillKey"
              :options="templateOptions"
            />
            <Select
              v-model:value="selectedSkillKey"
              size="small"
              style="width: 200px"
              placeholder="使用 Skill（可选）"
              allow-clear
              :options="skillOptions"
            />
            <Select
              v-if="selectedSkillKey"
              v-model:value="selectedSkillTemplateKey"
              size="small"
              style="width: 180px"
              placeholder="Skill 模板（可选）"
              allow-clear
              :options="skillTemplateOptions"
            />
            <label v-if="selectedSkillKey" style="display: flex; align-items: center; gap: 4px; font-size: 12px">
              <Switch v-model:checked="enableSearch" size="small" />
              联网搜索
            </label>
            <Tag v-if="modelConfig.thinking_enabled" color="purple">思考模式</Tag>
            <span style="flex: 1"></span>
            <Button size="small" @click="openModelModal">模型设置</Button>
            <Button size="small" @click="openSaveCombinedReportModal">整理为报告</Button>
            <Button size="small" danger @click="removeProject(selectedProject)">删除项目</Button>
          </div>

          <div
            ref="threadRef"
            class="ai-thread"
            style="max-height: 55vh; overflow-y: auto; padding-right: 4px"
            @click="onThreadClick"
          >
            <Empty
              v-if="!analysesLoading && !streamingEntry && !analyses.length"
              description="还没有分析记录，在下面输入想分析的问题试试，支持多轮追问"
              style="margin-top: 32px"
            />

            <template v-for="a in orderedAnalyses" :key="a.id">
              <div class="chat-row chat-row--user">
                <Avatar style="background-color: hsl(var(--primary)); flex-shrink: 0">我</Avatar>
                <div class="chat-bubble chat-bubble--user">{{ a.question }}</div>
              </div>
              <div class="chat-row chat-row--assistant">
                <Avatar style="background-color: #8c8c8c; flex-shrink: 0">AI</Avatar>
                <div class="chat-bubble chat-bubble--assistant">
                  <Alert v-if="a.status === 'failed'" type="error" :message="a.error || '分析失败'" />
                  <!-- eslint-disable-next-line vue/no-v-html -- markdown-it 默认 html:false，源文本里的裸 HTML 标签会被转义，替换出来的徽标 span 也只包含正则捕获的纯数字，不会被当成标签执行 -->
                  <div v-else class="markdown-body" v-html="renderAnalysisHtml(a.result || '')"></div>
                  <div class="chat-meta">
                    <Tag v-if="a.status === 'failed'" :color="statusColor(a.status)">
                      {{ statusLabel(a.status) }}
                    </Tag>
                    <span>{{ formatDateTime(a.created_at) }}</span>
                    <template v-if="a.status === 'success'">
                      <a @click="copyResult(a.result || '')">复制</a>
                      <a @click="regenerate(a)">重新生成</a>
                      <a @click="openSaveReportModal(a)">保存为报告</a>
                      <a :class="{ 'feedback-active': a.feedback === 'up' }" @click="setFeedback(a, 'up')">👍</a>
                      <a :class="{ 'feedback-active': a.feedback === 'down' }" @click="setFeedback(a, 'down')">👎</a>
                    </template>
                    <a @click="removeAnalysis(a)">删除</a>
                  </div>
                </div>
              </div>
            </template>

            <template v-if="streamingEntry">
              <div class="chat-row chat-row--user">
                <Avatar style="background-color: hsl(var(--primary)); flex-shrink: 0">我</Avatar>
                <div class="chat-bubble chat-bubble--user">{{ streamingEntry.question }}</div>
              </div>
              <div class="chat-row chat-row--assistant">
                <Avatar style="background-color: #8c8c8c; flex-shrink: 0">AI</Avatar>
                <div class="chat-bubble chat-bubble--assistant">
                  <!-- eslint-disable-next-line vue/no-v-html -- 同上，markdown-it 默认转义裸 HTML -->
                  <div v-if="streamingEntry.text" class="markdown-body" v-html="renderAnalysisHtml(streamingEntry.text)"></div>
                  <Typography.Text v-else type="secondary">思考中…（笔记多、开了思考模式或联网搜索时可能要等几分钟）</Typography.Text>
                  <div class="chat-meta">
                    <a @click="cancelAnalysis">取消 / 删除这轮</a>
                  </div>
                </div>
              </div>
            </template>
          </div>

          <div v-if="quickPrompts.length" style="display: flex; gap: 8px; flex-wrap: wrap; margin: 8px 0">
            <Button
              v-for="p in quickPrompts"
              :key="p"
              size="small"
              :disabled="analyzing"
              @click="useQuickPrompt(p)"
            >
              {{ p }}
            </Button>
          </div>
          <div style="display: flex; gap: 8px">
            <TextArea
              v-model:value="questionInput"
              :auto-size="{ minRows: 1, maxRows: 4 }"
              placeholder="想对这些笔记分析什么？可以继续追问"
              :disabled="analyzing"
              @keydown.enter="handleEnter"
            />
            <Button v-if="analyzing" danger @click="cancelAnalysis">取消</Button>
            <Button v-else type="primary" @click="startAnalysis">开始分析</Button>
          </div>
        </Card>
      </Col>

      <!-- 右栏：来源笔记 -->
      <Col :span="6">
        <Card size="small">
          <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px">
            <strong>来源笔记 ({{ notes.length }})</strong>
            <span style="flex: 1"></span>
            <Button size="small" @click="openAddNotesModal">+ 添加</Button>
          </div>
          <Input v-model:value="noteSearch" placeholder="搜索笔记标题/内容" allow-clear style="margin-bottom: 8px" />
          <div style="display: flex; gap: 8px; margin-bottom: 8px">
            <Tag
              :color="notesTab === 'all' ? 'blue' : 'default'"
              style="cursor: pointer"
              @click="notesTab = 'all'"
            >
              全部笔记
            </Tag>
            <Tag
              :color="notesTab === 'selected' ? 'blue' : 'default'"
              style="cursor: pointer"
              @click="notesTab = 'selected'"
            >
              我选择的 {{ selectedNoteIds.size }}
            </Tag>
          </div>

          <Empty v-if="!notesLoading && !notesForTab.length" description="没有笔记" />
          <div style="max-height: 52vh; overflow-y: auto">
            <div v-for="group in groupedNotesForTab" :key="group.label" style="margin-bottom: 12px">
              <Typography.Text type="secondary" style="font-size: 12px; display: block; margin-bottom: 6px">
                {{ group.label }}
              </Typography.Text>
              <Row :gutter="[8, 8]">
                <Col v-for="note in group.notes" :key="note.note_id" :span="12">
                  <Card size="small" hoverable @click="openDetail(note)">
                    <template #cover>
                      <div style="position: relative; width: 100%; height: 90px; overflow: hidden; background: #f0f0f0">
                        <Image
                          :src="coverProxied(note)"
                          :preview="false"
                          width="100%"
                          height="90px"
                          style="object-fit: cover; display: block"
                          fallback="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxIiBoZWlnaHQ9IjEiLz4="
                        />
                        <span class="note-index-badge">{{ noteIndexOf(note.note_id) }}</span>
                        <Checkbox
                          :checked="selectedNoteIds.has(note.note_id)"
                          style="position: absolute; top: 4px; right: 4px"
                          @click.stop
                          @change="toggleSelectedNote(note.note_id)"
                        />
                      </div>
                    </template>
                    <div style="font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                      {{ note.title || '无标题' }}
                    </div>
                  </Card>
                </Col>
              </Row>
            </div>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px">
            <Typography.Text type="secondary" style="font-size: 12px">
              已选择 {{ selectedNoteIds.size }} 篇笔记
            </Typography.Text>
            <a style="font-size: 12px" @click="clearSelection">清空选择</a>
          </div>
        </Card>
      </Col>
    </Row>

    <!-- 切换项目：选定项目后不常驻，按需从这里弹出，把宽度让给对话区 -->
    <Drawer v-model:open="projectDrawerOpen" title="切换项目" placement="left" width="360">
      <template #extra>
        <Button size="small" type="primary" @click="openCreateModal">新建</Button>
      </template>
      <Input v-model:value="projectSearch" placeholder="搜索项目" allow-clear style="margin-bottom: 8px" />
      <Empty v-if="!projectsLoading && !filteredProjects.length" description="暂无分析项目" />
      <Card
        v-for="project in filteredProjects"
        :key="project.id"
        size="small"
        hoverable
        :class="{ 'project-card--active': selectedProject?.id === project.id }"
        style="margin-bottom: 8px; cursor: pointer"
        @click="openProject(project)"
      >
        <div style="font-weight: 500">{{ project.name }}</div>
        <div style="margin-top: 4px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
          <Tag color="blue">{{ project.note_count }} 篇</Tag>
          <Typography.Text type="secondary" style="font-size: 12px">
            {{ formatDateTime(project.created_at) }}
          </Typography.Text>
        </div>
      </Card>
    </Drawer>

    <!-- 新建项目 -->
    <Modal v-model:open="createModalOpen" title="新建分析项目" :footer="null" width="420px">
      <Input
        v-model:value="newProjectName"
        placeholder="比如：普吉岛分析"
        @keydown.enter="submitCreateProject"
      />
      <Button type="primary" block :loading="creating" style="margin-top: 12px" @click="submitCreateProject">
        创建
      </Button>
    </Modal>

    <!-- 重命名项目 -->
    <Modal v-model:open="renameModalOpen" title="重命名项目" :footer="null" width="420px">
      <Input v-model:value="renameValue" @keydown.enter="submitRename" />
      <Button type="primary" block :loading="renaming" style="margin-top: 12px" @click="submitRename">
        保存
      </Button>
    </Modal>

    <!-- 模型设置：和系统设置 API 配置页的"AI 模型"卡共用同一份配置，厂商由后端注册表下发 -->
    <Modal v-model:open="modelModalOpen" title="模型设置" :footer="null" width="480px">
      <Form layout="vertical">
        <FormItem label="模型厂商">
          <Radio.Group
            :value="modelForm.provider"
            button-style="solid"
            @change="(e) => changeModelProvider(e.target.value as string)"
          >
            <Radio.Button v-for="p in modelConfig.providers" :key="p.key" :value="p.key">
              {{ p.label }}
            </Radio.Button>
          </Radio.Group>
          <div style="margin-top: 6px; font-size: 12px; color: rgba(128, 128, 128, 0.9)">
            {{ currentProviderMeta?.description }}
          </div>
        </FormItem>
        <FormItem
          :label="`${modelProviderLabel} API Key`"
          :extra="modelConfig.configured ? '留空表示不修改已保存的 Key' : undefined"
        >
          <Input.Password
            v-model:value="modelForm.api_key"
            :placeholder="`从 ${modelProviderLabel} 官方平台获取 API Key`"
          />
        </FormItem>
        <FormItem label="模型">
          <Input v-model:value="modelForm.model" :placeholder="currentProviderMeta?.default_model" />
          <div style="margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap">
            <Tag
              v-for="preset in modelPresets"
              :key="preset.value"
              style="cursor: pointer"
              :color="modelForm.model === preset.value ? 'blue' : 'default'"
              @click="modelForm.model = preset.value"
            >
              {{ preset.label }}
            </Tag>
          </div>
        </FormItem>
        <FormItem v-if="currentProviderMeta?.supports_thinking">
          <Switch v-model:checked="modelForm.thinking_enabled" />
          <span style="margin-left: 8px">启用思考模式（Thinking，回答前多推理一步，更慢但更准）</span>
        </FormItem>
        <div v-else style="margin-bottom: 16px; font-size: 12px; color: rgba(128, 128, 128, 0.9)">
          该厂商无独立思考开关，推理模型（如 deepseek-reasoner）自带思维链。
        </div>
        <Button type="primary" block :loading="modelSaving" @click="submitModelConfig">保存</Button>
      </Form>
    </Modal>

    <!-- 单篇笔记详情 -->
    <Modal
      v-model:open="detailModalOpen"
      :title="detailNote?.title || '无标题'"
      :footer="null"
      width="720px"
    >
      <template v-if="detailNote">
        <Carousel v-if="detailNote.image_list.length" arrows>
          <div v-for="(_img, idx) in detailNote.image_list" :key="idx">
            <img :src="galleryProxied(detailNote, idx)" style="width: 100%; max-height: 420px; object-fit: contain" />
          </div>
        </Carousel>
        <video
          v-else-if="detailNote.video_addr"
          :src="videoProxied(detailNote)"
          controls
          style="width: 100%; max-height: 420px; background: #000"
        ></video>

        <p style="margin-top: 12px; white-space: pre-wrap">{{ detailNote.desc }}</p>
        <div style="margin-bottom: 8px">
          <Tag v-for="tag in detailNote.tags" :key="tag">#{{ tag }}</Tag>
        </div>
        <Typography.Text type="secondary" style="display: block; font-size: 12px; margin-bottom: 12px">
          {{ detailNote.nickname }} · {{ detailNote.upload_time }} · {{ detailNote.ip_location }}
        </Typography.Text>
        <div style="display: flex; gap: 8px">
          <Button v-if="detailNote.note_url" type="primary" ghost @click="openInXhs(detailNote.note_url)">
            在小红书查看原文
          </Button>
          <Button danger @click="removeNoteFromProject(detailNote)">移出项目</Button>
        </div>
      </template>
    </Modal>

    <!-- 添加笔记 -->
    <Modal
      v-model:open="addNotesModalOpen"
      title="从采集任务里挑笔记加入项目"
      width="800px"
      :confirm-loading="adding"
      :ok-button-props="{ disabled: pickNoteIds.size === 0 }"
      ok-text="添加到项目"
      @ok="submitAddNotes"
    >
      <Select
        style="width: 100%; margin-bottom: 12px"
        placeholder="选择一个采集任务"
        :loading="sourceTasksLoading"
        :value="sourceTaskId"
        :options="sourceTasks.map((t) => ({ value: t.id, label: `${t.keyword}（${t.note_count} 篇）` }))"
        @change="(v) => onSourceTaskChange(v as number)"
      />

      <div v-if="sourceTaskId" style="display: flex; align-items: center; gap: 12px; margin-bottom: 8px">
        <Checkbox :checked="allSourcePicked" @change="toggleSelectAllSource">全选</Checkbox>
        <span v-if="pickNoteIds.size" style="color: rgba(0, 0, 0, 0.45); font-size: 13px">
          已选 {{ pickNoteIds.size }} 篇
        </span>
      </div>

      <Empty v-if="sourceTaskId && !sourceNotesLoading && !sourceNotes.length" description="该任务暂无笔记" />
      <Row :gutter="[12, 12]" style="max-height: 50vh; overflow-y: auto">
        <Col v-for="note in sourceNotes" :key="note.note_id" :span="8">
          <Card size="small" hoverable @click="togglePickNote(note.note_id)">
            <template #cover>
              <div style="position: relative; width: 100%; height: 120px; overflow: hidden; background: #f0f0f0">
                <Image
                  :src="coverProxied(note)"
                  :preview="false"
                  width="100%"
                  height="120px"
                  style="object-fit: cover; display: block"
                  fallback="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxIiBoZWlnaHQ9IjEiLz4="
                />
                <Checkbox
                  :checked="pickNoteIds.has(note.note_id)"
                  style="position: absolute; top: 6px; left: 6px"
                  @click.stop
                  @change="togglePickNote(note.note_id)"
                />
              </div>
            </template>
            <Card.Meta :title="note.title || '无标题'" :description="note.nickname" />
          </Card>
        </Col>
      </Row>
    </Modal>

    <!-- 保存为报告 -->
    <Modal
      v-model:open="saveReportModalOpen"
      title="保存为报告"
      width="480px"
      :confirm-loading="savingReport"
      ok-text="保存"
      @ok="confirmSaveReport"
    >
      <div style="margin-bottom: 4px">报告标题</div>
      <Input v-model:value="saveReportTitle" placeholder="给这份报告起个名字" />
      <p style="margin-top: 12px; font-size: 12px; color: rgba(0, 0, 0, 0.45)">
        保存后可以在「分析报告」页面统一查看和管理，正文和证据笔记会被完整保存下来，不受之后项目笔记增删的影响。
      </p>
    </Modal>

    <!-- 整理为报告：选哪几轮、存成新报告还是追加到已有报告 -->
    <Modal
      v-model:open="saveCombinedReportModalOpen"
      title="整理为报告"
      width="560px"
      :confirm-loading="savingCombinedReport"
      ok-text="生成并保存"
      @ok="confirmSaveCombinedReport"
    >
      <div style="margin-bottom: 6px; font-size: 13px; font-weight: 500">选择要包含的轮次</div>
      <Empty v-if="!successfulAnalyses.length" description="还没有分析完成的记录" />
      <div v-else style="max-height: 240px; overflow-y: auto; border: 1px solid #303030; border-radius: 6px; padding: 8px">
        <div
          v-for="a in successfulAnalyses"
          :key="a.id"
          style="display: flex; align-items: flex-start; gap: 8px; padding: 4px 0; cursor: pointer"
          @click="toggleReportAnalysis(a.id)"
        >
          <Checkbox :checked="selectedAnalysisIdsForReport.has(a.id)" @click.stop="toggleReportAnalysis(a.id)" />
          <div style="min-width: 0; flex: 1">
            <div style="font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
              {{ a.question }}
            </div>
            <Typography.Text type="secondary" style="font-size: 11px">
              {{ formatDateTime(a.created_at) }}
            </Typography.Text>
          </div>
        </div>
      </div>

      <div style="margin-top: 16px; margin-bottom: 6px; font-size: 13px; font-weight: 500">保存方式</div>
      <RadioGroup v-model:value="saveCombinedReportMode">
        <Radio value="new">保存为新报告</Radio>
        <Radio value="append" :disabled="!existingReports.length">
          追加到已有报告{{ existingReportsLoading ? '（加载中…）' : !existingReports.length ? '（该项目还没有报告）' : '' }}
        </Radio>
      </RadioGroup>

      <div v-if="saveCombinedReportMode === 'new'" style="margin-top: 12px">
        <div style="margin-bottom: 4px">报告标题</div>
        <Input v-model:value="saveCombinedReportTitle" placeholder="给这份报告起个名字" />
      </div>
      <div v-else style="margin-top: 12px">
        <div style="margin-bottom: 4px">追加到</div>
        <Select
          v-model:value="appendTargetReportId"
          placeholder="选择一份已有报告"
          style="width: 100%"
          :options="existingReports.map((r) => ({ label: r.title, value: r.id }))"
        />
      </div>

      <p style="margin-top: 12px; font-size: 12px; color: rgba(0, 0, 0, 0.45)">
        保存后可以在「分析报告」页面查看和管理，不再只是本地下载。
      </p>
    </Modal>
  </Page>
</template>

<style scoped>
.project-card--active {
  border-color: #1677ff;
}

.note-index-badge {
  position: absolute;
  top: 4px;
  left: 4px;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  border-radius: 9px;
  background: rgb(0 0 0 / 55%);
  color: #fff;
  font-size: 11px;
  line-height: 18px;
  text-align: center;
}

.chat-row {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.chat-row--user {
  flex-direction: row-reverse;
}
.chat-bubble {
  max-width: 88%;
  padding: 8px 12px;
  border-radius: 8px;
  word-break: break-word;
}
.chat-bubble--user {
  background-color: #1677ff;
  color: #fff;
  white-space: pre-wrap;
}
.chat-bubble--assistant {
  background-color: #f5f5f5;
  color: rgb(0 0 0 / 88%);
}
.chat-meta {
  margin-top: 6px;
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 12px;
  color: rgb(0 0 0 / 45%);
}
.chat-meta a {
  color: rgb(0 0 0 / 45%);
  text-decoration: underline;
  cursor: pointer;
}
.chat-meta a:hover {
  color: #ff4d4f;
}
.chat-meta a.feedback-active {
  color: #1677ff;
  font-weight: 600;
}

.markdown-body {
  font-size: 14px;
  line-height: 1.6;
}
.markdown-body :deep(p) {
  margin: 0 0 8px;
}
.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 12px 0 8px;
  font-weight: 600;
  line-height: 1.4;
}
.markdown-body :deep(h1) {
  font-size: 18px;
}
.markdown-body :deep(h2) {
  font-size: 16px;
}
.markdown-body :deep(h3) {
  font-size: 15px;
}
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0 0 8px;
  padding-left: 20px;
}
.markdown-body :deep(li) {
  margin-bottom: 4px;
}
.markdown-body :deep(strong) {
  font-weight: 600;
}
.markdown-body :deep(code) {
  background: rgb(0 0 0 / 6%);
  padding: 1px 4px;
  border-radius: 4px;
  font-size: 13px;
}
.markdown-body :deep(pre) {
  background: rgb(0 0 0 / 6%);
  padding: 8px;
  border-radius: 6px;
  overflow-x: auto;
}
.markdown-body :deep(pre code) {
  background: none;
  padding: 0;
}
.markdown-body :deep(blockquote) {
  margin: 8px 0;
  padding-left: 10px;
  border-left: 3px solid rgb(0 0 0 / 15%);
  color: rgb(0 0 0 / 65%);
}
.markdown-body :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid rgb(0 0 0 / 15%);
  padding: 4px 8px;
}
.markdown-body :deep(a) {
  color: #1677ff;
}
.markdown-body :deep(.cite-badge) {
  display: inline-block;
  min-width: 16px;
  height: 16px;
  margin-right: 2px;
  padding: 0 4px;
  border-radius: 8px;
  background: #1677ff;
  color: #fff;
  font-size: 11px;
  line-height: 16px;
  text-align: center;
  cursor: pointer;
}
</style>
