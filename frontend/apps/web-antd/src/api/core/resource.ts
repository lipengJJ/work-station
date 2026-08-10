import { requestClient } from '#/api/request';

export namespace ResourceApi {
  export interface SourceInfo {
    source_id: string;
    source_name: string;
    supports_search: boolean;
    supports_save: boolean;
    search_providers: string[];
  }

  export interface ResourceItem {
    source: string;
    title: string;
    url: string;
    share_id: string;
    share_pwd: string;
    category: string;
    snippet: string;
  }

  export interface SearchResult {
    source: string;
    provider: string;
    items: ResourceItem[];
    total: number;
    page: number;
    page_size: number;
    message: string;
  }

  export interface SaveParams {
    source: string;
    share_url: string;
    share_pwd?: string;
    target_dir?: string;
  }

  export interface SaveTask {
    id: number;
    source: string;
    resource_title: string;
    share_url: string;
    share_id: string;
    share_pwd: string;
    target_dir: string;
    status: 'failed' | 'pending' | 'success';
    message: string;
    created_at: string;
  }

  export interface SaveTaskPage {
    items: SaveTask[];
    total: number;
    page: number;
    page_size: number;
  }

  export interface CookieStatus {
    has_token: boolean;
    preview: null | string;
    updated_at: null | string;
  }

  export interface QuarkAccount {
    nickname: string;
    vip_member: boolean;
    capacity: number;
    used: number;
  }

  export interface LinkCheckItem {
    share_id?: string;
    url?: string;
    pwd?: string;
  }

  export interface LinkCheckResult {
    share_id: string;
    status: 'invalid' | 'needs_pwd' | 'unknown' | 'valid';
    message: string;
    file_count: number;
    url: string;
  }
}

/** 可用资源源列表（新增网盘源后自动扩展） */
export async function listResourceSourcesApi() {
  return requestClient.get<ResourceApi.SourceInfo[]>('/resource/sources');
}

/** 资源搜索（夸克分享链接聚合搜索） */
export async function searchResourceApi(params: {
  category?: string;
  keyword: string;
  page?: number;
  page_size?: number;
  source?: string;
}) {
  return requestClient.get<ResourceApi.SearchResult>('/resource/search', { params });
}

/** 转存分享链接到网盘 */
export async function saveResourceApi(body: ResourceApi.SaveParams) {
  return requestClient.post<ResourceApi.SaveTask>('/resource/save', body);
}

/** 批量校验夸克分享链接是否有效（最多 20 条） */
export async function checkResourceLinksApi(links: ResourceApi.LinkCheckItem[]) {
  return requestClient.post<ResourceApi.LinkCheckResult[]>('/resource/links/check', { links });
}

/** 转存记录分页列表 */
export async function listSaveTasksApi(params: { page?: number; page_size?: number }) {
  return requestClient.get<ResourceApi.SaveTaskPage>('/resource/save-tasks', { params });
}

/** 删除一条转存记录 */
export async function deleteSaveTaskApi(taskId: number) {
  return requestClient.delete<{ ok: boolean }>(`/resource/save-tasks/${taskId}`);
}

/** 夸克 Cookie 状态 */
export async function getQuarkCookieStatusApi() {
  return requestClient.get<ResourceApi.CookieStatus>('/resource/quark/cookie');
}

/** 保存夸克 Cookie */
export async function setQuarkCookieApi(cookies: string) {
  return requestClient.post<ResourceApi.CookieStatus>('/resource/quark/cookie', { cookies });
}

/** 清除夸克 Cookie */
export async function clearQuarkCookieApi() {
  return requestClient.delete<ResourceApi.CookieStatus>('/resource/quark/cookie');
}

/** 校验夸克 Cookie 并返回账号信息 */
export async function verifyQuarkAccountApi() {
  return requestClient.get<ResourceApi.QuarkAccount>('/resource/quark/me');
}
