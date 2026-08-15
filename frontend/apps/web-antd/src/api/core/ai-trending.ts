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
