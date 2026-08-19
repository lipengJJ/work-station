import { requestClient } from '#/api/request';

// 消息通知：系统设置 > 消息通知 页面的 API 适配层（多通道化）。
// 后端接口统一挂在 /api/notify 下，走同一套 JWT 鉴权。
export namespace NotifyApi {
  export interface NotificationConfig {
    id: number;
    channel: string;
    remark: string;
    webhook_url: string;
    sendkey: string;
    token: string;
    enabled: boolean;
    mention_all: boolean;
    smtp_host: string;
    smtp_port: number;
    smtp_user: string;
    smtp_password: string;
    smtp_use_ssl: boolean;
    email_to: string;
    created_at: string;
    updated_at: string;
  }

  export interface NotificationConfigIn {
    channel?: string;
    remark: string;
    webhook_url: string;
    sendkey: string;
    token: string;
    enabled: boolean;
    mention_all: boolean;
    smtp_host?: string;
    smtp_port?: number;
    smtp_user?: string;
    smtp_password?: string;
    smtp_use_ssl?: boolean;
    email_to?: string;
  }

  /** 通道配置弹窗的字段定义（数据驱动渲染） */
  export interface ChannelFieldDef {
    key: string;
    label: string;
    type: 'text' | 'password' | 'textarea' | 'switch';
    mono?: boolean;
    placeholder?: null | string;
    extra?: null | string;
  }

  /** 通道目录项：元信息 + 实时配置状态（其他模块查询可用通知方式的公共入口） */
  export interface ChannelInfo {
    channel: string;
    label: string;
    icon: string;
    description: string;
    configured: boolean;
    enabled: boolean;
    summary: string;
    capabilities: string[];
    fields: ChannelFieldDef[];
    not_implemented: boolean;
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

/** 通道目录：全部已注册通道 + 配置/启用状态（前端通道列表 / 全局发送组件的数据源） */
export async function getNotifyChannelsApi() {
  return requestClient.get<{ channels: NotifyApi.ChannelInfo[] }>('/notify/channels');
}

/** 全部通道配置 */
export async function listNotifyConfigsApi() {
  return requestClient.get<NotifyApi.NotificationConfig[]>('/notify/configs');
}

/** 单通道配置（未配置返回默认值） */
export async function getNotifyConfigApi(channel: string) {
  return requestClient.get<NotifyApi.NotificationConfig>(`/notify/config/${channel}`);
}

/** 保存单通道配置（upsert） */
export async function saveNotifyConfigApi(channel: string, body: NotifyApi.NotificationConfigIn) {
  return requestClient.put<NotifyApi.NotificationConfig>(`/notify/config/${channel}`, body);
}

/** 测试发送：channel 可选（不传 = 第一个启用通道） */
export async function createNotifyConfigApi(body: NotifyApi.NotificationConfigIn) {
  return requestClient.post<NotifyApi.NotificationConfig>('/notify/configs', body);
}

export async function updateNotifyConfigApi(id: number, body: NotifyApi.NotificationConfigIn) {
  return requestClient.put<NotifyApi.NotificationConfig>(`/notify/configs/${id}`, body);
}

export async function deleteNotifyConfigApi(id: number) {
  return requestClient.delete<{ success: boolean }>(`/notify/configs/${id}`);
}

export async function testNotifyAllApi() {
  return requestClient.post<{
    success: boolean;
    total: number;
    success_count: number;
    message: string;
    results: { channel: string; remark: string; success: boolean; message: string }[];
  }>('/notify/test');
}

export async function testNotifySendApi(channel?: string, remark = '') {
  return requestClient.post<{
    success: boolean;
    total: number;
    success_count: number;
    message: string;
    results: { channel: string; remark: string; success: boolean; message: string }[];
  }>('/notify/test', channel ? { channel, remark } : {});
}

/** 手动发送：channel 可选（不传 = 第一个启用通道） */
export async function manualNotifySendApi(body: {
  channel?: string;
  title: string;
  content: string;
  msgtype?: string;
}) {
  return requestClient.post<NotifyApi.SendResult>('/notify/send', body);
}

export async function listNotifyLogsApi(page: number, pageSize: number) {
  return requestClient.get<NotifyApi.NotificationLogPage>('/notify/logs', {
    params: { page, page_size: pageSize },
  });
}
