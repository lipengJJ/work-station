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
    group_id: null | number;
    last_fetched_at: null | string;
    last_status: SourceStatus;
    last_error: string;
    consecutive_failures: number;
    fail_count: number;
    last_success_at: null | string;
    total_fetched: number;
  }

  export interface SourceGroup {
    id: number;
    name: string;
    description: string;
    color: string;
    sort_order: number;
    is_builtin: boolean;
    source_count: number;
  }

  export interface SourceGroupParams {
    name: string;
    description?: string;
    color?: string;
    sort_order?: number;
  }

  export interface SourceBatchParams {
    source_ids: string[];
    group_id?: null | number;
    enabled?: boolean;
  }

  export interface SourceImportOpmlParams {
    content?: string;
    opml_url?: string;
    group_id?: null | number;
  }

  export interface SourceImportOpmlResult {
    created: string[];
    reused: string[];
    skipped: number;
    source_ids: string[];
    detail: string;
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
    topic_id: null | number;
    display_name: string;
    normal_words: Word[];
    required_words: Word[];
    exclude_words: Word[];
    max_count: number;
    enabled: boolean;
    sort_order: number;
    created_at: null | string;
    updated_at: null | string;
  }

  export interface RuleParams {
    display_name?: string;
    normal_words?: Word[];
    required_words?: Word[];
    exclude_words?: Word[];
    max_count?: number;
    enabled?: boolean;
    sort_order?: number;
    topic_id?: null | number;
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

/** 源列表 + 健康状态（可按分组筛选） */
export async function listHotlistSourcesApi(groupId?: number) {
  return requestClient.get<HotlistApi.Source[]>('/hotlist/sources', {
    params: groupId === undefined ? undefined : { group_id: groupId },
  });
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

// -------------------------------------------------------------- 源分组 ----

/** 源分组列表（含组内源数） */
export async function listSourceGroupsApi() {
  return requestClient.get<HotlistApi.SourceGroup[]>('/hotlist/source-groups');
}

/** 新建源分组 */
export async function createSourceGroupApi(body: HotlistApi.SourceGroupParams) {
  return requestClient.post<HotlistApi.SourceGroup>('/hotlist/source-groups', body);
}

/** 更新源分组（name/description/color/sort_order，全字段可选） */
export async function updateSourceGroupApi(groupId: number, body: Partial<HotlistApi.SourceGroupParams>) {
  return requestClient.put<HotlistApi.SourceGroup>(`/hotlist/source-groups/${groupId}`, body);
}

/** 删除源分组（内置分组拒删；组内源自动移回未分组） */
export async function deleteSourceGroupApi(groupId: number) {
  return requestClient.delete<{ ok: boolean }>(`/hotlist/source-groups/${groupId}`);
}

// -------------------------------------------------------------- 批量操作 ----

/** 批量移动分组 / 启停源 */
export async function batchSourcesApi(body: HotlistApi.SourceBatchParams) {
  return requestClient.post<{ ok: boolean; moved: number; enabled_changed: number }>(
    '/hotlist/sources/batch',
    body,
  );
}

/** 批量导入 OPML 到分组（content 优先；opml_url 可选） */
export async function importSourcesOpmlApi(body: HotlistApi.SourceImportOpmlParams) {
  return requestClient.post<HotlistApi.SourceImportOpmlResult>('/hotlist/sources/import-opml', body);
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

/** 主题下的词组规则列表 */
export async function listTopicRulesApi(topicId: number) {
  return requestClient.get<HotlistApi.Rule[]>(`/hotlist/topics/${topicId}/rules`);
}

/** 新建主题下的词组规则 */
export async function createTopicRuleApi(topicId: number, body: HotlistApi.RuleParams) {
  return requestClient.post<HotlistApi.Rule>(`/hotlist/topics/${topicId}/rules`, body);
}

/** 更新词组规则（全字段可选，覆盖式保存；不允许改归属） */
export async function updateHotlistRuleApi(ruleId: number, body: HotlistApi.RuleParams) {
  return requestClient.put<HotlistApi.Rule>(`/hotlist/rules/${ruleId}`, body);
}

/** 删除词组规则 */
export async function deleteHotlistRuleApi(ruleId: number) {
  return requestClient.delete<{ ok: boolean }>(`/hotlist/rules/${ruleId}`);
}

/** 批量导入 TrendRadar 格式文本到该主题 */
export async function importTopicRulesApi(topicId: number, text: string) {
  return requestClient.post<HotlistApi.RuleImportResult>(`/hotlist/topics/${topicId}/rules/import`, {
    text,
  });
}

/** 试跑：用该主题的源 + 规则，拿当天已抓数据跑一遍匹配，返回命中条数 + 样例 */
export async function previewTopicRuleApi(topicId: number, body: HotlistApi.RulePreviewParams) {
  return requestClient.post<HotlistApi.RulePreviewResult>(
    `/hotlist/topics/${topicId}/rules/preview`,
    body,
  );
}

// -------------------------------------------------------------- 全局过滤词 ----

/** 全局过滤词列表（对所有主题生效） */
export async function listGlobalFiltersApi() {
  return requestClient.get<HotlistApi.Rule[]>('/hotlist/global-filters');
}

/** 新建全局过滤词（命中即从所有词组匹配结果中剔除） */
export async function createGlobalFilterApi(body: HotlistApi.GlobalFilterParams) {
  return requestClient.post<HotlistApi.Rule>('/hotlist/global-filters', body);
}

/** 删除全局过滤词 */
export async function deleteGlobalFilterApi(ruleId: number) {
  return requestClient.delete<{ ok: boolean }>(`/hotlist/global-filters/${ruleId}`);
}

// -------------------------------------------------------------- 摘要 ----

/** 热点摘要（daily=当日全部 / incremental=只看新增 / current=当前榜单），按规则分组 */
export async function getHotlistDigestApi(params: HotlistApi.DigestParams) {
  return requestClient.get<HotlistApi.Digest>('/hotlist/digest', { params });
}
