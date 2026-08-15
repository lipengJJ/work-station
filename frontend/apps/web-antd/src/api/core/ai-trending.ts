import { requestClient } from '#/api/request';

export namespace AiTrendingApi {
  export type TrendingSourceId =
    | 'hn'
    | 'github'
    | 'arxiv'
    | 'hf_models'
    | 'hf_papers'
    | 'infoq'
    | 'kr36';

  export type TrendingCategory = 'news' | 'project' | 'paper' | 'model';

  export interface TrendingItem {
    id: number;
    source: TrendingSourceId;
    title: string;
    url: string;
    summary: string;
    heat_score: number;
    category: TrendingCategory;
    tags: string[];
    heat_meta: Record<string, number | string>;
    published_at: null | string;
    fetched_at: string;
    created_at: string;
  }

  export interface TrendingItemPage {
    items: TrendingItem[];
    total: number;
    page: number;
    page_size: number;
  }

  export interface SourceStatus {
    source_id: string;
    source_name: string;
    category_type: string;
    last_fetched_at: null | string;
    last_status: '' | 'failed' | 'success';
    last_error: string;
    consecutive_failures: number;
    fail_count: number;
    last_success_at: null | string;
    total_fetched: number;
  }

  export interface RefreshResult {
    triggered: boolean;
    message: string;
  }

  export interface ListItemsParams {
    category?: string;
    page?: number;
    page_size?: number;
    sort?: 'heat' | 'time';
    source?: string;
  }

  export interface PushConfig {
    enabled: boolean;
    webhook_url: string;
    webhook_secret_set: boolean;
    keyword: null | string;
    push_time: string;
    top_n: number;
    summary_prompt: null | string;
  }

  export interface PushConfigUpdate {
    enabled: boolean;
    webhook_url: string;
    webhook_secret?: null | string;
    keyword?: null | string;
    push_time?: string;
    top_n?: number;
    summary_prompt?: null | string;
  }

  export type PushLogStatus = 'success' | 'degraded' | 'failed';

  export interface PushLog {
    id: number;
    pushed_at: string;
    status: PushLogStatus;
    error: string;
    items_count: number;
    summary_preview: string;
  }

  export interface PushTestParams {
    enabled?: boolean;
    webhook_url?: string;
    webhook_secret?: null | string;
    keyword?: null | string;
    push_time?: string;
    top_n?: number;
    summary_prompt?: null | string;
  }

  // ------------------------------------------------------------ 主题跟踪 ----
  export type TopicStatus = 'idle' | 'running' | 'failed';
  export type PushChannel = 'wecom' | 'dingtalk' | 'feishu' | 'email';
  export type PushFrequency = 'daily';

  export interface TopicPushConfig {
    enabled: boolean;
    channel: PushChannel;
    frequency: PushFrequency;
    time: string;
  }

  export interface Topic {
    id: number;
    name: string;
    keywords: string[];
    interval_minutes: number;
    enabled: boolean;
    status: TopicStatus;
    last_run_at: null | string;
    last_run_message: null | string;
    last_item_count: number;
    hit_count: number;
    next_run_at: null | string;
    push: TopicPushConfig;
    created_at: string;
  }

  export interface TopicCreateParams {
    name: string;
    keywords: string[];
    interval_minutes?: number;
    enabled?: boolean;
    push?: TopicPushConfig;
  }

  export interface TopicUpdateParams {
    name?: string;
    keywords?: string[];
    interval_minutes?: number;
    enabled?: boolean;
    push?: TopicPushConfig;
  }

  export interface TopicItemsParams {
    sort?: 'heat' | 'time';
    page?: number;
    page_size?: number;
  }

  export interface TopicHitPage {
    items: TrendingItem[];
    total: number;
    page: number;
    page_size: number;
  }
}

/** 热点条目分页列表（来源/类型筛选 + 热度/时间排序） */
export async function listTrendingItemsApi(params: AiTrendingApi.ListItemsParams) {
  return requestClient.get<AiTrendingApi.TrendingItemPage>('/ai-trending/items', {
    params,
  });
}

/** 来源健康状态列表 */
export async function getTrendingSourcesApi() {
  return requestClient.get<AiTrendingApi.SourceStatus[]>('/ai-trending/sources');
}

/** 手动触发全量抓取（10 分钟限频 1 次，异步执行） */
export async function refreshTrendingApi() {
  return requestClient.post<AiTrendingApi.RefreshResult>('/ai-trending/refresh');
}

/** 定时推送配置（webhook_url 掩码、secret 只回 _set） */
export async function getPushConfigApi() {
  return requestClient.get<AiTrendingApi.PushConfig>('/ai-trending/push/config');
}

/** 保存定时推送配置（保存后后端自动重调度每日 cron） */
export async function updatePushConfigApi(body: AiTrendingApi.PushConfigUpdate) {
  return requestClient.put<AiTrendingApi.PushConfig>('/ai-trending/push/config', body);
}

/** 最近一次推送记录（无记录时返回 null） */
export async function getLatestPushLogApi() {
  return requestClient.get<AiTrendingApi.PushLog | null>('/ai-trending/push/latest');
}

/** 测试推送（5 分钟限频 1 次；失败也返回 log 行，status=failed） */
export async function testPushApi(body: AiTrendingApi.PushTestParams = {}) {
  return requestClient.post<AiTrendingApi.PushLog>('/ai-trending/push/test', body);
}

// ------------------------------------------------------------ 主题跟踪 ----

/** 主题列表（带 hit_count / next_run_at） */
export async function listTopicsApi() {
  return requestClient.get<AiTrendingApi.Topic[]>('/ai-trending/topics');
}

/** 创建主题（enabled 时后端自动注册 interval job） */
export async function createTopicApi(body: AiTrendingApi.TopicCreateParams) {
  return requestClient.post<AiTrendingApi.Topic>('/ai-trending/topics', body);
}

/** 主题详情 */
export async function getTopicApi(topicId: number) {
  return requestClient.get<AiTrendingApi.Topic>(`/ai-trending/topics/${topicId}`);
}

/** 更新主题（全可选，只覆盖传入字段） */
export async function updateTopicApi(topicId: number, body: AiTrendingApi.TopicUpdateParams) {
  return requestClient.put<AiTrendingApi.Topic>(`/ai-trending/topics/${topicId}`, body);
}

/** 删除主题（注销 job + 级联清空命中记录） */
export async function deleteTopicApi(topicId: number) {
  return requestClient.delete<{ success: boolean }>(`/ai-trending/topics/${topicId}`);
}

/** 立即抓取（每主题 60s 限频 + running 防重入，异步执行） */
export async function runTopicNowApi(topicId: number) {
  return requestClient.post<{ success: boolean; message: string }>(
    `/ai-trending/topics/${topicId}/run-now`,
  );
}

/** 主题命中列表（join hits+items 分页；sort=heat|time） */
export async function listTopicItemsApi(topicId: number, params: AiTrendingApi.TopicItemsParams) {
  return requestClient.get<AiTrendingApi.TopicHitPage>(
    `/ai-trending/topics/${topicId}/items`,
    { params },
  );
}

/** 主题推送配置（channel/frequency/time） */
export async function getTopicPushConfigApi(topicId: number) {
  return requestClient.get<AiTrendingApi.TopicPushConfig>(
    `/ai-trending/topics/${topicId}/push-config`,
  );
}

/** 保存主题推送配置（仅落库，不触发真实发送） */
export async function updateTopicPushConfigApi(
  topicId: number,
  body: AiTrendingApi.TopicPushConfig,
) {
  return requestClient.put<AiTrendingApi.TopicPushConfig>(
    `/ai-trending/topics/${topicId}/push-config`,
    body,
  );
}
