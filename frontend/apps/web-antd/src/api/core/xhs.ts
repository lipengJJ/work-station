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
  }

  export interface QrcodeStatusResult {
    status: 'expired' | 'pending' | 'success';
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
  }

  export interface CollectTaskFiles {
    excel_files: string[];
    media_file_count: number;
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

  export interface PreviewResult {
    notes: Note[];
    comments: Comment[];
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
  return requestClient.post<XhsApi.QrcodeStartResult>('/xhs/login/qrcode/start');
}

export async function pollXhsQrcodeLoginApi(qrId: string) {
  return requestClient.get<XhsApi.QrcodeStatusResult>('/xhs/login/qrcode/status', {
    params: { qr_id: qrId },
  });
}

export async function sendXhsPhoneCodeApi(phone: string, zone = '86') {
  return requestClient.post<XhsApi.PhoneSendResult>('/xhs/login/phone/send_code', { phone, zone });
}

export async function verifyXhsPhoneLoginApi(phone: string, code: string, zone = '86') {
  return requestClient.post<XhsApi.PhoneVerifyResult>('/xhs/login/phone/verify', { phone, code, zone });
}

export async function createXhsCollectTaskApi(body: XhsApi.CollectTaskParams) {
  return requestClient.post<XhsApi.CollectTask>('/xhs/collect-tasks', body);
}

export async function listXhsCollectTasksApi() {
  return requestClient.get<XhsApi.CollectTask[]>('/xhs/collect-tasks');
}

export async function getXhsCollectTaskApi(taskId: number) {
  return requestClient.get<XhsApi.CollectTask>(`/xhs/collect-tasks/${taskId}`);
}

export async function deleteXhsCollectTaskApi(taskId: number) {
  return requestClient.delete<{ success: boolean }>(`/xhs/collect-tasks/${taskId}`);
}

export async function getXhsCollectTaskPreviewApi(taskId: number) {
  return requestClient.get<XhsApi.PreviewResult>(`/xhs/collect-tasks/${taskId}/preview`);
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

/**
 * 小红书图片/视频代理地址。<img>/<video> 的 src 属性没法带 Authorization 请求头，
 * 只有这一个接口允许把访问令牌附在查询参数 token= 上（后端 get_current_user_for_media
 * 里同时接受请求头或查询参数）。
 */
export function buildXhsMediaProxyUrl(url: string): string {
  if (!url) return '';
  const { apiURL } = useAppConfig(import.meta.env, import.meta.env.PROD);
  const accessStore = useAccessStore();
  const params = new URLSearchParams({ url });
  if (accessStore.accessToken) {
    params.set('token', accessStore.accessToken);
  }
  return `${apiURL}/xhs/proxy/media?${params.toString()}`;
}
