<script lang="ts" setup>
import type { XhsApi } from '#/api/core/xhs';

import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';

import { Page } from '@vben/common-ui';

import {
  Alert,
  Button,
  Card,
  Carousel,
  Checkbox,
  Col,
  Empty,
  Form,
  FormItem,
  Image,
  Input,
  InputNumber,
  message,
  Modal,
  Progress,
  Row,
  Select,
  Switch,
  Tabs,
  Tag,
} from 'ant-design-vue';

import {
  buildXhsMediaProxyUrl,
  clearXhsTokenApi,
  createXhsCollectTaskApi,
  deleteXhsCollectTaskApi,
  deleteXhsNoteApi,
  deleteXhsNotesApi,
  downloadXhsCollectTaskApi,
  getXhsCollectTaskPreviewApi,
  getXhsTokenApi,
  getXhsTokenFullApi,
  listXhsCollectTasksApi,
  pollXhsQrcodeLoginApi,
  sendXhsPhoneCodeApi,
  setXhsTokenApi,
  startXhsQrcodeLoginApi,
  verifyXhsPhoneLoginApi,
} from '#/api/core/xhs';

const TextArea = Input.TextArea;

const SORT_OPTIONS = [
  { value: 0, label: '综合排序' },
  { value: 1, label: '最新' },
  { value: 2, label: '最多点赞' },
  { value: 3, label: '最多评论' },
  { value: 4, label: '最多收藏' },
];
const NOTE_TYPE_OPTIONS = [
  { value: 0, label: '不限' },
  { value: 1, label: '视频笔记' },
  { value: 2, label: '普通笔记' },
];
const NOTE_TIME_OPTIONS = [
  { value: 0, label: '不限' },
  { value: 1, label: '一天内' },
  { value: 2, label: '一周内' },
  { value: 3, label: '半年内' },
];
const NOTE_RANGE_OPTIONS = [
  { value: 0, label: '不限' },
  { value: 1, label: '已看过' },
  { value: 2, label: '未看过' },
  { value: 3, label: '已关注' },
];
const STATUS_LABEL: Record<string, string> = {
  pending: '排队中',
  running: '运行中',
  success: '已完成',
  failed: '失败',
};
const STATUS_COLOR: Record<string, string> = {
  pending: 'default',
  running: 'processing',
  success: 'success',
  failed: 'error',
};
const PHASE_LABEL: Record<string, string> = {
  queued: '等待开始',
  searching: '搜索中',
  fetching_notes: '抓取笔记详情',
  downloading_media: '下载素材',
  fetching_comments: '抓取评论',
  exporting: '导出文件',
  done: '已完成',
  failed: '失败',
};

function defaultTaskForm(): XhsApi.CollectTaskParams {
  return {
    keyword: '',
    require_num: 50,
    sort_type_choice: 0,
    note_type: 0,
    note_time: 0,
    note_range: 0,
    // 直接抓全部：Excel + 图文 + 视频素材，不再让用户选保存方式
    save_choice: 'all',
    fetch_comments: false,
    max_comments_per_note: null,
    comment_interval_seconds: null,
  };
}

// ---------------------------------------------------------------- token ----

const tokenStatus = ref<XhsApi.TokenStatus>({
  has_token: false,
  preview: null,
  updated_at: null,
});
const tokenModalOpen = ref(false);
const loginTab = ref('qrcode');

const qrcode = reactive({ loading: false, image: '', qrId: '', message: '' });
let qrcodeTimer: ReturnType<typeof setInterval> | undefined;

const phone = reactive({
  zone: '86',
  number: '',
  code: '',
  sending: false,
  verifying: false,
  message: '',
});
const manual = reactive({ cookies: '', saving: false, message: '' });

async function refreshTokenStatus() {
  tokenStatus.value = await getXhsTokenApi();
}

async function startQrcode() {
  if (qrcodeTimer) clearInterval(qrcodeTimer);
  qrcode.loading = true;
  qrcode.image = '';
  try {
    const data = await startXhsQrcodeLoginApi();
    if (data.status !== 'ok' || !data.qr_id || !data.qr_image) {
      message.error(`获取二维码失败：${data.msg}`);
      return;
    }
    qrcode.image = data.qr_image;
    qrcode.qrId = data.qr_id;
    qrcode.message = '请使用小红书 App 扫描二维码';
    qrcodeTimer = setInterval(pollQrcode, 2000);
  } catch (e: any) {
    message.error(`获取二维码失败：${e.message}`);
  } finally {
    qrcode.loading = false;
  }
}

async function pollQrcode() {
  try {
    const s = await pollXhsQrcodeLoginApi(qrcode.qrId);
    if (s.status === 'success') {
      clearInterval(qrcodeTimer);
      qrcode.message = `登录成功：${s.nickname}`;
      message.success('登录成功');
      refreshTokenStatus();
    } else if (s.status === 'expired') {
      clearInterval(qrcodeTimer);
      qrcode.message = s.msg || '二维码已过期，请重新获取';
    } else {
      qrcode.message = s.msg || '等待扫码...';
    }
  } catch (e: any) {
    clearInterval(qrcodeTimer);
    qrcode.message = `轮询失败：${e.message}`;
  }
}

async function sendPhoneCode() {
  if (!phone.number.trim()) {
    phone.message = '请输入手机号';
    return;
  }
  phone.sending = true;
  try {
    const res = await sendXhsPhoneCodeApi(phone.number.trim(), phone.zone.trim() || '86');
    phone.message = res.success ? '验证码已发送' : `发送失败：${res.msg}`;
  } catch (e: any) {
    phone.message = `发送失败：${e.message}`;
  } finally {
    phone.sending = false;
  }
}

async function verifyPhone() {
  if (!phone.number.trim() || !phone.code.trim()) {
    phone.message = '请输入手机号和验证码';
    return;
  }
  phone.verifying = true;
  try {
    const res = await verifyXhsPhoneLoginApi(
      phone.number.trim(),
      phone.code.trim(),
      phone.zone.trim() || '86',
    );
    if (res.success) {
      phone.message = `登录成功：${res.nickname}`;
      message.success('登录成功');
      refreshTokenStatus();
    } else {
      phone.message = `登录失败：${res.msg}`;
    }
  } catch (e: any) {
    phone.message = `登录失败：${e.message}`;
  } finally {
    phone.verifying = false;
  }
}

async function saveManualCookie() {
  const val = manual.cookies.trim();
  if (!val) {
    manual.message = '请粘贴 cookie 内容';
    return;
  }
  manual.saving = true;
  try {
    await setXhsTokenApi(val);
    manual.message = '保存成功';
    message.success('Token 已保存');
    refreshTokenStatus();
  } catch (e: any) {
    manual.message = `保存失败：${e.message}`;
  } finally {
    manual.saving = false;
  }
}

async function viewFullCookie() {
  try {
    const data = await getXhsTokenFullApi();
    manual.cookies = data.cookies;
    manual.message = '已加载当前完整 cookie';
  } catch (e: any) {
    manual.message = `获取失败：${e.message}`;
  }
}

function clearToken() {
  Modal.confirm({
    title: '确定清除已保存的 token 吗？',
    content: '仅清除本系统里保存的 cookie，不影响其它地方。',
    okType: 'danger',
    onOk: async () => {
      await clearXhsTokenApi();
      manual.cookies = '';
      manual.message = '已清除';
      refreshTokenStatus();
    },
  });
}

// ---------------------------------------------------------------- tasks ----

const taskForm = reactive(defaultTaskForm());
const submitting = ref(false);
const tasks = ref<XhsApi.CollectTask[]>([]);
const tasksLoading = ref(false);
let tasksTimer: ReturnType<typeof setInterval> | undefined;

async function fetchTasks() {
  tasksLoading.value = true;
  try {
    tasks.value = await listXhsCollectTasksApi();
  } catch {
    // 忽略单次轮询失败，下一轮再试
  } finally {
    tasksLoading.value = false;
  }
}

async function submitTask() {
  if (!taskForm.keyword.trim()) {
    message.error('请输入关键词');
    return;
  }
  submitting.value = true;
  try {
    await createXhsCollectTaskApi({ ...taskForm, keyword: taskForm.keyword.trim() });
    message.success('任务已创建，请在下方查看进度');
    Object.assign(taskForm, defaultTaskForm());
    fetchTasks();
  } catch (e: any) {
    message.error(`创建失败：${e.message}`);
  } finally {
    submitting.value = false;
  }
}

function deleteTask(taskId: number) {
  Modal.confirm({
    title: '确定删除该任务及其所有数据吗？',
    content: '此操作不可恢复。',
    okType: 'danger',
    onOk: async () => {
      try {
        await deleteXhsCollectTaskApi(taskId);
        fetchTasks();
      } catch (e: any) {
        message.error(`删除失败：${e.message}`);
      }
    },
  });
}

function downloadFile(taskId: number, kind: 'archive' | 'comments' | 'excel') {
  downloadXhsCollectTaskApi(taskId, kind).catch((e: any) => {
    message.error(`下载失败：${e.message}`);
  });
}

function statusLabel(s: string) {
  return STATUS_LABEL[s] ?? s;
}
function statusColor(s: string) {
  return STATUS_COLOR[s] ?? 'default';
}
function phaseLabel(p: string) {
  return PHASE_LABEL[p] ?? p;
}
function progressPercent(task: XhsApi.CollectTask) {
  if (!task.progress_total) return 0;
  return Math.min(100, Math.round((task.progress_current / task.progress_total) * 100));
}
function hasExcel(task: XhsApi.CollectTask) {
  return task.files.excel_files.some((f) => !f.endsWith('_comments.xlsx'));
}
function hasComments(task: XhsApi.CollectTask) {
  return task.files.excel_files.some((f) => f.endsWith('_comments.xlsx'));
}
function hasAnyFile(task: XhsApi.CollectTask) {
  return task.files.excel_files.length > 0 || task.files.media_file_count > 0;
}

// -------------------------------------------------------- preview / detail ----

const previewModalOpen = ref(false);
const previewLoading = ref(false);
const previewTaskId = ref<number>();
const previewTaskKeyword = ref('');
const previewNotes = ref<XhsApi.Note[]>([]);
const previewComments = ref<XhsApi.Comment[]>([]);

const previewNotesLimited = computed(() => previewNotes.value.slice(0, 300));

const selectedNoteIds = ref<Set<string>>(new Set());
const selectedCount = computed(() => selectedNoteIds.value.size);
const allSelected = computed(
  () => previewNotesLimited.value.length > 0 && selectedCount.value === previewNotesLimited.value.length,
);

function isSelected(noteId: string) {
  return selectedNoteIds.value.has(noteId);
}

function toggleNoteSelection(noteId: string) {
  const next = new Set(selectedNoteIds.value);
  if (next.has(noteId)) {
    next.delete(noteId);
  } else {
    next.add(noteId);
  }
  selectedNoteIds.value = next;
}

function toggleSelectAll() {
  selectedNoteIds.value = allSelected.value
    ? new Set()
    : new Set(previewNotesLimited.value.map((n) => n.note_id));
}

async function openPreview(task: XhsApi.CollectTask) {
  previewTaskId.value = task.id;
  previewTaskKeyword.value = task.keyword;
  previewModalOpen.value = true;
  previewLoading.value = true;
  previewNotes.value = [];
  previewComments.value = [];
  selectedNoteIds.value = new Set();
  try {
    const data = await getXhsCollectTaskPreviewApi(task.id);
    previewNotes.value = data.notes;
    previewComments.value = data.comments;
  } catch (e: any) {
    message.error(`加载预览失败：${e.message}`);
  } finally {
    previewLoading.value = false;
  }
}

function coverOf(note: XhsApi.Note) {
  return note.video_cover || note.image_list[0] || '';
}

function proxied(url: string) {
  return buildXhsMediaProxyUrl(url);
}

function noteComments(noteId: string) {
  return previewComments.value.filter((c) => c.note_id === noteId);
}

function deleteNote(note: XhsApi.Note) {
  if (previewTaskId.value === undefined) return;
  const taskId = previewTaskId.value;
  Modal.confirm({
    title: `确定删除笔记《${note.title || '无标题'}》吗？`,
    content: '已保存的素材文件也会一并删除。',
    okType: 'danger',
    onOk: async () => {
      try {
        await deleteXhsNoteApi(taskId, note.note_id);
        previewNotes.value = previewNotes.value.filter((n) => n.note_id !== note.note_id);
        previewComments.value = previewComments.value.filter((c) => c.note_id !== note.note_id);
        if (detailNote.value?.note_id === note.note_id) {
          detailModalOpen.value = false;
        }
        message.success('已删除该笔记');
        fetchTasks();
      } catch (e: any) {
        message.error(`删除失败：${e.message}`);
      }
    },
  });
}

function bulkDeleteSelected() {
  if (previewTaskId.value === undefined || selectedNoteIds.value.size === 0) return;
  const taskId = previewTaskId.value;
  const noteIds = [...selectedNoteIds.value];
  Modal.confirm({
    title: `确定删除选中的 ${noteIds.length} 篇笔记吗？`,
    content: '已保存的素材文件也会一并删除，此操作不可恢复。',
    okType: 'danger',
    onOk: async () => {
      try {
        await deleteXhsNotesApi(taskId, noteIds);
        const noteIdSet = new Set(noteIds);
        previewNotes.value = previewNotes.value.filter((n) => !noteIdSet.has(n.note_id));
        previewComments.value = previewComments.value.filter((c) => !noteIdSet.has(c.note_id));
        if (detailNote.value && noteIdSet.has(detailNote.value.note_id)) {
          detailModalOpen.value = false;
        }
        selectedNoteIds.value = new Set();
        message.success(`已删除 ${noteIds.length} 篇笔记`);
        fetchTasks();
      } catch (e: any) {
        message.error(`删除失败：${e.message}`);
      }
    },
  });
}

// ---------------------------------------------------------- note detail ----

const detailModalOpen = ref(false);
const detailNote = ref<XhsApi.Note>();

function openDetail(note: XhsApi.Note) {
  detailNote.value = note;
  detailModalOpen.value = true;
}

onMounted(() => {
  refreshTokenStatus();
  fetchTasks();
  tasksTimer = setInterval(fetchTasks, 3000);
});

onBeforeUnmount(() => {
  if (tasksTimer) clearInterval(tasksTimer);
  if (qrcodeTimer) clearInterval(qrcodeTimer);
});
</script>

<template>
  <Page :auto-content-height="false">
    <Alert
      :type="tokenStatus.has_token ? 'success' : 'warning'"
      show-icon
      style="margin-bottom: 16px"
    >
      <template #message>
        <span v-if="tokenStatus.has_token">
          Token 已配置 {{ tokenStatus.preview }}
        </span>
        <span v-else>尚未配置小红书 Token，请先获取</span>
      </template>
      <template #action>
        <Button size="small" @click="tokenModalOpen = true">获取 / 管理 Token</Button>
      </template>
    </Alert>

    <Row :gutter="16">
      <Col :span="8">
        <Card title="新建采集任务">
          <Form layout="vertical" @submit.prevent="submitTask">
            <FormItem label="关键词">
              <Input v-model:value="taskForm.keyword" placeholder="例如：普吉岛酒店推荐" />
            </FormItem>
            <FormItem label="采集数量">
              <InputNumber
                v-model:value="taskForm.require_num"
                :min="1"
                :max="1000"
                style="width: 100%"
              />
            </FormItem>
            <FormItem label="排序方式">
              <Select v-model:value="taskForm.sort_type_choice" :options="SORT_OPTIONS" />
            </FormItem>
            <FormItem label="笔记类型">
              <Select v-model:value="taskForm.note_type" :options="NOTE_TYPE_OPTIONS" />
            </FormItem>
            <FormItem label="发布时间">
              <Select v-model:value="taskForm.note_time" :options="NOTE_TIME_OPTIONS" />
            </FormItem>
            <FormItem label="笔记范围">
              <Select v-model:value="taskForm.note_range" :options="NOTE_RANGE_OPTIONS" />
            </FormItem>
            <FormItem>
              <Switch v-model:checked="taskForm.fetch_comments" /> 同时抓取评论
            </FormItem>
            <FormItem v-if="taskForm.fetch_comments" label="每篇评论上限（留空 = 不限制）">
              <InputNumber
                :value="taskForm.max_comments_per_note ?? undefined"
                :min="1"
                style="width: 100%"
                @update:value="(v) => (taskForm.max_comments_per_note = v == null ? null : Number(v))"
              />
            </FormItem>
            <Button type="primary" html-type="submit" block :loading="submitting">
              开始采集
            </Button>
          </Form>
        </Card>
      </Col>

      <Col :span="16">
        <Card title="任务列表" :loading="tasksLoading && tasks.length === 0">
          <Empty v-if="!tasks.length" description="暂无任务，先在左侧发起一次采集吧" />
          <Card
            v-for="task in tasks"
            :key="task.id"
            size="small"
            style="margin-bottom: 12px"
          >
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
              <strong>{{ task.keyword }}</strong>
              <Tag :color="statusColor(task.status)">{{ statusLabel(task.status) }}</Tag>
              <Tag v-if="task.note_count">{{ task.note_count }} 篇</Tag>
              <Tag v-if="task.params.save_choice === 'preview'" color="purple">仅预览</Tag>
              <span style="flex: 1"></span>
              <span style="color: rgba(0, 0, 0, 0.45); font-size: 12px">
                {{ task.created_at }}
              </span>
            </div>

            <div v-if="task.status === 'running' || task.status === 'pending'" style="margin-top: 8px">
              <div style="display: flex; justify-content: space-between; font-size: 12px">
                <span>{{ phaseLabel(task.phase) }}</span>
                <span v-if="task.progress_total">
                  {{ task.progress_current }} / {{ task.progress_total }}
                </span>
              </div>
              <Progress
                :percent="progressPercent(task)"
                :status="task.status === 'running' ? 'active' : undefined"
                size="small"
              />
            </div>

            <Alert
              v-if="task.status === 'failed'"
              type="error"
              :message="task.message ?? '任务失败'"
              show-icon
              style="margin-top: 8px"
            />

            <div style="margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center">
              <Button v-if="task.has_preview" size="small" @click="openPreview(task)">
                预览数据
              </Button>
              <Button v-if="hasExcel(task)" size="small" type="text" @click="downloadFile(task.id, 'excel')">
                下载 Excel
              </Button>
              <Button v-if="hasComments(task)" size="small" type="text" @click="downloadFile(task.id, 'comments')">
                下载评论
              </Button>
              <Button v-if="hasAnyFile(task)" size="small" type="text" @click="downloadFile(task.id, 'archive')">
                打包下载
              </Button>
              <span style="flex: 1"></span>
              <Button
                size="small"
                type="text"
                danger
                :disabled="task.status === 'running'"
                @click="deleteTask(task.id)"
              >
                删除
              </Button>
            </div>
          </Card>
        </Card>
      </Col>
    </Row>

    <!-- Token 管理 -->
    <Modal v-model:open="tokenModalOpen" title="获取 / 管理 Token" :footer="null" width="480px">
      <Tabs v-model:active-key="loginTab">
        <Tabs.TabPane key="qrcode" tab="扫码登录">
          <div style="text-align: center">
            <Button type="primary" :loading="qrcode.loading" @click="startQrcode">获取二维码</Button>
            <div v-if="qrcode.image" style="margin-top: 16px">
              <img :src="qrcode.image" width="200" height="200" style="border-radius: 8px" />
              <p style="margin-top: 8px; color: rgba(0, 0, 0, 0.65)">{{ qrcode.message }}</p>
            </div>
          </div>
        </Tabs.TabPane>
        <Tabs.TabPane key="phone" tab="手机号登录">
          <div style="display: flex; gap: 8px; margin-bottom: 8px">
            <Input v-model:value="phone.zone" style="width: 70px" />
            <Input v-model:value="phone.number" placeholder="手机号" />
            <Button :loading="phone.sending" @click="sendPhoneCode">发送验证码</Button>
          </div>
          <div style="display: flex; gap: 8px">
            <Input v-model:value="phone.code" placeholder="验证码" />
            <Button type="primary" :loading="phone.verifying" @click="verifyPhone">
              验证并登录
            </Button>
          </div>
          <p style="margin-top: 8px; color: rgba(0, 0, 0, 0.65)">{{ phone.message }}</p>
        </Tabs.TabPane>
        <Tabs.TabPane key="manual" tab="手动粘贴">
          <TextArea
            v-model:value="manual.cookies"
            :rows="4"
            placeholder="key1=value1; key2=value2; ..."
          />
          <div style="margin-top: 8px; display: flex; gap: 8px">
            <Button type="primary" :loading="manual.saving" @click="saveManualCookie">保存</Button>
            <Button @click="viewFullCookie">查看当前完整值</Button>
            <Button danger @click="clearToken">清除</Button>
          </div>
          <p style="margin-top: 8px; color: rgba(0, 0, 0, 0.65)">{{ manual.message }}</p>
        </Tabs.TabPane>
      </Tabs>
    </Modal>

    <!-- 数据预览：笔记卡片网格 -->
    <Modal
      v-model:open="previewModalOpen"
      :title="`数据预览 · ${previewTaskKeyword}（共 ${previewNotes.length} 篇）`"
      :footer="null"
      width="960px"
    >
      <div v-if="previewLoading" style="text-align: center; padding: 32px">加载中...</div>
      <template v-else>
        <Alert
          v-if="previewNotes.length > 300"
          type="info"
          message="为避免页面卡顿，仅展示前 300 篇；完整数据请使用 Excel / 打包下载。"
          style="margin-bottom: 12px"
        />
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px">
          <Checkbox :checked="allSelected" @change="toggleSelectAll">全选</Checkbox>
          <span v-if="selectedCount" style="color: rgba(0, 0, 0, 0.45); font-size: 13px">
            已选 {{ selectedCount }} 篇
          </span>
          <Button v-if="selectedCount" danger size="small" @click="bulkDeleteSelected">
            批量删除
          </Button>
        </div>
        <Row :gutter="[12, 12]" style="max-height: 62vh; overflow-y: auto">
          <Col v-for="note in previewNotesLimited" :key="note.note_id" :span="8">
            <Card size="small" hoverable @click="openDetail(note)">
              <template #cover>
                <div style="position: relative; width: 100%; height: 160px; overflow: hidden; background: #f0f0f0">
                  <Image
                    :src="proxied(coverOf(note))"
                    :preview="false"
                    width="100%"
                    height="160px"
                    style="object-fit: cover; display: block"
                    fallback="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxIiBoZWlnaHQ9IjEiLz4="
                  />
                  <Checkbox
                    :checked="isSelected(note.note_id)"
                    style="position: absolute; top: 6px; left: 6px"
                    @click.stop
                    @change="toggleNoteSelection(note.note_id)"
                  />
                  <Button
                    danger
                    shape="circle"
                    size="small"
                    style="position: absolute; top: 4px; right: 4px"
                    @click.stop="deleteNote(note)"
                  >
                    ×
                  </Button>
                </div>
              </template>
              <Card.Meta :title="note.title || '无标题'" :description="note.nickname" />
              <div style="margin-top: 8px; font-size: 12px; color: rgba(0, 0, 0, 0.45)">
                ♥ {{ note.liked_count }} ・ ★ {{ note.collected_count }} ・ 💬 {{ note.comment_count }}
              </div>
            </Card>
          </Col>
        </Row>
      </template>
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
          <div v-for="(img, idx) in detailNote.image_list" :key="idx">
            <img :src="proxied(img)" style="width: 100%; max-height: 420px; object-fit: contain" />
          </div>
        </Carousel>
        <video
          v-else-if="detailNote.video_addr"
          :src="proxied(detailNote.video_addr)"
          controls
          style="width: 100%; max-height: 420px; background: #000"
        ></video>

        <p style="margin-top: 12px; white-space: pre-wrap">{{ detailNote.desc }}</p>
        <div style="margin-bottom: 8px">
          <Tag v-for="tag in detailNote.tags" :key="tag">#{{ tag }}</Tag>
        </div>
        <p style="color: rgba(0, 0, 0, 0.45); font-size: 12px">
          {{ detailNote.nickname }} · {{ detailNote.upload_time }} · {{ detailNote.ip_location }}
        </p>

        <template v-if="noteComments(detailNote.note_id).length">
          <div style="margin: 12px 0; font-weight: 500">
            评论（{{ noteComments(detailNote.note_id).length }}）
          </div>
          <div
            v-for="c in noteComments(detailNote.note_id)"
            :key="c.comment_id"
            style="margin-bottom: 8px"
          >
            <div style="font-size: 12px; font-weight: 500">{{ c.nickname }}</div>
            <div>{{ c.content }}</div>
          </div>
        </template>

        <Button danger style="margin-top: 12px" @click="deleteNote(detailNote)">删除这篇笔记</Button>
      </template>
    </Modal>
  </Page>
</template>
