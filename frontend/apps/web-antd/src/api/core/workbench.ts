import { requestClient } from '#/api/request';

export namespace WorkbenchApi {
  export interface Task {
    id: number;
    module: string;
    task_type: string;
    status: 'failed' | 'pending' | 'running' | 'success';
    params: Record<string, unknown>;
    result_summary: null | string;
    created_at: string;
    started_at: null | string;
    finished_at: null | string;
  }

  export interface DataSourceStatus {
    module: string;
    last_run_at: null | string;
    last_status: null | string;
    total_tasks: number;
  }

  export interface HomeSummary {
    total_tasks: number;
    success_count: number;
    failed_count: number;
    running_count: number;
  }

  export interface HomeResponse {
    data_sources: DataSourceStatus[];
    recent_tasks: Task[];
    summary: HomeSummary;
  }

  export interface TaskCenterResponse {
    running: Task[];
    completed: Task[];
    failed: Task[];
  }
}

export async function getHomeApi() {
  return requestClient.get<WorkbenchApi.HomeResponse>('/home');
}

export async function getTasksCenterApi() {
  return requestClient.get<WorkbenchApi.TaskCenterResponse>('/tasks-center');
}
