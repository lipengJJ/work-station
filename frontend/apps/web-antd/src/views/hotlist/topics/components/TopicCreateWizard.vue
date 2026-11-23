<script lang="ts" setup>
import type { HotlistApi } from '#/api/core/hotlist';
import type { NotifyApi } from '#/api/core/notify';
import type { TopicsApi } from '#/api/core/topics';

import { computed, reactive, ref, watch } from 'vue';

import { Drawer, Form, FormItem, Input, message, Modal, Radio, Select, Space, Switch, TimePicker } from 'ant-design-vue';
import dayjs from 'dayjs';

import { listHotlistSourcesApi, listSourceGroupsApi } from '#/api/core/hotlist';
import { getNotifyChannelsApi, listNotifyConfigsApi } from '#/api/core/notify';
import { listSkillsApi } from '#/api/core/skills';
import {
  batchSetTopicSourcesApi,
  createTopicApi,
  deleteTopicApi,
  updateTopicApi,
} from '#/api/core/topics';

// 创建 = 选择器（只问"要不要"），管理 = 管理台（才谈"怎么样"）。
// 向导里刻意不出现任何运行态数据（健康状态/近 7 天贡献/cron 字面量），
// 只在最后一步把「周期 + 时刻」拼成 cron，细节调参留给详情页各 Tab。
// 详见 doc/TOPIC_SOURCES_TAB_COMPACT_VIEW.md §3。

const open = defineModel<boolean>('open', { default: false });

const props = defineProps<{
  /** 续配草稿时传入；不传 = 全新创建 */
  resumeTopic?: null | TopicsApi.Topic;
}>();

const emit = defineEmits<{ done: [] }>();

const STRATEGY_OPTIONS = [
  { value: 'funnel', label: 'funnel · 三级漏斗（默认，条目多兼顾全貌与深度）' },
  { value: 'two_stage', label: 'two_stage · 分组小结（中等量、省事）' },
  { value: 'simple', label: 'simple · 直读（条目少的窄主题）' },
];
const THRESHOLD_PRESETS = [
  { label: '严格', value: 0.5 },
  { label: '均衡（推荐）', value: 0.35 },
  { label: '宽松', value: 0.2 },
];
const WEEKDAY_OPTIONS = [
  { value: 1, label: '周一' },
  { value: 2, label: '周二' },
  { value: 3, label: '周三' },
  { value: 4, label: '周四' },
  { value: 5, label: '周五' },
  { value: 6, label: '周六' },
  { value: 0, label: '周日' },
];

// -------------------------------------------------------------- 状态机 ----
const step = ref<1 | 2 | 3>(1);
const topicId = ref<null | number>(null);
const submitting = ref(false);

// 第①步
const step1 = reactive({ name: '', description: '', groupIds: [] as number[] });
const groups = ref<HotlistApi.SourceGroup[]>([]);
const selectedSourceCount = computed(() =>
  groups.value.filter((g) => step1.groupIds.includes(g.id)).reduce((sum, g) => sum + g.source_count, 0),
);
const canNextStep1 = computed(() => step1.name.trim().length > 0 && step1.groupIds.length > 0);

// 第②步
const step2 = reactive({
  interest_query: '',
  skill_key: '',
  similarity_threshold: 0.35,
  digest_strategy: 'funnel' as TopicsApi.DigestStrategy,
});
const skills = ref<{ display_name: string; skill_key: string }[]>([]);
const canNextStep2 = computed(() => step2.interest_query.trim().length > 0);

// 第③步
const step3 = reactive({
  digest_period: 'weekly' as TopicsApi.DigestPeriod,
  weekday: 1,
  time: '08:00',
  report_notify_enabled: false,
  report_notify_channel_ids: [] as number[],
});
const notifyChannels = ref<NotifyApi.ChannelInfo[]>([]);
const notifyConfigs = ref<NotifyApi.NotificationConfig[]>([]);
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
const digestCron = computed(() =>
  step3.digest_period === 'weekly'
    ? `${step3.time.split(':')[1]} ${step3.time.split(':')[0]} * * ${step3.weekday}`
    : `${step3.time.split(':')[1]} ${step3.time.split(':')[0]} * * *`,
);
const digestCronLabel = computed(() => {
  const weekdayLabel = WEEKDAY_OPTIONS.find((w) => w.value === step3.weekday)?.label || '';
  return step3.digest_period === 'weekly'
    ? `每${weekdayLabel} ${step3.time} 生成本期报告`
    : `每天 ${step3.time} 生成本期报告`;
});
const canFinish = computed(
  () => !step3.report_notify_enabled || step3.report_notify_channel_ids.length > 0,
);

function resetForm() {
  step.value = 1;
  topicId.value = null;
  step1.name = '';
  step1.description = '';
  step1.groupIds = [];
  step2.interest_query = '';
  step2.skill_key = '';
  step2.similarity_threshold = 0.35;
  step2.digest_strategy = 'funnel';
  step3.digest_period = 'weekly';
  step3.weekday = 1;
  step3.time = '08:00';
  step3.report_notify_enabled = false;
  step3.report_notify_channel_ids = [];
}

/** 续配草稿：回填已保存的字段，跳到第一个未完成的步骤（数据源已关联就跳过①）。 */
function resumeFrom(t: TopicsApi.Topic) {
  topicId.value = t.id;
  step1.name = t.name;
  step1.description = t.description;
  step1.groupIds = [];
  step2.interest_query = t.interest_query;
  step2.skill_key = t.skill_key;
  step2.similarity_threshold = t.similarity_threshold ?? 0.35;
  step2.digest_strategy = t.digest_strategy;
  step3.report_notify_enabled = t.report_notify_enabled;
  step3.report_notify_channel_ids = t.report_notify_channel_ids;
  const [minute, hour, , , weekday] = (t.digest_cron || '0 8 * * 1').split(' ');
  step3.digest_period = t.digest_period;
  step3.weekday = Number(weekday) || 1;
  step3.time = `${(hour || '8').padStart(2, '0')}:${(minute || '0').padStart(2, '0')}`;
  if (t.enabled_source_count === 0) step.value = 1;
  else if (!t.interest_query.trim()) step.value = 2;
  else step.value = 3;
}

watch(open, async (v) => {
  if (!v) return;
  resetForm();
  await Promise.all([loadGroups(), loadSkills(), loadNotify()]);
  if (props.resumeTopic) resumeFrom(props.resumeTopic);
});

async function loadGroups() {
  try {
    groups.value = await listSourceGroupsApi();
  } catch {
    groups.value = [];
  }
}
async function loadSkills() {
  try {
    const list = await listSkillsApi();
    skills.value = list.map((s) => ({ skill_key: s.skill_key, display_name: s.display_name }));
  } catch {
    skills.value = [];
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

// -------------------------------------------------------------- 步骤提交 ----
async function submitStep1() {
  if (!canNextStep1.value) return;
  submitting.value = true;
  try {
    if (topicId.value === null) {
      const created = await createTopicApi({
        name: step1.name.trim(),
        description: step1.description,
        enabled: false,
        setup_done: false,
      });
      topicId.value = created.id;
    } else {
      await updateTopicApi(topicId.value, {
        name: step1.name.trim(),
        description: step1.description,
      });
    }
    const ids = [
      ...new Set(
        (
          await Promise.all(step1.groupIds.map((gid) => listHotlistSourcesApi(gid)))
        ).flat().map((s) => s.id),
      ),
    ];
    await batchSetTopicSourcesApi(topicId.value, { mode: 'set', source_ids: ids });
    step.value = 2;
  } catch (e: any) {
    message.error(`保存失败：${e.response?.data?.detail || e.message}`);
  } finally {
    submitting.value = false;
  }
}

async function submitStep2() {
  if (!canNextStep2.value || topicId.value === null) return;
  submitting.value = true;
  try {
    await updateTopicApi(topicId.value, {
      interest_query: step2.interest_query.trim(),
      skill_key: step2.skill_key,
      similarity_threshold: step2.similarity_threshold,
      digest_strategy: step2.digest_strategy,
    });
    step.value = 3;
  } catch (e: any) {
    message.error(`保存失败：${e.response?.data?.detail || e.message}`);
  } finally {
    submitting.value = false;
  }
}

async function finish() {
  if (!canFinish.value || topicId.value === null) return;
  submitting.value = true;
  try {
    await updateTopicApi(topicId.value, {
      digest_period: step3.digest_period,
      digest_cron: digestCron.value,
      report_notify_enabled: step3.report_notify_enabled,
      report_notify_channel_ids: step3.report_notify_channel_ids,
      enabled: true,
      setup_done: true,
    });
    message.success('主题已创建，开始按周期产出报告');
    open.value = false;
    emit('done');
  } catch (e: any) {
    message.error(`保存失败：${e.response?.data?.detail || e.message}`);
  } finally {
    submitting.value = false;
  }
}

function prevStep() {
  if (step.value > 1) step.value = (step.value - 1) as 1 | 2;
}

// -------------------------------------------------------------- 退出确认 ----
function requestClose() {
  // 已经落库但没走完（setup_done 还没置 true）才需要问；全新打开、第①步还没提交过
  // 直接关，没有产生任何脏数据
  if (topicId.value === null) {
    open.value = false;
    return;
  }
  Modal.confirm({
    title: '退出创建向导？',
    content: '当前主题还没配置完成。保留草稿可以稍后在列表里点「继续配置」接着填；丢弃会连同已关联的源一起删除。',
    okText: '丢弃并删除',
    okType: 'danger',
    cancelText: '保留草稿',
    async onOk() {
      try {
        await deleteTopicApi(topicId.value!);
        message.success('已丢弃草稿');
      } catch (e: any) {
        message.error(`删除失败：${e.message}`);
      } finally {
        open.value = false;
        emit('done');
      }
    },
    onCancel() {
      open.value = false;
      emit('done');
    },
  });
}
</script>

<template>
  <Drawer
    :open="open"
    title="新建主题"
    width="640"
    :closable="true"
    :mask-closable="false"
    @close="requestClose"
  >
    <!-- 步骤指示：纯展示，不可点跳（向导要求顺序完成，不是 Tab） -->
    <div class="mb-6 flex items-center gap-2 text-xs">
      <template v-for="(label, idx) in ['基本设置', '主题设置', '通知设置']" :key="label">
        <div class="flex items-center gap-1.5">
          <span
            class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
            :class="
              step === idx + 1
                ? 'bg-primary text-primary-foreground'
                : step > idx + 1
                  ? 'bg-success/20 text-success'
                  : 'bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]'
            "
          >
            {{ idx + 1 }}
          </span>
          <span :class="step === idx + 1 ? 'font-semibold text-[hsl(var(--foreground))]' : 'text-[hsl(var(--muted-foreground))]'">
            {{ label }}
          </span>
        </div>
        <div v-if="idx < 2" class="h-px w-6 shrink-0 bg-[hsl(var(--border))]"></div>
      </template>
    </div>

    <!-- ① 基本设置 -->
    <Form v-if="step === 1" layout="vertical">
      <FormItem label="主题名称" required>
        <Input v-model:value="step1.name" placeholder="如：量化平台 / 大模型" :maxlength="64" />
      </FormItem>
      <FormItem label="描述">
        <Input.TextArea v-model:value="step1.description" :rows="2" placeholder="这个主题关注什么？" />
      </FormItem>
      <FormItem label="关联数据源组" required>
        <Select
          v-model:value="step1.groupIds"
          mode="multiple"
          placeholder="选择一个或多个数据源分组"
          :options="groups.map((g) => ({ value: g.id, label: `${g.name}（${g.source_count}）` }))"
        />
        <div class="mt-1.5 text-xs text-[hsl(var(--muted-foreground))]">
          <template v-if="step1.groupIds.length > 0">
            已选 {{ step1.groupIds.length }} 个分组 · 共 {{ selectedSourceCount }} 个源
          </template>
          <template v-else>至少选择一个数据源组，否则主题抓不到任何内容</template>
        </div>
      </FormItem>
      <div class="mt-6 flex justify-between">
        <button class="rounded-lg border border-[hsl(var(--border))] px-4 py-1.5 text-xs text-[hsl(var(--muted-foreground))]" @click="requestClose">
          取消
        </button>
        <button
          :disabled="!canNextStep1 || submitting"
          class="rounded-lg bg-primary px-4 py-1.5 text-xs font-bold text-white hover:bg-primary disabled:cursor-not-allowed disabled:opacity-40"
          @click="submitStep1"
        >
          下一步
        </button>
      </div>
    </Form>

    <!-- ② 主题设置 -->
    <Form v-else-if="step === 2" layout="vertical">
      <FormItem
        label="关注需求"
        required
        extra="自然语言描述你想看什么，例如：我想看 AI 工具链相关的新闻或知识。"
      >
        <Input.TextArea
          v-model:value="step2.interest_query"
          :rows="4"
          :maxlength="4000"
          placeholder="例：我想看 AI 工具链相关的新闻或者知识，关注 Agent runtime、MCP、模型网关"
        />
      </FormItem>
      <FormItem label="分析 Skill（留空 = 内置默认周报 Prompt）">
        <Select
          v-model:value="step2.skill_key"
          allow-clear
          placeholder="选择已启用的 Skill（可跳过）"
          :options="skills.map((s) => ({ value: s.skill_key, label: `${s.display_name}（${s.skill_key}）` }))"
        />
      </FormItem>
      <FormItem label="匹配范围（语义相关度阈值）">
        <Radio.Group v-model:value="step2.similarity_threshold">
          <Radio v-for="p in THRESHOLD_PRESETS" :key="p.label" :value="p.value">{{ p.label }}</Radio>
        </Radio.Group>
      </FormItem>
      <FormItem label="裁剪策略">
        <Radio.Group v-model:value="step2.digest_strategy">
          <Space direction="vertical">
            <Radio v-for="opt in STRATEGY_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</Radio>
          </Space>
        </Radio.Group>
      </FormItem>
      <div class="mt-6 flex justify-between">
        <button class="rounded-lg border border-[hsl(var(--border))] px-4 py-1.5 text-xs text-[hsl(var(--muted-foreground))]" @click="prevStep">
          上一步
        </button>
        <button
          :disabled="!canNextStep2 || submitting"
          class="rounded-lg bg-primary px-4 py-1.5 text-xs font-bold text-white hover:bg-primary disabled:cursor-not-allowed disabled:opacity-40"
          @click="submitStep2"
        >
          下一步
        </button>
      </div>
    </Form>

    <!-- ③ 通知设置 -->
    <Form v-else layout="vertical">
      <FormItem label="报告周期">
        <Radio.Group v-model:value="step3.digest_period">
          <Radio value="weekly">周报</Radio>
          <Radio value="daily">日报</Radio>
        </Radio.Group>
      </FormItem>
      <FormItem label="生成时刻">
        <div class="flex items-center gap-2">
          <Select
            v-if="step3.digest_period === 'weekly'"
            v-model:value="step3.weekday"
            class="w-28"
            :options="WEEKDAY_OPTIONS"
          />
          <TimePicker
            :value="dayjs(step3.time, 'HH:mm')"
            format="HH:mm"
            class="w-28"
            :allow-clear="false"
            @change="(t: any) => (step3.time = t ? t.format('HH:mm') : step3.time)"
          />
        </div>
        <div class="mt-1.5 text-xs text-[hsl(var(--muted-foreground))]">{{ digestCronLabel }}</div>
      </FormItem>
      <FormItem label="生成后推送摘要">
        <Switch v-model:checked="step3.report_notify_enabled" />
      </FormItem>
      <FormItem v-if="step3.report_notify_enabled" label="通知渠道" required>
        <Select
          v-model:value="step3.report_notify_channel_ids"
          mode="multiple"
          placeholder="选择已配置且启用的通知渠道"
          :options="notifyConfigOptions"
        />
      </FormItem>
      <div class="mt-6 flex items-center justify-between">
        <button class="rounded-lg border border-[hsl(var(--border))] px-4 py-1.5 text-xs text-[hsl(var(--muted-foreground))]" @click="prevStep">
          上一步
        </button>
        <div class="flex items-center gap-3">
          <button class="text-xs text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]" @click="requestClose">
            稍后再配，先存为草稿
          </button>
          <button
            :disabled="!canFinish || submitting"
            class="rounded-lg bg-primary px-4 py-1.5 text-xs font-bold text-white hover:bg-primary disabled:cursor-not-allowed disabled:opacity-40"
            @click="finish"
          >
            完成创建
          </button>
        </div>
      </div>
    </Form>
  </Drawer>
</template>
