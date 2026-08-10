<script lang="ts" setup>
import type { ResourceApi } from '#/api/core/resource';

import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';

import {
  Alert,
  Button,
  Collapse,
  Empty,
  Input,
  List,
  message,
  Modal,
  Pagination,
  Segmented,
  Tag,
  Tooltip,
} from 'ant-design-vue';
import {
  ClipboardCopy,
  FolderPlus,
  Link2,
  Loader2,
  Search,
  Settings,
} from 'lucide-vue-next';

import {
  getQuarkCookieStatusApi,
  listResourceSourcesApi,
  saveResourceApi,
  searchResourceApi,
} from '#/api/core/resource';

const router = useRouter();

// ----------------------------------------------------------------- 状态 ----
const keyword = ref('');
const category = ref('');
const page = ref(1);
const pageSize = 20;
const loading = ref(false);
const searched = ref(false);
const result = ref<null | ResourceApi.SearchResult>(null);
const sources = ref<ResourceApi.SourceInfo[]>([]);
const cookieReady = ref(false);

const CATEGORY_OPTIONS = [
  { label: '全部', value: '' },
  { label: '电影', value: 'movie' },
  { label: '剧集', value: 'tv' },
  { label: '电子书', value: 'book' },
  { label: '动漫', value: 'anime' },
  { label: '音乐', value: 'music' },
];
const categoryLabel = computed(
  () => CATEGORY_OPTIONS.find((opt) => opt.value === category.value)?.label ?? '全部',
);

onMounted(async () => {
  try {
    sources.value = await listResourceSourcesApi();
  } catch {
    sources.value = [];
  }
  try {
    cookieReady.value = (await getQuarkCookieStatusApi()).has_token;
  } catch {
    cookieReady.value = false;
  }
});

// ----------------------------------------------------------------- 搜索 ----
async function doSearch() {
  const kw = keyword.value.trim();
  if (!kw) {
    message.warning('请输入要搜索的资源名称');
    return;
  }
  loading.value = true;
  try {
    result.value = await searchResourceApi({
      keyword: kw,
      source: 'quark',
      category: category.value || undefined,
      page: page.value,
      page_size: pageSize,
    });
    searched.value = true;
  } catch (e: any) {
    message.error(`搜索失败：${e.message}`);
  } finally {
    loading.value = false;
  }
}

function onKeywordSearch() {
  page.value = 1;
  doSearch();
}

function onCategoryChange(value: number | string) {
  category.value = String(value);
  page.value = 1;
  if (keyword.value.trim()) doSearch();
}

function onPageChange(next: number) {
  page.value = next;
  doSearch();
}

function copyText(text: string) {
  navigator.clipboard?.writeText(text).then(
    () => message.success('链接已复制'),
    () => message.warning('复制失败，请手动复制'),
  );
}

// --------------------------------------------------------------- 转存弹窗 ----
const saveModalOpen = ref(false);
const saving = ref(false);
const saveTarget = ref<null | ResourceApi.ResourceItem>(null);
const savePwd = ref('');
const saveDir = ref('');

function openSaveModal(item: ResourceApi.ResourceItem) {
  saveTarget.value = item;
  savePwd.value = item.share_pwd || '';
  saveDir.value = '';
  saveModalOpen.value = true;
}

async function confirmSave() {
  if (!saveTarget.value) return;
  saving.value = true;
  try {
    const task = await saveResourceApi({
      source: 'quark',
      share_url: saveTarget.value.url,
      share_pwd: savePwd.value.trim() || undefined,
      target_dir: saveDir.value.trim() || undefined,
    });
    saveModalOpen.value = false;
    if (task.status === 'success') {
      message.success(task.message || '转存成功');
    } else {
      message.error(task.message || '转存失败');
    }
  } catch (e: any) {
    message.error(`转存失败：${e.message}`);
  } finally {
    saving.value = false;
  }
}

// --------------------------------------------------------- 粘贴链接直接转存 ----
const pasteLink = ref('');
const pasteSaving = ref(false);

async function savePastedLink() {
  const link = pasteLink.value.trim();
  if (!link) {
    message.warning('请先粘贴夸克分享链接');
    return;
  }
  pasteSaving.value = true;
  try {
    const task = await saveResourceApi({ source: 'quark', share_url: link });
    if (task.status === 'success') {
      message.success(task.message || '转存成功');
      pasteLink.value = '';
    } else {
      message.error(task.message || '转存失败');
    }
  } catch (e: any) {
    message.error(`转存失败：${e.message}`);
  } finally {
    pasteSaving.value = false;
  }
}
</script>

<template>
  <Page>
    <div class="mx-auto flex w-full max-w-5xl flex-col gap-4">
      <!-- 搜索区 -->
      <div
        class="rounded-xl border border-slate-700/50 bg-slate-900/60 p-5 shadow-lg backdrop-blur"
      >
        <div class="flex items-center gap-2 text-base font-semibold text-slate-200">
          <Search class="size-5 text-[#665cff]" />
          夸克网盘资源搜索
        </div>
        <div class="mt-4 flex flex-col gap-3">
          <div class="flex items-center gap-3">
            <Input
              v-model:value="keyword"
              class="flex-1"
              size="large"
              placeholder="输入资源名称，如：流浪地球、三体、经济学原理…"
              allow-clear
              @press-enter="onKeywordSearch"
            />
            <Button type="primary" size="large" :loading="loading" @click="onKeywordSearch">
              搜索
            </Button>
          </div>
          <div class="flex items-center gap-3">
            <Segmented
              :options="CATEGORY_OPTIONS"
              :value="category"
              class="!bg-slate-800"
              @change="onCategoryChange"
            />
            <span v-if="result" class="text-xs text-slate-400">
              {{ result.message }}
            </span>
          </div>
        </div>
      </div>

      <!-- Cookie 未配置提示 -->
      <Alert
        v-if="!cookieReady"
        type="warning"
        show-icon
        class="rounded-lg"
      >
        <template #message>
          <div class="flex items-center justify-between gap-2">
            <span>
              尚未配置夸克网盘 Cookie，转存功能不可用（搜索不受影响）。配置后即可一键转存到你的网盘。
            </span>
            <Button size="small" @click="router.push('/resource/settings')">
              <Settings class="mr-1 size-3.5" />
              去配置
            </Button>
          </div>
        </template>
      </Alert>

      <!-- 粘贴链接直接转存 -->
      <Collapse ghost class="!bg-transparent">
        <Collapse.Panel key="paste" header="没有搜到？直接粘贴夸克分享链接一键转存">
          <div class="flex items-center gap-3 py-2">
            <Input
              v-model:value="pasteLink"
              placeholder="https://pan.quark.cn/s/xxxx（支持带提取码的分享）"
              allow-clear
              @press-enter="savePastedLink"
            />
            <Button
              type="primary"
              ghost
              :loading="pasteSaving"
              :disabled="!cookieReady"
              @click="savePastedLink"
            >
              <FolderPlus class="mr-1 size-4" />
              转存到网盘
            </Button>
          </div>
        </Collapse.Panel>
      </Collapse>

      <!-- 结果列表 -->
      <div v-if="loading" class="flex justify-center py-20 text-slate-400">
        <Loader2 class="size-6 animate-spin" />
      </div>

      <List
        v-else-if="result && result.items.length > 0"
        class="rounded-xl border border-slate-700/50 bg-slate-900/60"
        :data-source="result.items"
        :pagination="false"
      >
        <template #renderItem="{ item }">
          <List.Item class="!px-5 !py-4">
            <div class="flex w-full items-start justify-between gap-4">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <Tag color="purple">夸克</Tag>
                  <span v-if="item.category" class="text-xs text-slate-500">
                    {{ categoryLabel }}
                  </span>
                  <span class="truncate font-medium text-slate-200">{{ item.title }}</span>
                </div>
                <div class="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                  <span class="inline-flex items-center gap-1">
                    <Link2 class="size-3.5" />
                    <span class="font-mono">{{ item.url }}</span>
                  </span>
                  <Tooltip title="复制分享链接">
                    <Button
                      type="text"
                      size="small"
                      class="!text-slate-400"
                      @click="copyText(item.url)"
                    >
                      <ClipboardCopy class="size-3.5" />
                    </Button>
                  </Tooltip>
                  <Tag v-if="item.share_pwd" color="orange">提取码：{{ item.share_pwd }}</Tag>
                </div>
                <div v-if="item.snippet" class="mt-1.5 line-clamp-2 text-xs text-slate-500">
                  {{ item.snippet }}
                </div>
              </div>
              <Button
                type="primary"
                :disabled="!cookieReady"
                @click="openSaveModal(item)"
              >
                <FolderPlus class="mr-1 size-4" />
                转存
              </Button>
            </div>
          </List.Item>
        </template>
      </List>

      <Empty
        v-else-if="searched && result && result.items.length === 0"
        class="rounded-xl border border-slate-700/50 bg-slate-900/60 py-16"
        :description="result?.message || '未找到相关资源'"
      />

      <!-- 分页 -->
      <div v-if="result && result.total > pageSize" class="flex justify-center">
        <Pagination
          :current="page"
          :page-size="pageSize"
          :total="result.total"
          :show-size-changer="false"
          @change="onPageChange"
        />
      </div>
    </div>

    <!-- 转存确认弹窗 -->
    <Modal
      v-model:open="saveModalOpen"
      title="转存到夸克网盘"
      :confirm-loading="saving"
      ok-text="确认转存"
      cancel-text="取消"
      @ok="confirmSave"
    >
      <div class="flex flex-col gap-3 py-2">
        <div class="rounded-lg bg-slate-800/70 px-3 py-2 text-sm text-slate-200">
          {{ saveTarget?.title }}
        </div>
        <div>
          <div class="mb-1 text-xs text-slate-400">提取码（该资源 {{ saveTarget?.share_pwd ? '已自动识别' : '无需提取码或需手动填写' }}）</div>
          <Input v-model:value="savePwd" placeholder="如有提取码请填写，如：1234" allow-clear />
        </div>
        <div>
          <div class="mb-1 text-xs text-slate-400">转存到目录（留空 = 网盘根目录）</div>
          <Input v-model:value="saveDir" placeholder="如：电影 / 电子书（自动创建）" allow-clear />
        </div>
      </div>
    </Modal>
  </Page>
</template>
