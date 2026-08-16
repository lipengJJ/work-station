import type { RequestResponse } from '@vben/request';

import { useAppConfig } from '@vben/hooks';
import { useAccessStore } from '@vben/stores';

import { requestClient } from '#/api/request';

export namespace XhsApi {
  export interface TokenStatus {
    has_token: boolean;
    preview: null | string;
    updated_at: null | string;
  }

  export interface QrcodeStartResult {
    status: 'error' | 'ok';
    msg?: string;
    qr_id?: string;
    qr_image?: string;
      expires_at: null | string;
  }

  export interface QrcodeStatusResult {
    status: 'expired' | 'pending' | 'scanned' | 'success';
    msg?: string;
    nickname?: string;
  }

  export interface PhoneSendResult {
    success: boolean;
    msg: string;
  }

  export interface PhoneVerifyResult {
    success: boolean;
    msg?: string;
    nickname?: string;
  }

  export interface CollectTaskParams {
    keyword: string;
    require_num: number;
    sort_type_choice: number;
    note_type: number;
    note_time: number;
    note_range: number;
    save_choice: string;
    fetch_comments: boolean;
    max_comments_per_note: null | number;
    comment_interval_seconds: null | number;
    /** 视频下载开关：默认 false（视频只保留地址不下载文件），勾选后随素材一起下载 */
    download_video: boolean;
  }

  export interface CollectTaskFiles {
    excel_files: string[];
    media_file_count: number;
  }

  export interface CollectStats {
    candidate_count: number;
    fetch_failed_count: number;
    low_content_count: number;
    collected_count: number;
    structured_ok_count: number;
    structured_failed_count: number;
  }

  export interface CollectTask {
    id: number;
    keyword: string;
    params: CollectTaskParams;
    status: 'failed' | 'pending' | 'running' | 'success';
    message: null | string;
    note_count: number;
    phase: string;
    progress_current: number;
    progress_total: number;
    created_at: string;
    files: CollectTaskFiles;
    has_preview: boolean;
    has_comments: boolean;
    collect_stats: CollectStats | null;
  }

  export interface Note {
    note_id: string;
    note_url: string;
    note_type: string;
    user_id: string;
    home_url: string;
    nickname: string;
    avatar: string;
    title: string;
    desc: string;
    liked_count: string;
    collected_count: string;
    comment_count: string;
    share_count: string;
    video_cover: null | string;
    video_addr: null | string;
    image_list: string[];
    tags: string[];
    upload_time: string;
    ip_location: string;
  }

  export interface NoteComment {
    comment_id: string;
    note_id: string;
    content: string;
    like_count: number | null;
    nickname: string | null;
    user_id: string | null;
    home_url: string | null;
    parent_comment_id: string;
    create_time: string | null;
  }

  export interface NoteCommentsResult {
    items: NoteComment[];
    total: number;
    page: number;
    page_size: number;
    source: 'table' | 'task_json' | 'none';
  }

  export interface NoteStructured {
    note_id: string;
    category: null | string;
    city: null | string;
    area: null | string;
    summary: null | string;
    key_points: string[];
    topic_tags: string[];
    ext: Record<string, unknown>;
    status: 'failed' | 'ok' | 'skipped_low_content';
    issues: string[];
  }

  export interface Comment {
    note_id: string;
    note_url: string;
    comment_id: string;
    user_id: string;
    home_url: string;
    nickname: string;
    avatar: string;
    content: string;
    show_tags: string[];
    like_count: string;
    upload_time: string;
    ip_location: string;
    pictures: string[];
  }

  export interface PageResult<T> {
    items: T[];
    total: number;
    page: number;
    page_size: number;
  }

  export interface NoteTaskListParams {
    query?: string;
    status?: string;
    page?: number;
    page_size?: number;
  }

  export interface TaskNotesListParams {
    query?: string;
    note_type?: '图集' | '视频';
    date_range?: '7d' | '30d' | '180d';
    page?: number;
    page_size?: number;
  }

  export interface NoteAnalysis {
    id: number;
    project_id: number;
    question: string;
    status: 'failed' | 'running' | 'success';
    result: null | string;
    error: null | string;
    model: string;
    template: null | string;
    feedback: 'down' | 'up' | null;
    created_at: string;
  }

  export interface AnalysisProject {
    id: number;
    name: string;
    note_count: number;
    created_at: string;
  }

  export interface AnalysisTemplate {
    id: string;
    label: string;
    quick_prompts: string[];
  }

  export interface TrackingTaskParams {
    name: string;
    keyword: string;
    require_num: number;
    sort_type_choice: number;
    note_type: number;
    note_time: number;
    note_range: number;
    must_include: string[];
    must_exclude: string[];
    interval_minutes: number;
    enabled: boolean;
    notify_enabled: boolean;
    notify_channel_ids: number[];
    notify_time_start: null | string;
    notify_time_end: null | string;
    notify_frequency: 'daily' | 'realtime' | '1h' | '6h' | '12h';
    notify_only_on_hit: boolean;
  }

  export interface TrackingTask extends TrackingTaskParams {
    id: number;
    status: 'failed' | 'idle' | 'running';
    last_run_at: null | string;
    last_run_message: null | string;
    last_hit_count: number;
    total_hit_count: number;
    next_run_at: null | string;
    created_at: string;
  }

  export interface TrackingHit extends Note {
    _hit_id: number;
  }

  export interface ReportListItem {
    id: number;
    title: string;
    summary: string;
    template: null | string;
    project_id: number;
    project_name: string;
    source_count: number;
    status: string;
    created_at: string;
  }

  export interface ReportSourceNote {
    note_id: string;
    note_url: string;
    note_type: string;
    nickname: string;
    avatar: string;
    title: string;
    desc: string;
    liked_count: string;
    collected_count: string;
    comment_count: string;
    video_cover: null | string;
    image_list: string[];
    upload_time: string;
  }

  export interface ReportDetail {
    id: number;
    title: string;
    question: string;
    result: string;
    template: null | string;
    model: string;
    project_id: number;
    project_name: string;
    source_note_ids: string[];
    source_notes: ReportSourceNote[];
    created_at: string;
  }

  export interface ReportListParams {
    query?: string;
    project_id?: number;
    template?: string;
    sort?: 'created_asc' | 'created_desc';
    page?: number;
    page_size?: number;
  }
}

export async function getXhsTokenApi() {
  return requestClient.get<XhsApi.TokenStatus>('/xhs/token');
}

export async function getXhsTokenFullApi() {
  return requestClient.get<{ cookies: string }>('/xhs/token/full');
}

export async function setXhsTokenApi(cookies: string) {
  return requestClient.post<XhsApi.TokenStatus>('/xhs/token', { cookies });
}

export async function clearXhsTokenApi() {
  return requestClient.delete<XhsApi.TokenStatus>('/xhs/token');
}

export async function startXhsQrcodeLoginApi() {
  return requestClient.post<XhsApi.QrcodeStartResult>('/xhs/login/qrcode/start', undefined, {
    timeout: 60000,
  });
}

export async function pollXhsQrcodeLoginApi(qrId: string) {
  return requestClient.get<XhsApi.QrcodeStatusResult>('/xhs/login/qrcode/status', {
    params: { qr_id: qrId },
  });
}

export async function cancelXhsQrcodeLoginApi(qrId: string) {
  return requestClient.post<{ success: boolean }>('/xhs/login/qrcode/cancel', null, {
    params: { qr_id: qrId },
  });
}

export async function sendXhsPhoneCodeApi(phone: string, zone = '86') {
  return requestClient.post<XhsApi.PhoneSendResult>('/xhs/login/phone/send_code', { phone, zone }, {
    timeout: 60000,
  });
}

export async function verifyXhsPhoneLoginApi(phone: string, code: string, zone = '86') {
  return requestClient.post<XhsApi.PhoneVerifyResult>('/xhs/login/phone/verify', { phone, code, zone }, {
    timeout: 60000,
  });
}

export async function createXhsCollectTaskApi(body: XhsApi.CollectTaskParams) {
  return requestClient.post<XhsApi.CollectTask>('/xhs/collect-tasks', body);
}

export async function listXhsCollectTasksApi() {
  return requestClient.get<XhsApi.CollectTask[]>('/xhs/collect-tasks');
}

export async function deleteXhsCollectTaskApi(taskId: number) {
  return requestClient.delete<{ success: boolean }>(`/xhs/collect-tasks/${taskId}`);
}

/**
 * 在已有主题基础上增量采集：跳过已经采集过的笔记，只补齐 incrementCount 篇新的。
 * 小红书搜索接口没有翻页续搜的游标，后端会"多要一些再本地去重"，实际新增数量
 * 可能少于请求的 incrementCount（该关键词候选已接近用尽时）。
 */
export async function incrementalCollectXhsTaskApi(
  taskId: number,
  incrementCount: number,
  downloadVideo?: boolean,
  fetchComments?: boolean,
) {
  return requestClient.post<XhsApi.CollectTask>(`/xhs/collect-tasks/${taskId}/incremental`, {
    increment_count: incrementCount,
    // 不传（undefined）= 沿用任务原有设置；显式传 = 本次增量覆盖
    download_video: downloadVideo,
    fetch_comments: fetchComments,
  });
}

/** "更新评论"：对任务里还没有评论的笔记补抓评论（后台执行）。 */
export async function fetchMissingCommentsXhsTaskApi(taskId: number) {
  return requestClient.post<{ message: string; stats: { total: number; already_have: number; to_fetch: number } }>(
    `/xhs/collect-tasks/${taskId}/fetch-missing-comments`,
  );
}

export async function deleteXhsNoteApi(taskId: number, noteId: string) {
  return requestClient.delete<XhsApi.CollectTask>(`/xhs/collect-tasks/${taskId}/notes/${noteId}`);
}

export async function deleteXhsNotesApi(taskId: number, noteIds: string[]) {
  return requestClient.delete<XhsApi.CollectTask>(`/xhs/collect-tasks/${taskId}/notes`, {
    data: { note_ids: noteIds },
  });
}

export async function downloadXhsCollectTaskApi(taskId: number, kind: 'archive' | 'comments' | 'excel') {
  const response = await requestClient.download<RequestResponse<Blob>>(
    `/xhs/collect-tasks/${taskId}/download/${kind}`,
    { responseReturn: 'raw' },
  );
  const disposition = (response.headers as Record<string, string>)['content-disposition'] || '';
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const filename = match?.[1] ?? `xhs-task-${taskId}-${kind}`;
  const url = URL.createObjectURL(response.data);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ------------------------------------------------------------- 笔记管理 ----

export async function listXhsNoteTasksApi(params?: XhsApi.NoteTaskListParams) {
  return requestClient.get<XhsApi.PageResult<XhsApi.CollectTask>>('/xhs/notes', { params });
}

export async function processXhsTaskAiDataApi(taskId: number) {
  return requestClient.post<{ message: string; pending_count: number; started: boolean }>(
    `/xhs/notes/tasks/${taskId}/ai-process`,
  );
}

export async function getXhsNoteTaskNotesApi(taskId: number, params?: XhsApi.TaskNotesListParams) {
  return requestClient.get<XhsApi.PageResult<XhsApi.Note>>(`/xhs/notes/${taskId}`, { params });
}

/**
 * 强制重新抓取一篇笔记的最新数据，覆盖全局去重缓存（点赞/评论数等互动数据会过期，
 * 缓存默认 3 天自动允许刷新，这个接口是手动提前触发）。只对已经进过缓存的笔记有效。
 */
export async function refreshXhsNoteApi(noteId: string) {
  return requestClient.post<XhsApi.Note>(`/xhs/notes/${noteId}/refresh`);
}

/** 查看 AI 结构化预处理结果（智谱 GLM），笔记还没处理过时后端返回 404。 */
export async function getXhsNoteStructuredApi(noteId: string) {
  return requestClient.get<XhsApi.NoteStructured>(`/xhs/notes/${noteId}/structured`);
}

/** 按笔记查看已获取的评论（笔记列表"评论"按钮，表数据优先、旧任务 JSON 兜底）。 */
export async function getXhsNoteCommentsApi(
  noteId: string,
  params?: { page?: number; page_size?: number },
) {
  return requestClient.get<XhsApi.NoteCommentsResult>(`/xhs/notes/${noteId}/comments`, { params });
}

// ------------------------------------------------------------- AI 分析 ----

export async function listXhsAnalysisProjectsApi() {
  return requestClient.get<XhsApi.AnalysisProject[]>('/xhs/analysis-projects');
}

export async function createXhsAnalysisProjectApi(name: string) {
  return requestClient.post<XhsApi.AnalysisProject>('/xhs/analysis-projects', { name });
}

// RequestClient 没有内置 patch() 方法（只有 get/post/put/delete），走通用的 request() 自己指定 method
export async function renameXhsAnalysisProjectApi(projectId: number, name: string) {
  return requestClient.request<XhsApi.AnalysisProject>(`/xhs/analysis-projects/${projectId}`, {
    data: { name },
    method: 'PATCH',
  });
}

export async function deleteXhsAnalysisProjectApi(projectId: number) {
  return requestClient.delete<{ success: boolean }>(`/xhs/analysis-projects/${projectId}`);
}

export async function listXhsAnalysisTemplatesApi() {
  return requestClient.get<XhsApi.AnalysisTemplate[]>('/xhs/analysis-templates');
}

export async function listXhsProjectNotesApi(projectId: number) {
  return requestClient.get<XhsApi.Note[]>(`/xhs/analysis-projects/${projectId}/notes`);
}

export async function addXhsProjectNotesApi(projectId: number, taskId: number, noteIds: string[]) {
  return requestClient.post<XhsApi.Note[]>(`/xhs/analysis-projects/${projectId}/notes`, {
    task_id: taskId,
    note_ids: noteIds,
  });
}

export async function removeXhsProjectNoteApi(projectId: number, noteId: string) {
  return requestClient.delete<{ success: boolean }>(
    `/xhs/analysis-projects/${projectId}/notes/${noteId}`,
  );
}

export async function listXhsProjectAnalysesApi(projectId: number) {
  return requestClient.get<XhsApi.NoteAnalysis[]>(`/xhs/analysis-projects/${projectId}/analyses`);
}

export async function deleteXhsProjectAnalysisApi(projectId: number, analysisId: number) {
  return requestClient.delete<{ success: boolean }>(
    `/xhs/analysis-projects/${projectId}/analyses/${analysisId}`,
  );
}

export async function setXhsProjectAnalysisFeedbackApi(
  projectId: number,
  analysisId: number,
  feedback: 'down' | 'up' | null,
) {
  return requestClient.request<XhsApi.NoteAnalysis>(
    `/xhs/analysis-projects/${projectId}/analyses/${analysisId}`,
    { data: { feedback }, method: 'PATCH' },
  );
}

export interface StreamProjectAnalysisHandlers {
  onDelta: (delta: string) => void;
  onError: (error: string) => void;
  onEnd: () => void;
}

/**
 * 对某个 AI 分析项目当前选中的笔记发起一次分析，SSE 流式返回结论增量。
 * 缓冲拼接逻辑和 streamChatApi 一致：fetch 的 chunk 边界和 SSE 事件边界不对齐，按 "\n\n" 拆。
 */
export interface StreamProjectAnalysisOptions {
  noteIds?: string[];
  template?: string;
  /** 传了就走通用 Skill Runtime（笔记作为业务上下文注入），忽略 template 字段 */
  skillKey?: string;
  skillTemplateKey?: string;
  /** 只在 skillKey 有值时生效，默认关闭避免意外触发联网工具调用 */
  enableSearch?: boolean;
}

export async function streamXhsProjectAnalysisApi(
  projectId: number,
  question: string,
  handlers: StreamProjectAnalysisHandlers,
  options?: StreamProjectAnalysisOptions,
  signal?: AbortSignal,
) {
  let buffer = '';
  await requestClient.postSSE(
    `/xhs/analysis-projects/${projectId}/analyses`,
    {
      question,
      note_ids: options?.noteIds,
      template: options?.template,
      skill_key: options?.skillKey,
      skill_template_key: options?.skillTemplateKey,
      enable_search: options?.enableSearch ?? false,
    },
    {
      headers: { 'Content-Type': 'application/json' },
      signal,
      onMessage: (raw: string) => {
        buffer += raw;
        const events = buffer.split('\n\n');
        buffer = events.pop() ?? '';
        for (const event of events) {
          const line = event.trim();
          if (!line.startsWith('data:')) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            const parsed = JSON.parse(payload) as {
              delta?: string;
              done?: boolean;
              error?: string;
            };
            if (parsed.error) {
              handlers.onError(parsed.error);
            } else if (parsed.delta) {
              handlers.onDelta(parsed.delta);
            }
          } catch {
            // 忽略解析失败的单个事件，不影响后续流
          }
        }
      },
      onEnd: handlers.onEnd,
    },
  );
}

// ------------------------------------------------------------- 分析报告 ----

export async function saveXhsAnalysisReportApi(
  projectId: number,
  analysisId: number,
  title: string,
  noteIds: string[],
) {
  return requestClient.post<XhsApi.ReportListItem>(
    `/xhs/analysis-projects/${projectId}/analyses/${analysisId}/report`,
    { title, note_ids: noteIds },
  );
}

export async function saveXhsCombinedReportApi(
  projectId: number,
  title: string,
  noteIds: string[],
  analysisIds: number[],
) {
  return requestClient.post<XhsApi.ReportListItem>(
    `/xhs/analysis-projects/${projectId}/report`,
    { title, note_ids: noteIds, analysis_ids: analysisIds },
  );
}

export async function appendXhsReportApi(reportId: number, noteIds: string[], analysisIds: number[]) {
  return requestClient.put<XhsApi.ReportListItem>(`/xhs/reports/${reportId}/append`, {
    note_ids: noteIds,
    analysis_ids: analysisIds,
  });
}

export async function listXhsReportsApi(params?: XhsApi.ReportListParams) {
  return requestClient.get<XhsApi.PageResult<XhsApi.ReportListItem>>('/xhs/reports', { params });
}

export async function getXhsReportApi(reportId: number) {
  return requestClient.get<XhsApi.ReportDetail>(`/xhs/reports/${reportId}`);
}

export async function deleteXhsReportApi(reportId: number) {
  return requestClient.delete<{ success: boolean }>(`/xhs/reports/${reportId}`);
}

// ------------------------------------------------------------- 追踪任务 ----

export async function listXhsTrackingTasksApi() {
  return requestClient.get<XhsApi.TrackingTask[]>('/xhs/tracking-tasks');
}

export async function createXhsTrackingTaskApi(body: XhsApi.TrackingTaskParams) {
  return requestClient.post<XhsApi.TrackingTask>('/xhs/tracking-tasks', body);
}

export async function updateXhsTrackingTaskApi(taskId: number, body: XhsApi.TrackingTaskParams) {
  return requestClient.put<XhsApi.TrackingTask>(`/xhs/tracking-tasks/${taskId}`, body);
}

export async function deleteXhsTrackingTaskApi(taskId: number) {
  return requestClient.delete<{ success: boolean }>(`/xhs/tracking-tasks/${taskId}`);
}

export async function runXhsTrackingTaskNowApi(taskId: number) {
  return requestClient.post<{ success: boolean }>(`/xhs/tracking-tasks/${taskId}/run-now`);
}

export async function listXhsTrackingHitsApi(taskId: number) {
  return requestClient.get<XhsApi.TrackingHit[]>(`/xhs/tracking-tasks/${taskId}/hits`);
}

export async function deleteXhsTrackingHitApi(taskId: number, hitId: number) {
  return requestClient.delete<{ success: boolean }>(`/xhs/tracking-tasks/${taskId}/hits/${hitId}`);
}

export interface XhsMediaRef {
  noteId: string;
  kind: 'cover' | 'image' | 'video';
  /** kind === 'image' 时，图集里的第几张（从 0 开始） */
  index?: number;
}

/**
 * 小红书图片/视频代理地址。<img>/<video> 的 src 属性没法带 Authorization 请求头，
 * 只有这一个接口允许把访问令牌附在查询参数 token= 上（后端 get_current_user_for_media
 * 里同时接受请求头或查询参数）。
 *
 * 传了 media 的话，后端会优先找本地已下载的素材文件返回——小红书 CDN 的图片/视频
 * URL 实测采集完约一天后就会过期（返回 403，不是跳到新地址），不传 media 就只能
 * 现场请求原始 URL，过期了就是加载失败（老代码 / 没有 note 上下文时的兜底行为）。
 */
export function buildXhsMediaProxyUrl(url: string, media?: XhsMediaRef): string {
  if (!url) return '';
  const { apiURL } = useAppConfig(import.meta.env, import.meta.env.PROD);
  const accessStore = useAccessStore();
  const params = new URLSearchParams({ url });
  if (accessStore.accessToken) {
    params.set('token', accessStore.accessToken);
  }
  if (media) {
    params.set('note_id', media.noteId);
    params.set('kind', media.kind);
    if (media.index !== undefined) params.set('index', String(media.index));
  }
  return `${apiURL}/xhs/proxy/media?${params.toString()}`;
}
