<script lang="ts" setup>
import type { ResourceApi } from '#/api/core/resource';

import { computed, onMounted, ref } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Alert,
  Button,
  Card,
  Input,
  message,
  Popconfirm,
  Progress,
  Tag,
} from 'ant-design-vue';
import { CheckCircle2, KeyRound, RefreshCw, ShieldCheck, XCircle } from 'lucide-vue-next';

import {
  clearQuarkCookieApi,
  getQuarkCookieStatusApi,
  listResourceSourcesApi,
  setQuarkCookieApi,
  verifyQuarkAccountApi,
} from '#/api/core/resource';

const cookieStatus = ref<null | ResourceApi.CookieStatus>(null);
const cookieInput = ref('');
const saving = ref(false);
const verifying = ref(false);
const account = ref<null | ResourceApi.QuarkAccount>(null);
const sources = ref<ResourceApi.SourceInfo[]>([]);

const hasToken = computed(() => cookieStatus.value?.has_token ?? false);

function formatSize(bytes: number) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let idx = 0;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx += 1;
  }
  return `${value.toFixed(1)} ${units[idx]}`;
}

async function fetchStatus() {
  try {
    cookieStatus.value = await getQuarkCookieStatusApi();
    if (cookieStatus.value?.has_token) {
      account.value = await verifyQuarkAccountApi();
    }
  } catch {
    // 状态读取失败不阻塞页面
  }
}

async function onSave() {
  const cookies = cookieInput.value.trim();
  if (!cookies) {
    message.warning('请粘贴夸克网盘 Cookie');
    return;
  }
  saving.value = true;
  try {
    cookieStatus.value = await setQuarkCookieApi(cookies);
    cookieInput.value = '';
    message.success('Cookie 已保存');
    await verifyAccount();
  } catch (e: any) {
    message.error(`保存失败：${e.message}`);
  } finally {
    saving.value = false;
  }
}

async function verifyAccount() {
  verifying.value = true;
  try {
    account.value = await verifyQuarkAccountApi();
    message.success(`验证通过：${account.value.nickname}`);
  } catch (e: any) {
    account.value = null;
    message.error(`验证失败：${e.message}`);
  } finally {
    verifying.value = false;
  }
}

async function onClear() {
  try {
    cookieStatus.value = await clearQuarkCookieApi();
    account.value = null;
    message.success('已清除夸克 Cookie');
  } catch (e: any) {
    message.error(`清除失败：${e.message}`);
  }
}

onMounted(async () => {
  fetchStatus();
  try {
    sources.value = await listResourceSourcesApi();
  } catch {
    sources.value = [];
  }
});
</script>

<template>
  <Page>
    <div class="mx-auto flex w-full max-w-4xl flex-col gap-4">
      <!-- 夸克 Cookie 配置 -->
      <Card
        class="rounded-xl border-slate-700/50 bg-slate-900/60"
        :bordered="false"
      >
        <template #title>
          <div class="flex items-center gap-2 text-[hsl(var(--foreground))]">
            <KeyRound class="size-4 text-[hsl(var(--primary))]" />
            夸克网盘 Cookie
          </div>
        </template>

        <div class="flex flex-col gap-4">
          <div class="flex flex-wrap items-center gap-3">
            <span class="text-sm text-[hsl(var(--muted-foreground))]">当前状态：</span>
            <Tag v-if="hasToken" color="success">
              <CheckCircle2 class="mr-1 inline size-3.5" />
              已配置（{{ cookieStatus?.preview }}）
            </Tag>
            <Tag v-else color="warning">
              <XCircle class="mr-1 inline size-3.5" />
              未配置
            </Tag>
          </div>

          <div class="flex flex-col gap-2">
            <div class="text-xs text-[hsl(var(--muted-foreground))]">
              登录 pan.quark.cn 后，浏览器开发者工具（F12）→ Network → 任意请求 → 请求头中复制完整的
              <span class="font-mono text-[hsl(var(--muted-foreground))]">Cookie</span> 值粘贴到下方
            </div>
            <Input.TextArea
              v-model:value="cookieInput"
              :rows="4"
              placeholder="粘贴完整 Cookie，如：__pus=xxx; __ss=xxx; __st=xxx; ..."
              class="!bg-slate-800/60"
            />
          </div>

          <div class="flex items-center gap-3">
            <Button type="primary" :loading="saving" @click="onSave">保存并验证</Button>
            <Button :loading="verifying" :disabled="!hasToken" @click="verifyAccount">
              <RefreshCw class="mr-1 size-4" />
              重新验证
            </Button>
            <Popconfirm
              title="确定清除夸克 Cookie 吗？"
              ok-text="清除"
              cancel-text="取消"
              :disabled="!hasToken"
              @confirm="onClear"
            >
              <Button danger :disabled="!hasToken">清除</Button>
            </Popconfirm>
          </div>

          <!-- 账号信息 -->
          <div
            v-if="account"
            class="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4"
          >
            <div class="mb-2 flex items-center gap-2 text-sm font-medium text-emerald-300">
              <ShieldCheck class="size-4" />
              验证通过：{{ account.nickname }}
              <Tag v-if="account.vip_member" color="gold">夸克会员</Tag>
            </div>
            <div class="flex items-center gap-4 text-xs text-[hsl(var(--muted-foreground))]">
              <span>已用 {{ formatSize(account.used) }}</span>
              <span>/</span>
              <span>总容量 {{ formatSize(account.capacity) }}</span>
              <Progress
                v-if="account.capacity > 0"
                class="max-w-[200px] flex-1"
                :percent="Math.min(100, Math.round((account.used / account.capacity) * 100))"
                size="small"
              />
            </div>
          </div>
        </div>
      </Card>

      <!-- 搜索渠道说明 -->
      <Card
        class="rounded-xl border-slate-700/50 bg-slate-900/60"
        :bordered="false"
      >
        <template #title>
          <div class="flex items-center gap-2 text-[hsl(var(--foreground))]">
            <ShieldCheck class="size-4 text-[hsl(var(--primary))]" />
            搜索渠道
          </div>
        </template>
        <div class="flex flex-col gap-3 text-sm text-[hsl(var(--muted-foreground))]">
          <div v-for="source in sources" :key="source.source_id" class="flex items-center gap-2">
            <Tag color="purple">{{ source.source_name }}</Tag>
            <span>搜索：{{ source.search_providers.join('、') }}</span>
            <Tag :color="source.supports_save ? 'success' : 'default'">
              {{ source.supports_save ? '支持转存' : '仅搜索' }}
            </Tag>
          </div>
          <Alert
            type="info"
            show-icon
            class="rounded-lg"
            message="搜索渠道说明"
            description="夸克网盘没有官方开放的资源搜索接口，系统通过 B站视频搜索、头条搜索聚合发现分享链接（Bing / DuckDuckGo 作为海外备选渠道）；搜索多渠道并发合并结果，0 结果时自动换词重试。若你有更稳定的第三方夸克搜索 API，可通过后端环境变量 WORKBENCH_QUARK_SEARCH_API 配置后自动优先使用。转存走夸克官方接口，不受搜索渠道影响。"
          />
        </div>
      </Card>

      <!-- 使用说明 -->
      <Card
        class="rounded-xl border-slate-700/50 bg-slate-900/60"
        :bordered="false"
      >
        <template #title>
          <div class="flex items-center gap-2 text-[hsl(var(--foreground))]">使用说明</div>
        </template>
        <ol class="flex list-decimal flex-col gap-2 pl-5 text-sm text-[hsl(var(--muted-foreground))]">
          <li>「资源搜索」页输入关键词（如电影名、书名），可切换电影 / 剧集 / 电子书等分类筛选；</li>
          <li>搜索结果中的「转存」按钮可把资源一键转存到你的夸克网盘，提取码会自动识别，也可手动填写；</li>
          <li>搜索不到时，可直接粘贴夸克分享链接（https://pan.quark.cn/s/xxxx）转存；</li>
          <li>「转存记录」页可查看所有转存历史与失败原因；</li>
          <li>Cookie 存放在本服务数据库中，仅用于调用夸克接口，不会泄露给第三方。</li>
        </ol>
      </Card>
    </div>
  </Page>
</template>
