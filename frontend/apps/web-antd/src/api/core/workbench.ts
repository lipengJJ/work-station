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

  export interface HomeSummary {
    total_tasks: number;
    success_count: number;
    failed_count: number;
    running_count: number;
    today_new: number;
    today_done: number;
    success_rate: number;
  }

  export interface TrendPoint {
    date: string;
    created: number;
    finished: number;
  }

  export interface RunningTask {
    id: number;
    /** collect 采集任务 | backfill 补抓评论 | tracking 追踪扫描 */
    kind: 'collect' | 'backfill' | 'tracking';
    title: string;
    status: string;
    phase: string | null;
    progress_current: number | null;
    progress_total: number | null;
    started_at: string | null;
  }

  export interface HomeResponse {
    recent_tasks: Task[];
    running_tasks: RunningTask[];
    trend: TrendPoint[];
    status_distribution: Record<string, number>;
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
