<script lang="ts" setup>
import type { TopicsApi } from '#/api/core/topics';

import { computed, onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { Drawer, Form, FormItem, Input, message, Modal, Switch } from 'ant-design-vue';
import { CalendarClock, CheckCircle2, FileText, Layers, Plus, Tags, Trash2 } from 'lucide-vue-next';

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
const enabledTopicCount = computed(() => topics.value.filter((t) => t.enabled).length);

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
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-background-deep p-6 lg:p-8 select-none">
      <!-- 页头 Hero -->
      <div class="fade-up relative mb-8 shrink-0 overflow-hidden rounded-3xl border border-border bg-card p-6 shadow-sm">
        <div class="pointer-events-none absolute -right-12 -top-14 size-52 rounded-full bg-primary/12 blur-3xl"></div>
        <div class="pointer-events-none absolute -bottom-20 -left-14 size-60 rounded-full bg-warning/8 blur-3xl"></div>
        <div class="relative flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div class="flex items-center gap-4">
            <div
              class="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-primary to-primary/50 text-primary-foreground shadow-lg shadow-primary/25"
            >
              <Tags class="size-5" />
            </div>
            <div>
              <p class="text-[10px] font-bold uppercase tracking-[0.25em] text-primary">Topic Subscriptions</p>
              <h1
                class="display-font mt-1 bg-gradient-to-r from-foreground to-foreground/60 bg-clip-text text-2xl font-black tracking-tight text-transparent"
              >
                主题订阅
              </h1>
              <p class="mt-1 text-xs text-muted-foreground">按主题绑定源与关键词，用 Skill 定期产出 AI 日报 / 周报</p>
            </div>
          </div>
          <button
            class="flex shrink-0 items-center gap-1.5 self-start rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-md shadow-primary/20 transition-all hover:bg-primary/90 hover:shadow-lg hover:shadow-primary/30 lg:self-auto"
            @click="openCreate"
          >
            <Plus class="h-4 w-4" />
            新建主题
          </button>
        </div>
      </div>

      <!-- 统计卡片 -->
      <div class="fade-up mb-6 grid shrink-0 grid-cols-1 gap-4 sm:grid-cols-2" style="animation-delay: 60ms">
        <div
          class="group relative overflow-hidden rounded-2xl border border-border bg-card p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-xl"
        >
          <div class="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-primary via-primary/70 to-primary/30"></div>
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-muted-foreground">主题总数</span>
            <Tags class="size-4 text-primary/70 transition-transform duration-300 group-hover:scale-110" />
          </div>
          <div class="mt-3 text-3xl font-bold tracking-tight text-foreground">{{ topics.length }}</div>
          <div class="mt-1 text-[11px] text-muted-foreground">订阅的主题</div>
        </div>
        <div
          class="group relative overflow-hidden rounded-2xl border border-border bg-card p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-xl"
          style="animation-delay: 120ms"
        >
          <div class="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-success via-success/70 to-success/30"></div>
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium text-muted-foreground">启用中</span>
            <CheckCircle2 class="size-4 text-success/70 transition-transform duration-300 group-hover:scale-110" />
          </div>
          <div class="mt-3 text-3xl font-bold tracking-tight text-foreground">{{ enabledTopicCount }}</div>
          <div class="mt-1 text-[11px] text-muted-foreground">正在周期产出报告</div>
        </div>
      </div>

      <!-- 空状态 -->
      <div
        v-if="!loading && topics.length === 0"
        class="fade-up rounded-2xl border border-dashed border-border p-16 text-center"
        style="animation-delay: 200ms"
      >
        <div class="mx-auto mb-3 flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <Tags class="size-5" />
        </div>
        <p class="text-sm font-medium text-foreground">还没有主题</p>
        <p class="mt-1 text-xs text-muted-foreground">创建一个主题，绑定源与 Skill，AI 会按周期产出报告</p>
        <button
          class="mt-4 rounded-full bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground shadow-md shadow-primary/20 transition-all hover:bg-primary/90"
          @click="openCreate"
        >
          新建主题
        </button>
      </div>

      <!-- 主题卡片 -->
      <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <div
          v-for="(topic, idx) in topics"
          :key="topic.id"
          class="fade-up group cursor-pointer rounded-2xl border border-border bg-card p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:border-primary/40 hover:shadow-xl"
          :style="{ animationDelay: `${200 + idx * 50}ms` }"
          @click="openDetail(topic.id)"
        >
          <div class="mb-3 flex items-center gap-3">
            <div
              class="flex size-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary/15 to-primary/5 text-primary transition-transform duration-300 group-hover:scale-110"
            >
              <Layers class="size-4" />
            </div>
            <span class="truncate text-sm font-semibold text-foreground">{{ topic.name }}</span>
            <span
              class="inline-flex items-center gap-1 text-xs"
              :class="topic.enabled ? 'text-success' : 'text-muted-foreground'"
            >
              <span class="h-1.5 w-1.5 rounded-full" :class="topic.enabled ? 'bg-success' : 'bg-muted-foreground'"></span>
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

          <p v-if="topic.description" class="mb-3 line-clamp-2 text-xs text-muted-foreground">
            {{ topic.description }}
          </p>
          <p v-else class="mb-3 text-xs text-muted-foreground/60">暂无描述</p>

          <div class="mb-4 flex flex-wrap gap-2">
            <span
              class="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-1 text-[11px] text-muted-foreground"
            >
              <CalendarClock class="size-3" />
              {{ PERIOD_LABEL[topic.digest_period] }} · {{ topic.digest_cron }}
            </span>
            <span
              class="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-1 text-[11px] text-muted-foreground"
            >
              <FileText class="size-3" />
              {{ STRATEGY_LABEL[topic.digest_strategy] }}
            </span>
          </div>

          <div class="flex items-center justify-between border-t border-border pt-3 text-[11px]">
            <span class="text-muted-foreground">
              启用源 <b class="font-semibold text-foreground">{{ topic.enabled_source_count }}</b> 个
              <span
                v-if="topic.enabled_source_count > 100"
                class="ml-1 rounded-full bg-warning/15 px-2 py-0.5 font-medium text-warning"
              >
                超护栏
              </span>
            </span>
            <button
              class="text-muted-foreground transition-colors hover:text-destructive"
              @click.stop="removeTopic(topic)"
            >
              <Trash2 class="size-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建主题 -->
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
        <p class="mb-3 text-xs text-muted-foreground">
          创建后在下方展开配置区，配数据源、关键词规则、Skill / 周期与推送。
        </p>
        <div class="flex justify-end gap-2">
          <button class="rounded-full border border-border px-4 py-1.5 text-xs" @click="createOpen = false">取消</button>
          <button
            :disabled="creating"
            class="rounded-full bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
            @click="submitCreate"
          >
            创建
          </button>
        </div>
      </Form>
    </Modal>

    <!-- 主题详情抽屉 -->
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

<style scoped>
.display-font {
  font-family:
    'SF Pro Display', 'PingFang SC', 'Hiragino Sans GB', 'Noto Sans SC',
    'Microsoft YaHei', system-ui, sans-serif;
}
.fade-up {
  animation: fade-up 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
}
@keyframes fade-up {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
