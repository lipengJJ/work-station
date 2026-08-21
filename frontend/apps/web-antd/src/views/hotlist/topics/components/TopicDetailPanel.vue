<script lang="ts" setup>
import type { NotifyApi } from '#/api/core/notify';
import type { TopicsApi } from '#/api/core/topics';

import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import {
  Alert,
  Checkbox,
  Form,
  FormItem,
  Input,
  InputNumber,
  message,
  Modal,
  Pagination,
  Radio,
  Select,
  Space,
  Spin,
  Switch,
  Tooltip,
  Upload,
} from 'ant-design-vue';
import { FolderInput, Play, RefreshCw, Upload as UploadIcon } from 'lucide-vue-next';

import RuleTab from './RuleTab.vue';
import TopicSourcePickerModal from './TopicSourcePickerModal.vue';

import {
  batchSetTopicSourcesApi,
  disableStaleSourcesApi,
  generateReportApi,
  listTopicReportsApi,
  listTopicSourcesApi,
  listTopicsApi,
  updateTopicApi,
} from '#/api/core/topics';
import { getNotifyChannelsApi, listNotifyConfigsApi } from '#/api/core/notify';
import { listSkillsApi } from '#/api/core/skills';

const props = defineProps<{ topicId: number }>();
const emit = defineEmits<{ changed: [] }>();

const router = useRouter();

const STRATEGY_OPTIONS = [
  { value: 'funnel', label: 'funnel · 三级漏斗（默认，条目多兼顾全貌与深度）' },
  { value: 'two_stage', label: 'two_stage · 分组小结（中等量、省事）' },
  { value: 'simple', label: 'simple · 直读（条目少的窄主题）' },
];
const PERIOD_OPTIONS = [
  { value: 'weekly', label: '周报（默认每周一 8 点）' },
  { value: 'daily', label: '日报' },
];

function formatDateTime(iso: null | string) {
  if (!iso) return '—';
  return iso.slice(0, 16).replace('T', ' ');
}

function statusInfo(status: string) {
  return (
    {
      pending: { label: '排队中', dot: 'bg-slate-500', text: 'text-[hsl(var(--muted-foreground))]' },
      running: { label: '生成中', dot: 'bg-indigo-400', text: 'text-indigo-400' },
      success: { label: '成功', dot: 'bg-emerald-400', text: 'text-emerald-400' },
      failed: { label: '失败', dot: 'bg-rose-500', text: 'text-rose-400' },
    } as Record<string, { label: string; dot: string; text: string }>
  )[status] || { label: status, dot: 'bg-slate-500', text: 'text-[hsl(var(--muted-foreground))]' };
}

// -------------------------------------------------------------- 主题 ----
const topic = ref<TopicsApi.Topic | null>(null);
const loading = ref(true);

async function fetchTopic() {
  loading.value = true;
  try {
    const list = await listTopicsApi();
    topic.value = list.find((t) => t.id === props.topicId) || null;
    if (!topic.value) message.error('主题不存在');
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    loading.value = false;
  }
}

// -------------------------------------------------------------- 步骤条（workflow） ----
const activeStep = ref<'config' | 'notify' | 'reports' | 'rules' | 'sources'>('sources');
const ruleCount = ref(0);

const steps = computed(() => {
  const hitOn = topic.value?.hit_notify_enabled;
  const reportOn = topic.value?.report_notify_enabled;
  const notifyBadge =
    hitOn && reportOn ? '命中✓ 报告✓' : hitOn ? '命中✓' : reportOn ? '报告✓' : '未开启';
  return [
    {
      key: 'sources' as const,
      label: '数据源',
      badge: `${topic.value?.enabled_source_count ?? 0} 个源`,
      done: (topic.value?.enabled_source_count ?? 0) > 0,
    },
    {
      key: 'rules' as const,
      label: '关键词规则',
      badge: ruleCount.value > 0 ? `${ruleCount.value} 组` : '全量分析',
      done: ruleCount.value > 0,
    },
    {
      key: 'config' as const,
      label: '分析配置',
      badge: topic.value?.skill_key || '默认 Prompt',
      done: true,
    },
    {
      key: 'notify' as const,
      label: '推送设置',
      badge: notifyBadge,
      done: Boolean(hitOn || reportOn),
    },
    {
      key: 'reports' as const,
      label: '报告历史',
      badge: `${reportsTotal.value} 篇`,
      done: reportsTotal.value > 0,
    },
  ];
});

// -------------------------------------------------------------- 数据源 ----
const sources = ref<TopicsApi.TopicSource[]>([]);
const sourcesLoading = ref(false);
const opmlOpen = ref(false);
const opmlUrl = ref('');
const opmlFileText = ref('');
const opmlSaving = ref(false);
const staleIds = ref<string[]>([]);
const pickerOpen = ref(false);

async function fetchSources() {
  sourcesLoading.value = true;
  try {
    sources.value = await listTopicSourcesApi(props.topicId);
    staleIds.value = sources.value
      .filter((s) => s.topic_enabled && s.consecutive_failures >= 5)
      .map((s) => s.id);
  } catch (e: any) {
    message.error(`加载源列表失败：${e.message}`);
  } finally {
    sourcesLoading.value = false;
  }
}

const currentEnabledIds = computed(() => sources.value.filter((s) => s.topic_enabled).map((s) => s.id));

const sourceGroups = computed(() => {
  const groups: { key: string; label: string; items: TopicsApi.TopicSource[] }[] = [];
  const map = new Map<string, TopicsApi.TopicSource[]>();
  for (const s of sources.value) {
    const key = s.imported_from || 'manual';
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(s);
  }
  for (const [key, items] of map) {
    groups.push({
      key,
      label:
        key === 'manual'
          ? '手动添加'
          : key === 'builtin'
            ? '内置源'
            : `OPML 导入（${key.replace(/^opml:/, '')}）`,
      items,
    });
  }
  return groups;
});

async function batchToggle(mode: 'all_on' | 'all_off' | 'set', ids?: string[]) {
  try {
    const res = await batchSetTopicSourcesApi(props.topicId, {
      mode,
      source_ids: mode === 'set' ? ids : undefined,
    });
    message.success(`已更新 ${res.changed} 个源（当前启用 ${res.enabled_count} 个）`);
    if (res.enabled_count > 100) {
      message.warning('启用源数超过 100，可能拖慢抓取与数据库写入');
    }
    await fetchSources();
    await fetchTopic();
    emit('changed');
  } catch (e: any) {
    message.error(`操作失败：${e.message}`);
  }
}

function toggleOne(source: TopicsApi.TopicSource) {
  // set 模式在后端是"全量覆盖"（集合内启用、集合外关闭），不能只传这一个 id，
  // 否则会把本主题其余已启用的源全部关掉；这里基于当前启用集合做增删。
  const next = source.topic_enabled
    ? currentEnabledIds.value.filter((id) => id !== source.id)
    : [...currentEnabledIds.value, source.id];
  batchToggle('set', next);
}

function disableStale() {
  Modal.confirm({
    title: '关闭所有连续失败 ≥5 次的源？',
    async onOk() {
      try {
        const res = await disableStaleSourcesApi(props.topicId);
        message.success(`已关闭 ${res.disabled} 个失效源`);
        await fetchSources();
        await fetchTopic();
        emit('changed');
      } catch (e: any) {
        message.error(`操作失败：${e.message}`);
      }
    },
  });
}

function readOpmlFile(file: File) {
  const reader = new FileReader();
  reader.onload = () => {
    opmlFileText.value = String(reader.result || '');
  };
  reader.readAsText(file);
  return false;
}

async function submitImport() {
  if (!opmlUrl.value.trim() && !opmlFileText.value.trim()) {
    message.warning('请上传 .opml 文件或粘贴 OPML 的 URL');
    return;
  }
  opmlSaving.value = true;
  try {
    const { importOpmlApi } = await import('#/api/core/topics');
    const res = await importOpmlApi(props.topicId, {
      opml_text: opmlFileText.value || undefined,
      opml_url: opmlUrl.value || undefined,
    });
    message.success(res.detail);
    opmlOpen.value = false;
    opmlUrl.value = '';
    opmlFileText.value = '';
    await fetchSources();
    await fetchTopic();
  } catch (e: any) {
    message.error(`导入失败：${e.message}`);
  } finally {
    opmlSaving.value = false;
  }
}

async function onPickerApplied() {
  await fetchSources();
  await fetchTopic();
  emit('changed');
}

// -------------------------------------------------------------- 分析配置 ----
const skills = ref<{ skill_key: string; display_name: string }[]>([]);
const skillTemplates = ref<{ template_key: string; name: string }[]>([]);
const saving = ref(false);

const form = ref({
  name: '',
  description: '',
  skill_key: '',
  template_key: '',
  extra_question: '',
  digest_strategy: 'funnel' as TopicsApi.DigestStrategy,
  digest_period: 'weekly' as TopicsApi.DigestPeriod,
  digest_cron: '0 8 * * 1',
  max_items: 500,
  shortlist_size: 80,
  fulltext_size: 15,
  compare_with_previous: true,
  publish_enabled: false,
  publish_formats: ['json', 'html'] as string[],
  // 报告定时推送
  report_notify_enabled: false,
  report_notify_channel_ids: [] as number[],
  report_notify_time_start: '',
  report_notify_time_end: '',
  // 实时命中推送
  hit_notify_enabled: false,
  hit_notify_channel_ids: [] as number[],
  hit_notify_time_start: '',
  hit_notify_time_end: '',
  hit_notify_frequency: 'realtime' as 'realtime' | '1h' | '6h' | '12h' | 'daily',
  hit_notify_only_on_hit: true,
});

const HIT_FREQ_OPTIONS = [
  { value: 'realtime', label: '实时（抓到新命中立即推送）' },
  { value: '1h', label: '每 1 小时汇总' },
  { value: '6h', label: '每 6 小时汇总' },
  { value: '12h', label: '每 12 小时汇总' },
  { value: 'daily', label: '每天汇总（约 24 小时一次，从首条命中起算）' },
];

const notifyChannels = ref<NotifyApi.ChannelInfo[]>([]);
const notifyConfigs = ref<NotifyApi.NotificationConfig[]>([]);

function fillForm() {
  if (!topic.value) return;
  const t = topic.value;
  form.value = {
    name: t.name,
    description: t.description,
    skill_key: t.skill_key,
    template_key: t.template_key || '',
    extra_question: t.extra_question,
    digest_strategy: t.digest_strategy,
    digest_period: t.digest_period,
    digest_cron: t.digest_cron,
    max_items: t.max_items,
    shortlist_size: t.shortlist_size,
    fulltext_size: t.fulltext_size,
    compare_with_previous: t.compare_with_previous,
    publish_enabled: t.publish_enabled,
    publish_formats: t.publish_formats,
    report_notify_enabled: t.report_notify_enabled,
    report_notify_channel_ids: t.report_notify_channel_ids,
    report_notify_time_start: t.report_notify_time_start || '',
    report_notify_time_end: t.report_notify_time_end || '',
    hit_notify_enabled: t.hit_notify_enabled,
    hit_notify_channel_ids: t.hit_notify_channel_ids,
    hit_notify_time_start: t.hit_notify_time_start || '',
    hit_notify_time_end: t.hit_notify_time_end || '',
    hit_notify_frequency: t.hit_notify_frequency,
    hit_notify_only_on_hit: t.hit_notify_only_on_hit,
  };
}

async function loadSkills() {
  try {
    const list = await listSkillsApi();
    skills.value = list.map((s) => ({ skill_key: s.skill_key, display_name: s.display_name }));
  } catch {
    skills.value = [];
  }
}

async function onSkillChange(skillKey: string) {
  form.value.template_key = '';
  skillTemplates.value = [];
  if (!skillKey) return;
  try {
    const { listSkillTemplatesApi } = await import('#/api/core/skills');
    const tpls = await listSkillTemplatesApi(skillKey);
    skillTemplates.value = tpls.map((t) => ({ template_key: t.template_key, name: t.name }));
  } catch {
    skillTemplates.value = [];
  }
}

async function loadNotify() {
  try {
    const [channels, configs] = await Promise.all([getNotifyChannelsApi(), listNotifyConfigsApi()]);
    notifyChannels.value = channels.channels || [];
    notifyConfigs.value = configs;
  } catch {
    // 静默：通知配置拉不到不影响主题配置
  }
}

const notifyConfigOptions = computed(() =>
  notifyConfigs.value
    .filter((c) => {
      const meta = notifyChannels.value.find((ch) => ch.channel === c.channel);
      return c.enabled && meta?.configured;
    })
    .map((c) => ({
      value: c.id,
      label: `${c.remark || c.channel}${c.channel === 'wecom_webhook' ? '（企业微信）' : c.channel === 'serverchan' ? '（Server酱）' : c.channel === 'email' ? '（邮件）' : ''}`,
    })),
);

async function saveConfig() {
  saving.value = true;
  try {
    const f = form.value;
    const updated = await updateTopicApi(props.topicId, {
      name: f.name.trim(),
      description: f.description,
      skill_key: f.skill_key,
      template_key: f.template_key || null,
      extra_question: f.extra_question,
      digest_strategy: f.digest_strategy,
      digest_period: f.digest_period,
      digest_cron: f.digest_cron,
      max_items: f.max_items,
      shortlist_size: f.shortlist_size,
      fulltext_size: f.fulltext_size,
      compare_with_previous: f.compare_with_previous,
      publish_enabled: f.publish_enabled,
      publish_formats: f.publish_formats,
      report_notify_enabled: f.report_notify_enabled,
      report_notify_channel_ids: f.report_notify_channel_ids,
      report_notify_time_start: f.report_notify_time_start || null,
      report_notify_time_end: f.report_notify_time_end || null,
      hit_notify_enabled: f.hit_notify_enabled,
      hit_notify_channel_ids: f.hit_notify_channel_ids,
      hit_notify_time_start: f.hit_notify_time_start || null,
      hit_notify_time_end: f.hit_notify_time_end || null,
      hit_notify_frequency: f.hit_notify_frequency,
      hit_notify_only_on_hit: f.hit_notify_only_on_hit,
    });
    topic.value = updated;
    message.success('配置已保存');
    emit('changed');
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    saving.value = false;
  }
}

// -------------------------------------------------------------- 报告历史 ----
const reports = ref<TopicsApi.Report[]>([]);
const reportsTotal = ref(0);
const reportsPage = ref(1);
const reportsLoading = ref(false);
const generating = ref(false);

async function fetchReports(page = 1) {
  reportsLoading.value = true;
  reportsPage.value = page;
  try {
    const res = await listTopicReportsApi(props.topicId, { page, page_size: 20 });
    reports.value = res.reports;
    reportsTotal.value = res.total;
  } catch (e: any) {
    message.error(`加载报告失败：${e.message}`);
  } finally {
    reportsLoading.value = false;
  }
}

async function generate(strategy = '') {
  generating.value = true;
  try {
    const res = await generateReportApi(props.topicId, { strategy: strategy || undefined });
    message.success(res.message);
    setTimeout(() => fetchReports(1), 1500);
  } catch (e: any) {
    message.error(`触发失败：${e.message}`);
  } finally {
    generating.value = false;
  }
}

// 高级生成：指定 strategy（A/B 对比）与 period_key（补历史期）
const advancedOpen = ref(false);
const advancedForm = ref({ strategy: '' as string, period_key: '' });

function openAdvanced() {
  advancedForm.value = { strategy: '', period_key: '' };
  advancedOpen.value = true;
}

async function submitAdvanced() {
  advancedOpen.value = false;
  generating.value = true;
  try {
    const res = await generateReportApi(props.topicId, {
      strategy: advancedForm.value.strategy || undefined,
      period_key: advancedForm.value.period_key || undefined,
    });
    message.success(res.message);
    setTimeout(() => fetchReports(1), 1500);
  } catch (e: any) {
    message.error(`触发失败：${e.message}`);
  } finally {
    generating.value = false;
  }
}

// -------------------------------------------------------------- 生命周期 ----
onMounted(async () => {
  await fetchTopic();
  await Promise.all([fetchSources(), loadSkills(), loadNotify()]);
  if (topic.value) fillForm();
  fetchReports(1);
});
</script>

<template>
  <Spin :spinning="loading">
    <template v-if="topic">
      <!-- ============================================================ 步骤条 -->
      <div class="mb-5 flex flex-wrap gap-2">
        <button
          v-for="(step, idx) in steps"
          :key="step.key"
          class="flex items-center gap-2 rounded-lg border px-3 py-2 text-xs transition-colors"
          :class="
            activeStep === step.key
              ? 'border-indigo-500 bg-indigo-500/10 text-indigo-400'
              : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
          "
          @click="activeStep = step.key"
        >
          <span
            class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
            :class="step.done ? 'bg-emerald-500/20 text-emerald-400' : 'bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]'"
          >
            {{ idx + 1 }}
          </span>
          <span class="font-semibold">{{ step.label }}</span>
          <span class="opacity-70">{{ step.badge }}</span>
        </button>
      </div>

      <!-- ============================================================ 数据源 -->
      <div v-show="activeStep === 'sources'">
        <div class="mb-4 flex flex-wrap items-center gap-2">
          <button
            class="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500"
            @click="pickerOpen = true"
          >
            <FolderInput class="h-3.5 w-3.5" />
            从分组关联
          </button>
          <button
            class="flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-3 py-1.5 text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            @click="opmlOpen = true"
          >
            <UploadIcon class="h-3.5 w-3.5" />
            导入 OPML
          </button>
          <button
            class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            @click="batchToggle('all_on')"
          >
            全开
          </button>
          <button
            class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            @click="batchToggle('all_off')"
          >
            全关
          </button>
          <button
            class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs text-rose-400 disabled:opacity-40"
            :disabled="staleIds.length === 0"
            @click="disableStale"
          >
            一键关闭失效源（{{ staleIds.length }}）
          </button>
          <span class="ml-auto text-xs text-[hsl(var(--muted-foreground))]">
            启用
            <b :class="topic.enabled_source_count > 100 ? 'text-amber-500' : 'text-[hsl(var(--foreground))]'">
              {{ topic.enabled_source_count }}
            </b>
            个源
            <span v-if="topic.enabled_source_count > 100" class="text-amber-500">
              · 超过 100 护栏，可能拖慢抓取
            </span>
          </span>
        </div>

        <Alert
          v-if="topic.enabled_source_count === 0"
          class="mb-4"
          type="warning"
          show-icon
          message="主题下还没有启用任何源"
          description="从分组关联、导入 OPML 或在下表勾选启用；抓取任务只跑「被至少一个启用主题启用」的源。"
        />

        <Spin :spinning="sourcesLoading">
          <div v-for="group in sourceGroups" :key="group.key" class="mb-5">
            <div class="mb-2 text-xs font-medium text-[hsl(var(--muted-foreground))]">{{ group.label }}（{{ group.items.length }}）</div>
            <div class="overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] shadow-xl">
              <div class="overflow-x-auto">
                <table class="w-full text-left text-xs">
                  <thead class="border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] font-mono text-[11px] text-[hsl(var(--muted-foreground))] uppercase">
                    <tr>
                      <th class="px-4 py-3">源 / ID</th>
                      <th class="px-4 py-3">健康状态</th>
                      <th class="px-4 py-3">近 7 天贡献</th>
                      <th class="px-4 py-3">抓取频率</th>
                      <th class="px-4 py-3">本主题启用</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-[hsl(var(--border))]">
                    <tr v-for="record in group.items" :key="record.id" class="transition-colors hover:bg-[hsl(var(--accent))]">
                      <td class="px-4 py-3">
                        <div class="font-semibold text-[hsl(var(--foreground))]">{{ record.name }}</div>
                        <div class="text-[11px] text-[hsl(var(--muted-foreground))]">{{ record.id }}</div>
                      </td>
                      <td class="px-4 py-3">
                        <Tooltip :title="record.last_error || '暂无错误信息'">
                          <span v-if="!record.enabled" class="inline-flex items-center gap-1.5 text-[hsl(var(--muted-foreground))]">
                            <span class="h-1.5 w-1.5 rounded-full bg-slate-500"></span>
                            全局停用
                          </span>
                          <span
                            v-else-if="record.last_status === 'failed'"
                            class="inline-flex items-center gap-1.5"
                            :class="record.consecutive_failures >= 5 ? 'text-rose-500/60' : 'text-rose-400'"
                          >
                            <span class="h-1.5 w-1.5 rounded-full bg-rose-500"></span>
                            失败×{{ record.consecutive_failures }}{{ record.consecutive_failures >= 5 ? '（失效）' : '' }}
                          </span>
                          <span v-else-if="record.last_status === 'success'" class="inline-flex items-center gap-1.5 text-emerald-400">
                            <span class="h-1.5 w-1.5 rounded-full bg-emerald-400"></span>
                            正常
                          </span>
                          <span v-else class="inline-flex items-center gap-1.5 text-[hsl(var(--muted-foreground))]">
                            <span class="h-1.5 w-1.5 rounded-full bg-slate-500"></span>
                            待抓取
                          </span>
                        </Tooltip>
                      </td>
                      <td class="px-4 py-3 font-mono text-[hsl(var(--muted-foreground))]">{{ record.hit_count_7d }} 条</td>
                      <td class="px-4 py-3 font-mono text-[hsl(var(--muted-foreground))]">{{ record.cron_expr }}</td>
                      <td class="px-4 py-3">
                        <Switch
                          :checked="record.topic_enabled"
                          :disabled="!record.enabled"
                          size="small"
                          @change="() => toggleOne(record)"
                        />
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </Spin>
      </div>

      <!-- ============================================================ 关键词规则 -->
      <div v-show="activeStep === 'rules'">
        <RuleTab :topic-id="topicId" @count-change="(n) => (ruleCount = n)" />
      </div>

      <!-- ============================================================ 分析配置 -->
      <div v-show="activeStep === 'config'">
        <div class="max-w-3xl">
          <Form layout="vertical">
            <FormItem label="主题名称">
              <Input v-model:value="form.name" :maxlength="64" />
            </FormItem>
            <FormItem label="描述">
              <Input.TextArea v-model:value="form.description" :rows="2" />
            </FormItem>

            <div class="mb-2 mt-6 border-b border-[hsl(var(--border))] pb-1 text-sm font-medium text-[hsl(var(--foreground))]">AI 分析</div>
            <FormItem label="分析 Skill（留空 = 内置默认周报 Prompt）">
              <Select
                v-model:value="form.skill_key"
                allow-clear
                placeholder="选择已启用的 Skill（如 topic-weekly-digest）"
                :options="skills.map((s) => ({ value: s.skill_key, label: `${s.display_name}（${s.skill_key}）` }))"
                @change="(v: any) => onSkillChange(v ? String(v) : '')"
              />
            </FormItem>
            <FormItem v-if="form.skill_key" label="模板">
              <Select
                v-model:value="form.template_key"
                allow-clear
                placeholder="默认模板"
                :options="skillTemplates.map((t) => ({ value: t.template_key, label: t.name }))"
              />
            </FormItem>
            <FormItem label="额外要求（透传给 AI 的补充指令）">
              <Input.TextArea
                v-model:value="form.extra_question"
                :rows="2"
                placeholder="例：重点关注能直接集成进 FastAPI 单体应用的项目，务必注明 License"
              />
            </FormItem>

            <div class="grid grid-cols-1 gap-x-6 md:grid-cols-2">
              <FormItem label="裁剪策略">
                <Radio.Group v-model:value="form.digest_strategy" class="w-full">
                  <Space direction="vertical">
                    <Radio v-for="opt in STRATEGY_OPTIONS" :key="opt.value" :value="opt.value">
                      {{ opt.label }}
                    </Radio>
                  </Space>
                </Radio.Group>
              </FormItem>
              <div>
                <FormItem label="周期">
                  <Radio.Group v-model:value="form.digest_period">
                    <Radio v-for="opt in PERIOD_OPTIONS" :key="opt.value" :value="opt.value">
                      {{ opt.label }}
                    </Radio>
                  </Radio.Group>
                </FormItem>
                <FormItem label="生成时刻（5 段 cron）">
                  <Input v-model:value="form.digest_cron" class="font-mono" />
                </FormItem>
              </div>
            </div>

            <div class="grid grid-cols-3 gap-x-6">
              <FormItem label="候选上限 max_items">
                <InputNumber v-model:value="form.max_items" :min="1" :max="5000" class="w-full" />
              </FormItem>
              <FormItem label="入选数 shortlist_size（funnel）">
                <InputNumber v-model:value="form.shortlist_size" :min="1" :max="1000" class="w-full" />
              </FormItem>
              <FormItem label="抓全文数 fulltext_size">
                <InputNumber v-model:value="form.fulltext_size" :min="0" :max="200" class="w-full" />
              </FormItem>
            </div>
            <FormItem label="与上期对比（新出现 / 持续 / 已消退）">
              <Switch v-model:checked="form.compare_with_previous" />
            </FormItem>

            <div class="mb-2 mt-6 border-b border-[hsl(var(--border))] pb-1 text-sm font-medium text-[hsl(var(--foreground))]">发布（S3 兼容对象存储）</div>
            <FormItem label="生成后发布到对象存储">
              <Switch v-model:checked="form.publish_enabled" />
            </FormItem>
            <FormItem v-if="form.publish_enabled" label="发布格式">
              <Checkbox.Group v-model:value="form.publish_formats">
                <Checkbox value="json">JSON（结构化数据）</Checkbox>
                <Checkbox value="html">HTML（浏览器直接打开）</Checkbox>
              </Checkbox.Group>
            </FormItem>

            <div class="flex gap-2">
              <button
                :disabled="saving"
                class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
                @click="saveConfig"
              >
                保存配置
              </button>
              <button
                :disabled="generating"
                class="flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] disabled:opacity-50"
                @click="generate()"
              >
                <Play class="h-3.5 w-3.5" />
                立即生成本期报告
              </button>
            </div>
          </Form>
        </div>
      </div>

      <!-- ============================================================ 推送设置 -->
      <div v-show="activeStep === 'notify'">
        <div class="max-w-3xl">
          <Form layout="vertical">
            <!-- 实时命中推送 -->
            <div class="mb-2 mt-2 border-b border-[hsl(var(--border))] pb-1 text-sm font-medium text-[hsl(var(--foreground))]">
              实时命中推送（hit_notify_*）
            </div>
            <p class="mb-3 text-xs text-[hsl(var(--muted-foreground))]">
              抓取时命中本主题的关键词规则后，按频率推送命中条目（无规则主题开启后推「全部命中」）
            </p>
            <FormItem label="开启实时命中推送">
              <Switch v-model:checked="form.hit_notify_enabled" />
            </FormItem>
            <template v-if="form.hit_notify_enabled">
              <FormItem label="通知渠道">
                <Select
                  v-model:value="form.hit_notify_channel_ids"
                  mode="multiple"
                  placeholder="选择已配置且启用的通知渠道"
                  :options="notifyConfigOptions"
                />
              </FormItem>
              <FormItem label="推送频率">
                <Select v-model:value="form.hit_notify_frequency" class="w-full" :options="HIT_FREQ_OPTIONS" />
              </FormItem>
              <div class="grid grid-cols-2 gap-x-6">
                <FormItem label="通知时段起（HH:MM，留空不限）">
                  <Input v-model:value="form.hit_notify_time_start" placeholder="如 09:00" />
                </FormItem>
                <FormItem label="通知时段止（HH:MM）">
                  <Input v-model:value="form.hit_notify_time_end" placeholder="如 22:00" />
                </FormItem>
              </div>
              <FormItem label="仅在有新命中时推送">
                <Switch v-model:checked="form.hit_notify_only_on_hit" />
                <div class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">关闭则无命中时也会发一条空消息</div>
              </FormItem>
            </template>

            <!-- 报告定时推送 -->
            <div class="mb-2 mt-6 border-b border-[hsl(var(--border))] pb-1 text-sm font-medium text-[hsl(var(--foreground))]">
              报告定时推送（report_notify_*）
            </div>
            <p class="mb-3 text-xs text-[hsl(var(--muted-foreground))]">
              报告生成完成后推送摘要 + 链接，与实时命中推送互不影响
            </p>
            <FormItem label="生成后推送摘要">
              <Switch v-model:checked="form.report_notify_enabled" />
            </FormItem>
            <template v-if="form.report_notify_enabled">
              <FormItem label="通知渠道">
                <Select
                  v-model:value="form.report_notify_channel_ids"
                  mode="multiple"
                  placeholder="选择已配置且启用的通知渠道"
                  :options="notifyConfigOptions"
                />
              </FormItem>
              <div class="grid grid-cols-2 gap-x-6">
                <FormItem label="静默时段起（HH:MM，留空不限）">
                  <Input v-model:value="form.report_notify_time_start" placeholder="如 22:00" />
                </FormItem>
                <FormItem label="静默时段止（HH:MM）">
                  <Input v-model:value="form.report_notify_time_end" placeholder="如 08:00" />
                </FormItem>
              </div>
            </template>

            <button
              :disabled="saving"
              class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
              @click="saveConfig"
            >
              保存配置
            </button>
          </Form>
        </div>
      </div>

      <!-- ============================================================ 报告历史 -->
      <div v-show="activeStep === 'reports'">
        <div class="mb-4 flex flex-wrap items-center gap-2">
          <button
            :disabled="generating"
            class="flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
            @click="generate()"
          >
            <Play class="h-3.5 w-3.5" />
            生成本期
          </button>
          <button
            class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            @click="openAdvanced"
          >
            高级生成（策略 A/B / 补历史期）
          </button>
          <button
            class="flex items-center gap-1 rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            @click="fetchReports(reportsPage)"
          >
            <RefreshCw class="h-3.5 w-3.5" />
            刷新
          </button>
        </div>

        <div class="overflow-hidden rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--background-deep))] shadow-xl">
          <div v-if="!reportsLoading && reports.length === 0" class="p-12 text-center text-sm text-[hsl(var(--muted-foreground))]">
            还没有报告
          </div>
          <div v-else class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] font-mono text-[11px] text-[hsl(var(--muted-foreground))] uppercase">
                <tr>
                  <th class="px-4 py-3">期号</th>
                  <th class="px-4 py-3">状态</th>
                  <th class="px-4 py-3">策略</th>
                  <th class="px-4 py-3">统计</th>
                  <th class="px-4 py-3">成本</th>
                  <th class="px-4 py-3">生成时间</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-[hsl(var(--border))]">
                <tr
                  v-for="record in reports"
                  :key="record.id"
                  class="cursor-pointer transition-colors hover:bg-[hsl(var(--accent))]"
                  @click="router.push(`/hotlist/topics/${topicId}/reports/${record.id}`)"
                >
                  <td class="px-4 py-3 font-mono text-[hsl(var(--foreground))]">{{ record.period_key }}</td>
                  <td class="px-4 py-3">
                    <span class="inline-flex items-center gap-1.5" :class="statusInfo(record.status).text">
                      <span class="h-1.5 w-1.5 rounded-full" :class="statusInfo(record.status).dot"></span>
                      {{ statusInfo(record.status).label }}
                    </span>
                  </td>
                  <td class="px-4 py-3 text-[hsl(var(--muted-foreground))]">{{ record.strategy }}</td>
                  <td class="px-4 py-3 text-[hsl(var(--muted-foreground))]">
                    {{
                      record.status === 'success'
                        ? `${record.item_count} 条 / ${record.source_count} 源`
                        : record.status === 'running'
                          ? '生成中…'
                          : record.error
                            ? record.error.slice(0, 30)
                            : '—'
                    }}
                  </td>
                  <td class="px-4 py-3 font-mono text-[hsl(var(--muted-foreground))]">
                    {{
                      record.prompt_tokens || record.completion_tokens
                        ? `${record.prompt_tokens}+${record.completion_tokens} tok · ${record.ai_call_count} 次`
                        : '—'
                    }}
                  </td>
                  <td class="px-4 py-3 text-[hsl(var(--muted-foreground))]">{{ formatDateTime(record.created_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div v-if="reportsTotal > 20" class="mt-4 flex justify-end">
          <Pagination
            :current="reportsPage"
            :page-size="20"
            :total="reportsTotal"
            size="small"
            @change="fetchReports"
          />
        </div>
      </div>
    </template>
  </Spin>

  <!-- 从分组关联源 -->
  <TopicSourcePickerModal
    v-model:open="pickerOpen"
    :topic-id="topicId"
    :current-enabled-ids="currentEnabledIds"
    @applied="onPickerApplied"
  />

  <!-- OPML 导入弹窗 -->
  <Modal v-model:open="opmlOpen" title="导入 OPML 订阅源" :footer="null" width="480px">
    <Form layout="vertical" class="pt-2">
      <FormItem label="上传 .opml 文件">
        <Upload :before-upload="readOpmlFile" :show-upload-list="false" accept=".opml,.xml">
          <button class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs">选择文件</button>
        </Upload>
      </FormItem>
      <FormItem label="或粘贴 OPML 的 URL">
        <Input
          v-model:value="opmlUrl"
          placeholder="https://raw.githubusercontent.com/xxx/feeds/cn-ai-tools.opml"
        />
      </FormItem>
      <Alert
        class="mb-3"
        type="info"
        show-icon
        message="导入说明"
        description="重复的 feed 自动复用已有源（不覆盖你改过的名字和 cron）；新源默认关闭，导入后在源管理里逐个启用。RSS 源默认 4 小时抓一次。"
      />
      <div class="flex justify-end gap-2">
        <button class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs" @click="opmlOpen = false">取消</button>
        <button
          :disabled="opmlSaving"
          class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
          @click="submitImport"
        >
          导入
        </button>
      </div>
    </Form>
  </Modal>

  <!-- 高级生成弹窗 -->
  <Modal v-model:open="advancedOpen" title="高级生成" :footer="null" width="480px">
    <Form layout="vertical" class="pt-2">
      <FormItem label="裁剪策略（留空 = 主题配置）" extra="策略 A/B：同一期数据用不同策略各生成一次，并排对比效果；注意同期会覆盖上一次结果">
        <Select
          v-model:value="advancedForm.strategy"
          allow-clear
          placeholder="使用主题默认策略"
          :options="STRATEGY_OPTIONS.map((s) => ({ value: s.value, label: s.label }))"
        />
      </FormItem>
      <FormItem label="期号（留空 = 当前周期）" extra="周报如 2026-W34，日报如 2026-08-19；补历史期用">
        <Input v-model:value="advancedForm.period_key" placeholder="2026-W34" class="font-mono" />
      </FormItem>
      <div class="flex justify-end gap-2">
        <button class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs" @click="advancedOpen = false">取消</button>
        <button
          class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500"
          @click="submitAdvanced"
        >
          开始生成
        </button>
      </div>
    </Form>
  </Modal>
</template>
