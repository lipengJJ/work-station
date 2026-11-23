<script lang="ts" setup>
import type { TopicsApi } from '#/api/core/topics';

import { computed, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import { Drawer, message, Modal, Switch, Tooltip } from 'ant-design-vue';
import { ChevronRight, Plus, Search } from 'lucide-vue-next';

import TopicCreateWizard from './components/TopicCreateWizard.vue';
import TopicDetailPanel from './components/TopicDetailPanel.vue';

import { deleteTopicApi, listTopicsApi, updateTopicApi } from '#/api/core/topics';

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

// 主题数量通常不大，不走后端分页；搜索/状态筛选前端过滤即可
const searchQuery = ref('');
const statusFilter = ref<'' | 'disabled' | 'draft' | 'enabled'>('');

/** 三态：setup_done=false 是草稿（向导没走完），其余按 enabled 分「启用中/已停用」。 */
function topicStatus(t: TopicsApi.Topic): 'disabled' | 'draft' | 'enabled' {
  if (!t.setup_done) return 'draft';
  return t.enabled ? 'enabled' : 'disabled';
}

const filteredTopics = computed(() => {
  const q = searchQuery.value.trim().toLowerCase();
  return topics.value.filter((t) => {
    if (statusFilter.value && topicStatus(t) !== statusFilter.value) return false;
    if (q && !t.name.toLowerCase().includes(q) && !t.description.toLowerCase().includes(q)) return false;
    return true;
  });
});

function clearFilters() {
  searchQuery.value = '';
  statusFilter.value = '';
}

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

// -------------------------------------------------------------- 新建/续配（三步向导）----
const wizardOpen = ref(false);
const wizardResumeTopic = ref<null | TopicsApi.Topic>(null);

function openCreate() {
  wizardResumeTopic.value = null;
  wizardOpen.value = true;
}

function openResume(topic: TopicsApi.Topic) {
  wizardResumeTopic.value = topic;
  wizardOpen.value = true;
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

/** 草稿行点击=续配向导，其余=正常详情。 */
function openRow(topic: TopicsApi.Topic) {
  if (!topic.setup_done) openResume(topic);
  else openDetail(topic.id);
}

onMounted(fetchTopics);
</script>

<template>
  <Page :auto-content-height="true" content-class="!p-0">
    <div class="custom-scrollbar flex h-full flex-1 flex-col overflow-y-auto bg-background-deep p-6 lg:p-8 select-none">
      <!-- 页头 -->
      <div class="mb-6 flex shrink-0 items-start justify-between gap-3">
        <div>
          <h1 class="text-xl font-extrabold text-foreground">主题订阅</h1>
          <p class="mt-1 text-xs text-muted-foreground">按主题绑定源与关键词，用 Skill 定期产出 AI 日报 / 周报</p>
        </div>
        <button
          class="flex shrink-0 items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-xs font-bold text-white hover:bg-primary"
          @click="openCreate"
        >
          <Plus class="h-3.5 w-3.5" />
          新建主题
        </button>
      </div>

      <!-- 搜索 / 筛选 -->
      <div class="mb-4 flex shrink-0 flex-wrap items-center gap-2">
        <div class="relative">
          <Search class="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            v-model="searchQuery"
            placeholder="搜索主题名称或描述"
            class="w-64 rounded-lg border border-border bg-card py-1.5 pl-8 pr-3 text-xs text-foreground outline-none focus:border-primary"
          />
        </div>
        <select
          v-model="statusFilter"
          class="rounded-lg border border-border bg-card px-3 py-1.5 text-xs text-foreground outline-none focus:border-primary"
        >
          <option value="">全部状态</option>
          <option value="enabled">启用中</option>
          <option value="disabled">已停用</option>
          <option value="draft">草稿</option>
        </select>
      </div>

      <div class="shrink-0 overflow-hidden rounded-2xl border border-border bg-background-deep shadow-xl">
        <div class="overflow-x-auto">
          <table class="w-full text-left text-xs">
            <thead class="border-b border-border bg-card font-mono text-[11px] uppercase text-muted-foreground">
              <tr>
                <th class="px-4 py-3.5">主题</th>
                <th class="px-4 py-3.5">状态</th>
                <th class="px-4 py-3.5">周期</th>
                <th class="px-4 py-3.5">裁剪策略</th>
                <th class="px-4 py-3.5">启用源</th>
                <th class="px-4 py-3.5 text-right">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              <tr
                v-for="topic in filteredTopics"
                :key="topic.id"
                tabindex="0"
                class="group cursor-pointer transition-colors hover:bg-accent focus:bg-accent focus:outline-none focus-visible:ring-1 focus-visible:ring-primary"
                @click="openRow(topic)"
                @keyup.enter="openRow(topic)"
              >
                <td class="px-4 py-4">
                  <div class="font-semibold text-foreground">{{ topic.name }}</div>
                  <div class="mt-0.5 max-w-xs truncate text-[11px] text-muted-foreground">
                    {{ topic.description || '暂无描述' }}
                  </div>
                </td>
                <td class="px-4 py-4">
                  <div v-if="!topic.setup_done" class="flex items-center gap-2">
                    <span class="inline-flex items-center gap-1.5 font-semibold text-warning">
                      <span class="h-1.5 w-1.5 rounded-full bg-warning"></span>
                      草稿
                    </span>
                  </div>
                  <div v-else class="flex items-center gap-2">
                    <span
                      class="inline-flex items-center gap-1.5 font-semibold"
                      :class="topic.enabled ? 'text-success' : 'text-muted-foreground'"
                    >
                      <span class="h-1.5 w-1.5 rounded-full" :class="topic.enabled ? 'bg-success' : 'bg-muted-foreground'"></span>
                      {{ topic.enabled ? '启用中' : '已停用' }}
                    </span>
                    <Switch
                      :checked="topic.enabled"
                      size="small"
                      @click.stop
                      @change="(v: boolean | number | string) => toggleEnabled(topic, !!v)"
                    />
                  </div>
                </td>
                <td class="px-4 py-4 text-muted-foreground">{{ PERIOD_LABEL[topic.digest_period] }} · {{ topic.digest_cron }}</td>
                <td class="px-4 py-4 text-muted-foreground">{{ STRATEGY_LABEL[topic.digest_strategy] }}</td>
                <td class="px-4 py-4 font-mono text-foreground">
                  {{ topic.enabled_source_count }}
                  <Tooltip v-if="topic.enabled_source_count > 100" title="启用源数量超过护栏建议值">
                    <span class="ml-1 rounded-full bg-warning/15 px-2 py-0.5 text-[10px] font-medium text-warning">超护栏</span>
                  </Tooltip>
                </td>
                <td class="px-4 py-4 text-right">
                  <div class="flex items-center justify-end gap-3">
                    <button class="text-[11px] text-muted-foreground hover:text-destructive" @click.stop="removeTopic(topic)">
                      删除
                    </button>
                    <span class="inline-flex items-center gap-1 font-semibold text-primary">
                      {{ topic.setup_done ? '配置' : '继续配置' }}
                      <ChevronRight class="h-3.5 w-3.5" />
                    </span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="!loading && filteredTopics.length === 0" class="flex flex-col items-center justify-center gap-3 p-12 text-center">
          <template v-if="searchQuery || statusFilter">
            <p class="text-sm font-semibold text-foreground">没有匹配的主题</p>
            <button class="rounded-lg border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground" @click="clearFilters">
              清除筛选条件
            </button>
          </template>
          <template v-else>
            <p class="text-sm font-semibold text-foreground">还没有主题</p>
            <p class="text-xs text-muted-foreground">创建一个主题，绑定源与 Skill，AI 会按周期产出报告</p>
            <button
              class="rounded-lg bg-primary px-3 py-1.5 text-xs font-bold text-white hover:bg-primary"
              @click="openCreate"
            >
              新建主题
            </button>
          </template>
        </div>
      </div>
    </div>

    <!-- 新建 / 续配草稿：三步向导 -->
    <TopicCreateWizard v-model:open="wizardOpen" :resume-topic="wizardResumeTopic" @done="fetchTopics" />

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
