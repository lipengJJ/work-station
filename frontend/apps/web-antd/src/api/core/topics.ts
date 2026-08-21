import { requestClient } from '#/api/request';

// 热点聚合 · 主题订阅与 AI 报告模块：/api/hotlist/topics* 与 /api/hotlist/reports* 的前端适配层。
export namespace TopicsApi {
  export type DigestStrategy = 'simple' | 'two_stage' | 'funnel';
  export type DigestPeriod = 'daily' | 'weekly';
  export type ReportStatus = 'pending' | 'running' | 'success' | 'failed';

  export interface Topic {
    id: number;
    name: string;
    slug: string;
    description: string;
    enabled: boolean;
    sort_order: number;
    skill_key: string;
    template_key: null | string;
    extra_question: string;
    digest_strategy: DigestStrategy;
    digest_period: DigestPeriod;
    digest_cron: string;
    max_items: number;
    shortlist_size: number;
    fulltext_size: number;
    compare_with_previous: boolean;
    publish_enabled: boolean;
    publish_formats: string[];
    // 报告定时推送
    report_notify_enabled: boolean;
    report_notify_channel_ids: number[];
    report_notify_time_start: null | string;
    report_notify_time_end: null | string;
    // 实时命中推送
    hit_notify_enabled: boolean;
    hit_notify_channel_ids: number[];
    hit_notify_time_start: null | string;
    hit_notify_time_end: null | string;
    hit_notify_frequency: 'realtime' | '1h' | '6h' | '12h' | 'daily';
    hit_notify_only_on_hit: boolean;
    hit_notify_pending_hits: number;
    hit_notify_pending_since: null | string;
    created_at: null | string;
    updated_at: null | string;
    enabled_source_count: number;
  }

  export interface TopicParams {
    name: string;
    slug?: string;
    description?: string;
    enabled?: boolean;
    sort_order?: number;
    skill_key?: string;
    template_key?: null | string;
    extra_question?: string;
    digest_strategy?: DigestStrategy;
    digest_period?: DigestPeriod;
    digest_cron?: string;
    max_items?: number;
    shortlist_size?: number;
    fulltext_size?: number;
    compare_with_previous?: boolean;
    publish_enabled?: boolean;
    publish_formats?: string[];
    // 报告定时推送
    report_notify_enabled?: boolean;
    report_notify_channel_ids?: number[];
    report_notify_time_start?: null | string;
    report_notify_time_end?: null | string;
    // 实时命中推送
    hit_notify_enabled?: boolean;
    hit_notify_channel_ids?: number[];
    hit_notify_time_start?: null | string;
    hit_notify_time_end?: null | string;
    hit_notify_frequency?: 'realtime' | '1h' | '6h' | '12h' | 'daily';
    hit_notify_only_on_hit?: boolean;
    hit_notify_pending_hits?: number;
    hit_notify_pending_since?: null | string;
  }

  export interface TopicSource {
    id: string;
    name: string;
    source_kind: string;
    adapter: string;
    cron_expr: string;
    enabled: boolean;
    last_status: '' | 'failed' | 'success';
    last_error: string;
    consecutive_failures: number;
    fail_count: number;
    last_success_at: null | string;
    total_fetched: number;
    topic_enabled: boolean;
    imported_from: string;
    hit_count_7d: number;
  }

  export interface OpmlImportResult {
    created: string[];
    reused: string[];
    skipped: number;
    source_ids: string[];
    detail: string;
  }

  export interface Report {
    id: number;
    topic_id: number;
    period_key: string;
    period_start: null | string;
    period_end: null | string;
    status: ReportStatus;
    summary: string;
    content_md: string;
    highlights: string[];
    item_ids: number[];
    candidate_ids: number[];
    item_count: number;
    source_count: number;
    strategy: string;
    skill_key: string;
    template_key: null | string;
    model: string;
    prompt_tokens: number;
    completion_tokens: number;
    ai_call_count: number;
    publish_status: '' | 'success' | 'failed';
    publish_urls: Record<string, string>;
    published_at: null | string;
    error: string;
    created_at: null | string;
  }

  export interface ReportPage {
    reports: Report[];
    total: number;
    page: number;
    page_size: number;
  }

  export interface ReportItemRef {
    id: number;
    title: string;
    url: string;
    source_id: string;
    source_name: string;
    weight: number;
    published_at: null | string;
  }

  export interface ReportDetail extends Report {
    topic_name: string;
    topic_slug: string;
    items: ReportItemRef[];
    coverage: number;
    prev_item_ids: number[];
  }

  export interface Candidate {
    id: number;
    title: string;
    url: string;
    source_id: string;
    source_name: string;
    weight: number;
    published_at: null | string;
  }
}

// ---------------------------------------------------------------- 主题 CRUD ----

export async function listTopicsApi() {
  return requestClient.get<TopicsApi.Topic[]>('/hotlist/topics');
}

export async function getTopicApi(topicId: number) {
  return requestClient.get<TopicsApi.Topic>(`/hotlist/topics/${topicId}`);
}

export async function createTopicApi(body: TopicsApi.TopicParams) {
  return requestClient.post<TopicsApi.Topic>('/hotlist/topics', body);
}

export async function updateTopicApi(topicId: number, body: Partial<TopicsApi.TopicParams>) {
  return requestClient.put<TopicsApi.Topic>(`/hotlist/topics/${topicId}`, body);
}

export async function deleteTopicApi(topicId: number) {
  return requestClient.delete<{ ok: boolean }>(`/hotlist/topics/${topicId}`);
}

// ---------------------------------------------------------------- 源关联 ----

export async function listTopicSourcesApi(topicId: number) {
  return requestClient.get<TopicsApi.TopicSource[]>(`/hotlist/topics/${topicId}/sources`);
}

export async function batchSetTopicSourcesApi(
  topicId: number,
  body: { mode: 'all_on' | 'all_off' | 'set'; source_ids?: string[] },
) {
  return requestClient.put<{ ok: boolean; changed: number; enabled_count: number }>(
    `/hotlist/topics/${topicId}/sources`,
    body,
  );
}

export async function importOpmlApi(topicId: number, body: { opml_text?: string; opml_url?: string }) {
  return requestClient.post<TopicsApi.OpmlImportResult>(`/hotlist/topics/${topicId}/sources/import-opml`, body);
}

export async function disableStaleSourcesApi(topicId: number) {
  return requestClient.post<{ ok: boolean; disabled: number }>(`/hotlist/topics/${topicId}/sources/disable-stale`);
}

export async function detachTopicSourceApi(topicId: number, sourceId: string) {
  return requestClient.delete<{ ok: boolean }>(`/hotlist/topics/${topicId}/sources/${sourceId}`);
}

// ---------------------------------------------------------------- 报告 ----

export async function listTopicReportsApi(topicId: number, params: { page?: number; page_size?: number } = {}) {
  return requestClient.get<TopicsApi.ReportPage>(`/hotlist/topics/${topicId}/reports`, { params });
}

export async function generateReportApi(
  topicId: number,
  body: { period_key?: string; strategy?: string; max_items?: number } = {},
) {
  return requestClient.post<{ triggered: boolean; message: string }>(
    `/hotlist/topics/${topicId}/reports/generate`,
    body,
  );
}

export async function getReportApi(reportId: number) {
  return requestClient.get<TopicsApi.ReportDetail>(`/hotlist/reports/${reportId}`);
}

export async function getReportCandidatesApi(reportId: number) {
  return requestClient.get<{ total_unreferenced: number; sampled: number; items: TopicsApi.Candidate[] }>(
    `/hotlist/reports/${reportId}/candidates`,
  );
}

export async function publishReportApi(reportId: number) {
  return requestClient.post<{ ok: boolean; urls?: Record<string, string>; error?: string }>(
    `/hotlist/reports/${reportId}/publish`,
  );
}

export async function notifyReportApi(reportId: number) {
  return requestClient.post<{ ok: boolean; message: string }>(`/hotlist/reports/${reportId}/notify`);
}
