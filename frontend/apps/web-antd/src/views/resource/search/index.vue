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
  checkResourceLinksApi,
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
const searchError = ref('');

async function doSearch() {
  const kw = keyword.value.trim();
  if (!kw) {
    message.warning('请输入要搜索的资源名称');
    return;
  }
  loading.value = true;
  searchError.value = '';
  linkStatus.value = {}; // 新结果集，清空旧校验状态
  try {
    result.value = await searchResourceApi({
      keyword: kw,
      source: 'quark',
      category: category.value || undefined,
      page: page.value,
      page_size: pageSize,
    });
    searched.value = true;
    void checkResultLinks(result.value.items);
  } catch (e: any) {
    searched.value = false;
    result.value = null;
    searchError.value = e.message || '搜索失败，请稍后重试';
    message.error(`搜索失败：${searchError.value}`);
  } finally {
    loading.value = false;
  }
}

// ------------------------------------------------------------ 链接有效性校验 ----
// share_id -> 校验状态（valid / invalid / needs_pwd / unknown）
const linkStatus = ref<Record<string, ResourceApi.LinkCheckResult>>({});

async function checkResultLinks(items: ResourceApi.ResourceItem[]) {
  const pending = items.filter((item) => !linkStatus.value[item.share_id]);
  if (pending.length === 0) return;
  const BATCH = 10;
  for (let i = 0; i < pending.length; i += BATCH) {
    const batch = pending.slice(i, i + BATCH).map((item) => ({ share_id: item.share_id, pwd: item.share_pwd || undefined }));
    try {
      const checked = await checkResourceLinksApi(batch);
      const next = { ...linkStatus.value };
      for (const c of checked) next[c.share_id] = c;
      linkStatus.value = next;
    } catch {
      // 校验失败不阻塞展示，保持"未验证"状态
    }
  }
}

function statusOf(item: ResourceApi.ResourceItem): ResourceApi.LinkCheckResult | undefined {
  return linkStatus.value[item.share_id];
}

function canSave(item: ResourceApi.ResourceItem): boolean {
  const st = statusOf(item);
  return cookieReady.value && (!st || st.status !== 'invalid');
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
  const st = statusOf(item);
  if (st?.status === 'invalid') {
    message.error('该链接已失效，无法转存');
    return;
  }
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
// 空态引导"粘贴链接转存"按钮控制 Collapse 展开
const expanded = ref(false);

async function savePastedLink() {
  const link = pasteLink.value.trim();
  if (!link) {
    message.warning('请先粘贴夸克分享链接');
    return;
  }
  // 转存前先校验链接有效性
  pasteSaving.value = true;
  try {
    const checked = await checkResourceLinksApi([{ url: link }]);
    const st = checked?.[0];
    if (st?.status === 'invalid') {
      message.error(st.message || '该链接已失效，无法转存');
      pasteSaving.value = false;
      return;
    }
    if (st?.status === 'needs_pwd') {
      message.warning('该分享需要提取码，请填写提取码后再转存');
      pasteSaving.value = false;
      return;
    }
  } catch {
    // 校验接口异常时继续走转存（后端仍有预检兜底）
  }
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
        <div class="flex items-center gap-2 text-base font-semibold text-[hsl(var(--foreground))]">
          <Search class="size-5 text-[hsl(var(--primary))]" />
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
            <span v-if="result" class="text-xs text-[hsl(var(--muted-foreground))]">
              {{ result.message }}
            </span>
          </div>
        </div>
      </div>

      <!-- Cookie 未配置提示：明确区分搜索可用/转存不可用 -->
      <Alert
        v-if="!cookieReady"
        type="warning"
        show-icon
        class="rounded-lg"
      >
        <template #message>
          <div class="flex items-center justify-between gap-2">
            <span>
              <b class="text-[hsl(var(--foreground))]">搜索功能不受影响</b>；
              未配置夸克网盘 Cookie 时「转存」不可用。配置后即可一键转存到你的网盘。
            </span>
            <Button size="small" @click="router.push('/resource/settings')">
              <Settings class="mr-1 size-3.5" />
              去配置
            </Button>
          </div>
        </template>
      </Alert>

      <!-- 搜索失败（渠道全挂）：明确提示，不白屏 -->
      <Alert
        v-if="searchError"
        type="error"
        show-icon
        class="rounded-lg"
      >
        <template #message>
          <div class="flex flex-col gap-2">
            <span>搜索失败：{{ searchError }}</span>
            <span class="text-xs text-[hsl(var(--muted-foreground))]">
              可能是所有搜索渠道暂时不可用（网络受限或被限流），请稍后重试；也可直接粘贴夸克分享链接进行转存。
            </span>
            <div>
              <Button size="small" :loading="loading" @click="onKeywordSearch">重试</Button>
            </div>
          </div>
        </template>
      </Alert>

      <!-- 粘贴链接直接转存 -->
      <Collapse ghost class="!bg-transparent" v-model:active-key="expanded ? ['paste'] : []">
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
      <div v-if="loading" class="flex justify-center py-20 text-[hsl(var(--muted-foreground))]">
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
                  <!-- 链接有效性徽标：校验后显示 -->
                  <Tooltip v-if="statusOf(item)" :title="statusOf(item)?.message">
                    <Tag v-if="statusOf(item)?.status === 'valid'" color="green">
                      有效{{ statusOf(item)?.file_count ? ` · ${statusOf(item)?.file_count} 个文件` : '' }}
                    </Tag>
                    <Tag v-else-if="statusOf(item)?.status === 'invalid'" color="red">已失效</Tag>
                    <Tag v-else-if="statusOf(item)?.status === 'needs_pwd'" color="orange">需提取码</Tag>
                    <Tag v-else color="default">未验证</Tag>
                  </Tooltip>
                  <span v-if="item.category" class="text-xs text-[hsl(var(--muted-foreground))]">
                    {{ categoryLabel }}
                  </span>
                  <span class="truncate font-medium text-[hsl(var(--foreground))]">{{ item.title }}</span>
                </div>
                <div class="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--muted-foreground))]">
                  <span class="inline-flex items-center gap-1">
                    <Link2 class="size-3.5" />
                    <span class="font-mono">{{ item.url }}</span>
                  </span>
                  <Tooltip title="复制分享链接">
                    <Button
                      type="text"
                      size="small"
                      class="!text-[hsl(var(--muted-foreground))]"
                      @click="copyText(item.url)"
                    >
                      <ClipboardCopy class="size-3.5" />
                    </Button>
                  </Tooltip>
                  <Tag v-if="item.share_pwd" color="orange">提取码：{{ item.share_pwd }}</Tag>
                </div>
                <div v-if="item.snippet" class="mt-1.5 line-clamp-2 text-xs text-[hsl(var(--muted-foreground))]">
                  {{ item.snippet }}
                </div>
              </div>
              <Tooltip :title="statusOf(item)?.status === 'invalid' ? '该链接已失效' : ''">
                <Button
                  type="primary"
                  :disabled="!canSave(item)"
                  @click="openSaveModal(item)"
                >
                  <FolderPlus class="mr-1 size-4" />
                  转存
                </Button>
              </Tooltip>
            </div>
          </List.Item>
        </template>
      </List>

      <Empty
        v-else-if="searched && result && result.items.length === 0"
        class="rounded-xl border border-slate-700/50 bg-slate-900/60 py-16"
      >
        <template #description>
          <div class="flex flex-col items-center gap-3">
            <span class="text-[hsl(var(--foreground))]">{{ result?.message || '未找到夸克网盘资源' }}</span>
            <span class="text-xs text-[hsl(var(--muted-foreground))]">
              可尝试更换关键词、切换分类；或在下方向上展开「直接粘贴夸克分享链接」进行转存
            </span>
            <Button size="small" ghost @click="expanded = true">
              <FolderPlus class="mr-1 size-3.5" />
              粘贴链接转存
            </Button>
          </div>
        </template>
      </Empty>

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
        <div class="rounded-lg bg-slate-800/70 px-3 py-2 text-sm text-[hsl(var(--foreground))]">
          {{ saveTarget?.title }}
        </div>
        <div>
          <div class="mb-1 text-xs text-[hsl(var(--muted-foreground))]">提取码（该资源 {{ saveTarget?.share_pwd ? '已自动识别' : '无需提取码或需手动填写' }}）</div>
          <Input v-model:value="savePwd" placeholder="如有提取码请填写，如：1234" allow-clear />
        </div>
        <div>
          <div class="mb-1 text-xs text-[hsl(var(--muted-foreground))]">转存到目录（留空 = 网盘根目录）</div>
          <Input v-model:value="saveDir" placeholder="如：电影 / 电子书（自动创建）" allow-clear />
        </div>
      </div>
    </Modal>
  </Page>
</template>
