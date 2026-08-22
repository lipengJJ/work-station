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
    /** 失败类型：dns_error / http_404 / parse_error / upstream_down … 空 = 没失败过 */
    last_error_kind: string;
    /** last_error_kind 的中文说明，后端填好直接展示 */
    last_error_label: string;
    consecutive_failures: number;
    /** 瞬时失败次数（DNS 抖动 / 上游故障），不判定源失效 */
    transient_failures: number;
    /** 永久失败次数（404 / 解析失败 / 被拒），失效判定只看这个 */
    permanent_failures: number;
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
    /** 分组过滤：空=全部；'ungrouped'=未分组；其余为分组 id */
    group?: string;
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

  /** 手动批量抓取：POST /sources/crawl 的返回。 */
  export interface CrawlTrigger {
    triggered: boolean;
    count: number;
    job_id: string;
  }

  /** 手动批量抓取进度：GET /sources/crawl-status 的返回。 */
  export interface CrawlStatus {
    running: boolean;
    total?: number;
    done?: number;
    source_ids?: string[];
    finished?: boolean;
    skipped?: boolean;
    failed?: number;
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
    /** 分组过滤：空=全部；'ungrouped'=未分组；其余为分组 id */
    group?: string;
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

/** 立即抓取选中的源（后台执行，立即返回；source_ids 为空 = 全部启用中的源） */
export async function crawlSourcesApi(sourceIds: string[]) {
  return requestClient.post<HotlistApi.CrawlTrigger>(
    '/hotlist/sources/crawl',
    { source_ids: sourceIds },
  );
}

/** 查询一次手动批量抓取的进度（页面刷新后靠 job_id 恢复显示） */
export async function getCrawlStatusApi(jobId: string) {
  return requestClient.get<HotlistApi.CrawlStatus>('/hotlist/sources/crawl-status', {
    params: { job_id: jobId },
  });
}

/** 立即抓取单个源（同步执行，返回该源抓完后的最新状态） */
export async function crawlOneSourceApi(sourceId: string) {
  return requestClient.post<HotlistApi.Source>(`/hotlist/sources/${sourceId}/crawl`);
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

// -------------------------------------------------------------- 摘要 ----

/** 热点摘要（daily=当日全部 / incremental=只看新增 / current=当前榜单），按语义命中主题分组 */
export async function getHotlistDigestApi(params: HotlistApi.DigestParams) {
  return requestClient.get<HotlistApi.Digest>('/hotlist/digest', { params });
}
