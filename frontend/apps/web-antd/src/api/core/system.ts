import { requestClient } from '#/api/request';

export namespace SystemApi {
  export interface ApiConfig {
    id: number;
    name: string;
    value: string;
    description: null | string;
    updated_at: null | string;
  }

  export interface ApiConfigIn {
    name: string;
    // 留空 = 编辑已有配置时不修改已保存的值；新增配置时必填
    value?: string;
    description?: string;
  }

  export interface LogsResult {
    lines: string[];
    file: string;
    total_lines: number;
  }
}

export async function listApiConfigsApi() {
  return requestClient.get<SystemApi.ApiConfig[]>('/system/api-configs');
}

export async function upsertApiConfigApi(body: SystemApi.ApiConfigIn) {
  return requestClient.put<SystemApi.ApiConfig>('/system/api-configs', body);
}

export async function deleteApiConfigApi(id: number) {
  return requestClient.delete<{ success: boolean }>(`/system/api-configs/${id}`);
}

export async function getSystemLogsApi(lines = 500) {
  return requestClient.get<SystemApi.LogsResult>('/system/logs', { params: { lines } });
}
