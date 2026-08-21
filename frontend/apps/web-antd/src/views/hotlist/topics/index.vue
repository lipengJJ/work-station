<script lang="ts" setup>
import type { TopicsApi } from '#/api/core/topics';

import { onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { Drawer, Form, FormItem, Input, message, Modal, Switch } from 'ant-design-vue';
import { CalendarClock, FileText, Layers, Plus, Trash2 } from 'lucide-vue-next';

import GlobalFiltersBlock from './components/GlobalFiltersBlock.vue';
import TopicDetailPanel from './components/TopicDetailPanel.vue';

import { createTopicApi, deleteTopicApi, listTopicsApi, updateTopicApi } from '#/api/core/topics';

const STRATEGY_LABEL: Record<TopicsApi.DigestStrategy, string> = {
  simple: 'simple（少量直读）',
  two_stage: 'two_stage（分组小结）',
  funnel: 'funnel（三级漏斗）',
};

const PERIOD_LABEL: Record<TopicsApi.DigestPeriod, string> = {
  daily: '日报',
  weekly: '周报',
};

// -------------------------------------------------------------- 列表 ----
const topics = ref<TopicsApi.Topic[]>([]);
const loading = ref(false);

async function fetchTopics() {
  loading.value = true;
  try {
    topics.value = await listTopicsApi();
  } catch (e: any) {
    message.error(`加载失败：${e.message}`);
  } finally {
    loading.value = false;
  }
}

async function toggleEnabled(topic: TopicsApi.Topic, enabled: boolean) {
  try {
    await updateTopicApi(topic.id, { enabled });
    topic.enabled = enabled;
    message.success(enabled ? '已启用' : '已停用');
  } catch (e: any) {
    message.error(`操作失败：${e.message}`);
  }
}

// -------------------------------------------------------------- 新建 ----
const createOpen = ref(false);
const creating = ref(false);
const createForm = reactive({ name: '', slug: '', description: '' });

function openCreate() {
  createForm.name = '';
  createForm.slug = '';
  createForm.description = '';
  createOpen.value = true;
}

async function submitCreate() {
  if (!createForm.name.trim()) {
    message.warning('请填写主题名称');
    return;
  }
  creating.value = true;
  try {
    const topic = await createTopicApi({
      name: createForm.name.trim(),
      slug: createForm.slug.trim() || undefined,
      description: createForm.description.trim(),
    });
    createOpen.value = false;
    message.success('主题已创建，继续在下方配置数据源 / 关键词 / 推送');
    fetchTopics();
    activeTopicName.value = topic.name;
    activeTopicId.value = topic.id;
    detailOpen.value = true;
  } catch (e: any) {
    message.error(`创建失败：${e.response?.data?.detail || e.message}`);
  } finally {
    creating.value = false;
  }
}

function removeTopic(topic: TopicsApi.Topic) {
  Modal.confirm({
    title: `删除主题「${topic.name}」？`,
    content: '删除后源关联与已生成的报告仍在，仅移除主题本身。',
    okType: 'danger',
    async onOk() {
      try {
        await deleteTopicApi(topic.id);
        message.success('已删除');
        if (activeTopicId.value === topic.id) detailOpen.value = false;
        fetchTopics();
      } catch (e: any) {
        message.error(`删除失败：${e.message}`);
      }
    },
  });
}

// -------------------------------------------------------------- 详情（内嵌抽屉，不跳路由）----
const detailOpen = ref(false);
const activeTopicId = ref<null | number>(null);
const activeTopicName = ref('');

function openDetail(topicId: number) {
  const t = topics.value.find((x) => x.id === topicId);
  activeTopicName.value = t?.name || '';
  activeTopicId.value = topicId;
  detailOpen.value = true;
}

onMounted(fetchTopics);
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-[hsl(var(--background-deep))] p-6 select-none">
      <div class="mb-6 shrink-0 flex items-start justify-between gap-3">
        <div>
          <h1 class="text-xl font-extrabold text-[hsl(var(--foreground))]">热点聚合 · 主题订阅</h1>
          <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">按主题绑定源与关键词，用 Skill 定期产出 AI 日报 / 周报</p>
        </div>
        <button
          class="flex shrink-0 items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500"
          @click="openCreate"
        >
          <Plus class="h-3.5 w-3.5" />
          新建主题
        </button>
      </div>

      <!-- 全局过滤词（对所有主题生效） -->
      <GlobalFiltersBlock />

      <div v-if="!loading && topics.length === 0" class="rounded-2xl border border-dashed border-[hsl(var(--border))] p-12 text-center">
        <p class="text-sm font-semibold text-[hsl(var(--foreground))]">还没有主题</p>
        <p class="mt-1 text-xs text-[hsl(var(--muted-foreground))]">创建一个主题，绑定源与 Skill，AI 会按周期产出报告</p>
        <button
          class="mt-4 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500"
          @click="openCreate"
        >
          新建主题
        </button>
      </div>

      <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <div
          v-for="topic in topics"
          :key="topic.id"
          class="cursor-pointer rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 shadow-xl transition-colors hover:border-indigo-500/50"
          @click="openDetail(topic.id)"
        >
          <div class="mb-2 flex items-center gap-2">
            <Layers class="size-4 shrink-0 text-indigo-400" />
            <span class="truncate text-sm font-bold text-[hsl(var(--foreground))]">{{ topic.name }}</span>
            <span class="inline-flex items-center gap-1 text-xs" :class="topic.enabled ? 'text-emerald-400' : 'text-[hsl(var(--muted-foreground))]'">
              <span class="h-1.5 w-1.5 rounded-full" :class="topic.enabled ? 'bg-emerald-400' : 'bg-slate-500'"></span>
              {{ topic.enabled ? '启用中' : '已停用' }}
            </span>
            <Switch
              class="ml-auto shrink-0"
              :checked="topic.enabled"
              size="small"
              @click.stop
              @change="(v: boolean | number | string) => toggleEnabled(topic, !!v)"
            />
          </div>

          <p v-if="topic.description" class="mb-3 line-clamp-2 text-xs text-[hsl(var(--muted-foreground))]">
            {{ topic.description }}
          </p>
          <p v-else class="mb-3 text-xs text-[hsl(var(--muted-foreground))]/60">暂无描述</p>

          <div class="mb-4 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[hsl(var(--muted-foreground))]">
            <span class="inline-flex items-center gap-1">
              <CalendarClock class="size-3.5" />
              {{ PERIOD_LABEL[topic.digest_period] }} · {{ topic.digest_cron }}
            </span>
            <span class="inline-flex items-center gap-1">
              <FileText class="size-3.5" />
              {{ STRATEGY_LABEL[topic.digest_strategy] }}
            </span>
          </div>

          <div class="flex items-center justify-between border-t border-[hsl(var(--border))] pt-3 text-[11px]">
            <span class="text-[hsl(var(--muted-foreground))]">
              启用源 <b class="text-[hsl(var(--foreground))]">{{ topic.enabled_source_count }}</b> 个
              <span
                v-if="topic.enabled_source_count > 100"
                class="ml-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-500"
              >
                超护栏
              </span>
            </span>
            <button
              class="text-[hsl(var(--muted-foreground))] hover:text-rose-400"
              @click.stop="removeTopic(topic)"
            >
              <Trash2 class="size-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <Modal v-model:open="createOpen" title="新建主题" :footer="null" width="440px">
      <Form layout="vertical">
        <FormItem label="名称" required>
          <Input v-model:value="createForm.name" placeholder="如：量化平台 / 大模型" :maxlength="64" />
        </FormItem>
        <FormItem label="Slug（可选，留空自动生成）" extra="URL 安全标识，创建后不可修改">
          <Input v-model:value="createForm.slug" placeholder="如 quant-platform" :maxlength="64" />
        </FormItem>
        <FormItem label="描述">
          <Input.TextArea v-model:value="createForm.description" :rows="2" placeholder="这个主题关注什么？" />
        </FormItem>
        <p class="mb-3 text-xs text-[hsl(var(--muted-foreground))]">
          创建后在下方展开配置区，配数据源、关键词规则、Skill / 周期与推送。
        </p>
        <div class="flex justify-end gap-2">
          <button class="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs" @click="createOpen = false">取消</button>
          <button
            :disabled="creating"
            class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-indigo-500 disabled:opacity-50"
            @click="submitCreate"
          >
            创建
          </button>
        </div>
      </Form>
    </Modal>

    <Drawer
      v-model:open="detailOpen"
      :title="activeTopicName || '主题详情'"
      width="90%"
      destroy-on-close
    >
      <TopicDetailPanel v-if="activeTopicId" :key="activeTopicId" :topic-id="activeTopicId" @changed="fetchTopics" />
    </Drawer>
  </Page>
</template>
