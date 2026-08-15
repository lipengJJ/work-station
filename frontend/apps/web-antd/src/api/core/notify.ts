import { requestClient } from '#/api/request';

// 消息通知：系统设置 > 消息通知 页面的 API 适配层。
// 后端接口统一挂在 /api/notify 下，走同一套 JWT 鉴权。
export namespace NotifyApi {
  export interface NotificationConfig {
    id: number;
    channel: string;
    webhook_url: string;
    enabled: boolean;
    mention_all: boolean;
    created_at: string;
    updated_at: string;
  }

  export interface NotificationConfigIn {
    channel?: string;
    webhook_url: string;
    enabled: boolean;
    mention_all: boolean;
  }

  export interface NotificationLog {
    id: number;
    channel: string;
    title: string;
    content: null | string;
    status: 'failed' | 'success';
    error_msg: null | string;
    created_at: string;
  }

  export interface NotificationLogPage {
    items: NotificationLog[];
    total: number;
    page: number;
    page_size: number;
  }

  export interface SendResult {
    success: boolean;
    message: string;
  }
}

export async function getNotifyConfigApi() {
  return requestClient.get<NotifyApi.NotificationConfig>('/notify/config');
}

export async function saveNotifyConfigApi(body: NotifyApi.NotificationConfigIn) {
  return requestClient.put<NotifyApi.NotificationConfig>('/notify/config', body);
}

export async function testNotifySendApi() {
  return requestClient.post<NotifyApi.SendResult>('/notify/test');
}

export async function manualNotifySendApi(body: { title: string; content: string; msgtype?: string }) {
  return requestClient.post<NotifyApi.SendResult>('/notify/send', body);
}

export async function listNotifyLogsApi(page: number, pageSize: number) {
  return requestClient.get<NotifyApi.NotificationLogPage>('/notify/logs', {
    params: { page, page_size: pageSize },
  });
}
