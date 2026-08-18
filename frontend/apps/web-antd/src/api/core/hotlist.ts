import { requestClient } from '#/api/request';

// 热点聚合模块：/api/hotlist/* 的前端适配层。
export namespace HotlistApi {
  export type SourceKind = 'hotlist' | 'tech';
  export type SourceStatus = '' | 'failed' | 'success';

  export interface Source {
    id: string;
    name: string;
    source_kind: SourceKind;
    adapter: string;
    expected_domain: string;
    decay_half_life_hours: number;
    cron_expr: string;
    enabled: boolean;
    sort_order: number;
    last_fetched_at: null | string;
    last_status: SourceStatus;
    last_error: string;
    consecutive_failures: number;
    fail_count: number;
    last_success_at: null | string;
    total_fetched: number;
  }

  export interface SourceUpdateParams {
    name?: string;
    enabled?: boolean;
    cron_expr?: string;
    expected_domain?: string;
    decay_half_life_hours?: number;
    sort_order?: number;
  }

  export interface SourceCreateParams {
    id: string;
    name: string;
    adapter: string;
    adapter_params: Record<string, unknown>;
    source_kind?: SourceKind;
    expected_domain?: string;
    decay_half_life_hours?: number;
    cron_expr?: string;
    enabled?: boolean;
    sort_order?: number;
  }

  export interface Item {
    id: number;
    source_id: string;
    title: string;
    url: string;
    mobile_url: string;
    summary: string;
    stat_date: string;
    rank: number;
    best_rank: number;
    ranks_json: number[];
    first_crawl_time: null | string;
    last_crawl_time: null | string;
    crawl_count: number;
    published_at: null | string;
    metrics: Record<string, number | string>;
    weight: number;
    hit_rules: string[];
  }

  export interface ItemPage {
    items: Item[];
    total: number;
    page: number;
    page_size: number;
  }

  export interface RankPoint {
    rank: number;
    crawl_time: string;
  }

  export interface ItemDetail {
    item: Item;
    history: RankPoint[];
  }

  export type SortField = 'rank' | 'time' | 'weight';

  export interface ListItemsParams {
    source_id?: string;
    source_kind?: SourceKind | '';
    stat_date?: string;
    sort?: SortField;
    hit_only?: boolean;
    page?: number;
    page_size?: number;
  }

  export interface CrawlResult {
    triggered: boolean;
    message: string;
  }

  // -------------------------------------------------------------- 频率词规则 ----
  export interface Word {
    word: string;
    is_regex: boolean;
    display_name?: null | string;
  }

  export type RuleType = 'global_filter' | 'group';

  export interface Rule {
    id: number;
    rule_type: RuleType;
    display_name: string;
    normal_words: Word[];
    required_words: Word[];
    exclude_words: Word[];
    source_ids: string[];
    max_count: number;
    enabled: boolean;
    sort_order: number;
    notify_enabled: boolean;
    notify_channel_ids: number[];
    notify_time_start: null | string;
    notify_time_end: null | string;
    notify_frequency: string;
    notify_only_on_hit: boolean;
    created_at: null | string;
    updated_at: null | string;
  }

  export interface RuleParams {
    display_name?: string;
    normal_words?: Word[];
    required_words?: Word[];
    exclude_words?: Word[];
    source_ids?: string[];
    max_count?: number;
    enabled?: boolean;
    sort_order?: number;
    notify_enabled?: boolean;
    notify_channel_ids?: number[];
    notify_time_start?: null | string;
    notify_time_end?: null | string;
    notify_frequency?: string;
    notify_only_on_hit?: boolean;
  }

  export interface GlobalFilterParams {
    word: string;
    enabled?: boolean;
    sort_order?: number;
  }

  export interface RuleImportResult {
    created_groups: number;
    created_global_filters: number;
  }

  export interface RulePreviewParams {
    normal_words?: Word[];
    required_words?: Word[];
    exclude_words?: Word[];
    source_ids?: string[];
    sample_limit?: number;
  }

  export interface RulePreviewResult {
    matched_count: number;
    samples: Item[];
  }

  // -------------------------------------------------------------- 摘要 ----
  export type DigestMode = 'current' | 'daily' | 'incremental';

  export interface DigestGroup {
    rule_id: null | number;
    display_name: string;
    items: Item[];
  }

  export interface Digest {
    mode: DigestMode;
    stat_date: string;
    total_items: number;
    groups: DigestGroup[];
  }

  export interface DigestParams {
    mode: DigestMode;
    stat_date?: string;
    source_ids?: string;
  }
}

/** 源列表 + 健康状态 */
export async function listHotlistSourcesApi() {
  return requestClient.get<HotlistApi.Source[]>('/hotlist/sources');
}

/** 更新源（改名 / 开关 / cron / 期望域名，全字段可选） */
export async function updateHotlistSourceApi(sourceId: string, body: HotlistApi.SourceUpdateParams) {
  return requestClient.put<HotlistApi.Source>(`/hotlist/sources/${sourceId}`, body);
}

/** 新建自定义源（主要给 RSS 用） */
export async function createHotlistSourceApi(body: HotlistApi.SourceCreateParams) {
  return requestClient.post<HotlistApi.Source>('/hotlist/sources', body);
}

/** 删除源 */
export async function deleteHotlistSourceApi(sourceId: string) {
  return requestClient.delete<{ ok: boolean }>(`/hotlist/sources/${sourceId}`);
}

/** 条目分页列表（来源 / 源类型 / 日期筛选 + 权重/榜位/时间排序） */
export async function listHotlistItemsApi(params: HotlistApi.ListItemsParams) {
  return requestClient.get<HotlistApi.ItemPage>('/hotlist/items', { params });
}

/** 条目详情 + 榜位时间线（含脱榜段） */
export async function getHotlistItemDetailApi(itemId: number) {
  return requestClient.get<HotlistApi.ItemDetail>(`/hotlist/items/${itemId}`);
}

/** 手动触发全量抓取（10 分钟限频 1 次，异步执行） */
export async function triggerHotlistCrawlApi() {
  return requestClient.post<HotlistApi.CrawlResult>('/hotlist/crawl');
}

// -------------------------------------------------------------- 频率词规则 ----

/** 规则列表（词组规则 + 全局过滤词，混在一起靠 rule_type 区分） */
export async function listHotlistRulesApi() {
  return requestClient.get<HotlistApi.Rule[]>('/hotlist/rules');
}

/** 新建词组规则 */
export async function createHotlistRuleApi(body: HotlistApi.RuleParams) {
  return requestClient.post<HotlistApi.Rule>('/hotlist/rules', body);
}

/** 更新词组规则（全字段可选，覆盖式保存） */
export async function updateHotlistRuleApi(ruleId: number, body: HotlistApi.RuleParams) {
  return requestClient.put<HotlistApi.Rule>(`/hotlist/rules/${ruleId}`, body);
}

/** 删除规则（词组或全局过滤词） */
export async function deleteHotlistRuleApi(ruleId: number) {
  return requestClient.delete<{ ok: boolean }>(`/hotlist/rules/${ruleId}`);
}

/** 新建全局过滤词（命中即从所有词组匹配结果中剔除） */
export async function createHotlistGlobalFilterApi(body: HotlistApi.GlobalFilterParams) {
  return requestClient.post<HotlistApi.Rule>('/hotlist/rules/global-filters', body);
}

/** 粘贴 TrendRadar 格式文本批量导入 */
export async function importHotlistRulesApi(text: string) {
  return requestClient.post<HotlistApi.RuleImportResult>('/hotlist/rules/import', { text });
}

/** 试跑：不落库，拿当天已抓数据跑一遍匹配，返回命中条数 + 样例 */
export async function previewHotlistRuleApi(body: HotlistApi.RulePreviewParams) {
  return requestClient.post<HotlistApi.RulePreviewResult>('/hotlist/rules/preview', body);
}

// -------------------------------------------------------------- 摘要 ----

/** 热点摘要（daily=当日全部 / incremental=只看新增 / current=当前榜单），按规则分组 */
export async function getHotlistDigestApi(params: HotlistApi.DigestParams) {
  return requestClient.get<HotlistApi.Digest>('/hotlist/digest', { params });
}
