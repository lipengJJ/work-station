import { requestClient } from '#/api/request';

// 热点聚合模块：/api/hotlist/* 的前端适配层。
export namespace HotlistApi {
  export type SourceStatus = '' | 'failed' | 'success';

  export interface Source {
    id: string;
    name: string;
    adapter: string;
    expected_domain: string;
    decay_half_life_hours: number;
    interval_hours: number;
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
    /** 是否让组内源不依赖主题订阅、常驻自动抓取。默认关闭。 */
    crawl_enabled: boolean;
    source_count: number;
  }

  export interface SourceGroupParams {
    name: string;
    description?: string;
    color?: string;
    sort_order?: number;
    crawl_enabled?: boolean;
  }

  export interface SourceBatchParams {
    source_ids: string[];
    group_id?: null | number;
    enabled?: boolean;
  }

  export interface SourceImportOpmlParams {
    content?: string;
    opml_url?: string;
    /** 直接给一批 RSS/Atom 订阅地址（一行一个，前端拆好传数组），优先于 content/opml_url */
    feed_urls?: string[];
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
    interval_hours?: number;
    expected_domain?: string;
    decay_half_life_hours?: number;
    sort_order?: number;
  }

  export interface SourceCreateParams {
    id: string;
    name: string;
    adapter: string;
    adapter_params: Record<string, unknown>;
    expected_domain?: string;
    decay_half_life_hours?: number;
    interval_hours?: number;
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

  /** 条目全文（trafilatura 抽取的 Markdown，保留标题层级/图片/链接） */
  export interface ItemFulltext {
    /** success 有全文；skipped（robots 禁止/疑似付费墙）/failed（抓取失败/正文过短）content 为空 */
    status: 'failed' | 'skipped' | 'success';
    content: string;
    char_count: number;
    error: string;
    fetched_at: null | string;
  }

  export type SortField = 'rank' | 'time' | 'weight';

  export interface ListItemsParams {
    /** 关键词：匹配标题 / 摘要 / 来源名称，后端全量搜索（非当前页过滤） */
    q?: string;
    /** 分组过滤：空=全部；'ungrouped'=未分组；其余为分组 id */
    group?: string;
    stat_date?: string;
    sort?: SortField;
    hit_only?: boolean;
    page?: number;
    page_size?: number;
  }

  /** 数据源分组 AI 总结：非对话，一键生成，固定指令。 */
  export interface GroupSummary {
    id: number;
    group_filter: string;
    status: 'failed' | 'running' | 'success';
    content: string;
    error: string;
    item_count: number;
    model: string;
    created_at: string;
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

  /** 文章语义向量索引进度：GET /embedding-status 的返回。 */
  export interface EmbeddingStatus {
    total: number;
    indexed: number;
    pending: number;
    failed: number;
    /** 是否有手动补算任务正在后台执行 */
    running: boolean;
  }

  /** 手动触发存量语义索引补算：POST /embedding-backfill 的返回。 */
  export interface EmbeddingBackfillResult {
    triggered: boolean;
    message: string;
  }

  // ------------------------------------------------------------ RSSHub 路由目录 ----

  /** 本机 RSSHub 支持的一条站点路由（来自 RSSHub 自身 /api/namespace 元数据） */
  export interface RsshubRoute {
    namespace: string;
    namespace_name: string;
    path: string;
    /** 命名空间 + path 拼出的通用路由（含 :param 占位符） */
    full_path: string;
    name: string;
    /** 带具体参数的示例路径，可直接拼服务地址订阅 */
    example: string;
    categories: string[];
    maintainers: string[];
    /** 该路由要跑起来还需要配置哪些环境变量（如 TWITTER_AUTH_TOKEN）；空 = 无需额外配置 */
    require_config: string[];
  }

  export interface RsshubRouteListParams {
    /** 关键词：匹配站点名 / 路由名 / 路径 */
    keyword?: string;
    category?: string;
    /** 只看该站点下的路由 */
    namespace?: string;
    page?: number;
    page_size?: number;
    /** 跳过后端缓存，强制重新拉取 */
    refresh?: boolean;
  }

  export interface RsshubRouteListResult {
    items: RsshubRoute[];
    total: number;
    page: number;
    page_size: number;
    /** 全量分类，不受当前筛选影响，渲染分类下拉用 */
    categories: string[];
    /** 目录缓存的抓取时间（epoch 秒） */
    fetched_at: number;
  }

  /** 一个 RSSHub 站点（namespace），下面可能有多条路由 */
  export interface RsshubNamespace {
    namespace: string;
    namespace_name: string;
    url: string;
    route_count: number;
    /** 该站点下所有路由的分类并集 */
    categories: string[];
  }

  export interface RsshubNamespaceListParams {
    /** 关键词：匹配站点名 / 站点 key */
    keyword?: string;
    category?: string;
    page?: number;
    page_size?: number;
    refresh?: boolean;
  }

  export interface RsshubNamespaceListResult {
    items: RsshubNamespace[];
    total: number;
    page: number;
    page_size: number;
    categories: string[];
    fetched_at: number;
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
/** 删除分组：连组内源一起删，级联清掉这些源产出的全部新闻数据（不可逆）。 */
export async function deleteSourceGroupApi(groupId: number) {
  return requestClient.delete<{ deleted_items: number; deleted_sources: number; ok: boolean }>(
    `/hotlist/source-groups/${groupId}`,
  );
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

/** 条目全文（缓存优先，没有就现抓一次；跟主题报告 L2 共用同一份缓存） */
export async function getHotlistItemFulltextApi(itemId: number) {
  return requestClient.get<HotlistApi.ItemFulltext>(`/hotlist/items/${itemId}/fulltext`);
}

/** 手动触发全量抓取（10 分钟限频 1 次，异步执行） */
export async function triggerHotlistCrawlApi() {
  return requestClient.post<HotlistApi.CrawlResult>('/hotlist/crawl');
}

/** 一键生成当前分组的 AI 总结（同步，等几秒直接拿结果；group 同 listHotlistItemsApi 的分组过滤） */
export async function generateGroupSummaryApi(group: string) {
  return requestClient.post<HotlistApi.GroupSummary>('/hotlist/items/summary', undefined, {
    params: { group: group || undefined },
  });
}

/** 取该分组最近一条成功的总结（没有则返回 null） */
export async function getGroupSummaryApi(group: string) {
  return requestClient.get<HotlistApi.GroupSummary | null>('/hotlist/items/summary', {
    params: { group: group || undefined },
  });
}

/** 文章语义向量索引进度（低频补偿任务每 30 分钟跑一批） */
export async function getEmbeddingStatusApi(sourceIds: string[], group?: string) {
  return requestClient.get<HotlistApi.EmbeddingStatus>('/hotlist/embedding-status', {
    params: {
      group: group || undefined,
      source_ids: sourceIds.length > 0 ? sourceIds.join(',') : undefined,
    },
  });
}

/** 手动触发存量语义索引补算：已处理成功的文章会被跳过，只补缺失/失败的 */
export async function triggerEmbeddingBackfillApi(sourceIds: string[], group?: string) {
  return requestClient.post<HotlistApi.EmbeddingBackfillResult>(
    '/hotlist/embedding-backfill',
    undefined,
    {
      params: {
        group: group || undefined,
        source_ids: sourceIds.length > 0 ? sourceIds.join(',') : undefined,
      },
    },
  );
}

// -------------------------------------------------------------- RSSHub 路由目录 ----

/** 浏览/搜索本机 RSSHub 支持的站点（namespace）列表（关键词 + 分类筛选 + 分页，后端 30 分钟缓存） */
export async function listRsshubNamespacesApi(params: HotlistApi.RsshubNamespaceListParams) {
  return requestClient.get<HotlistApi.RsshubNamespaceListResult>('/hotlist/rsshub/namespaces', {
    params,
  });
}

/** 浏览某个站点下的具体路由（传 namespace）；也可不传 namespace 做全量关键词搜索 */
export async function listRsshubRoutesApi(params: HotlistApi.RsshubRouteListParams) {
  return requestClient.get<HotlistApi.RsshubRouteListResult>('/hotlist/rsshub/routes', {
    params,
  });
}
