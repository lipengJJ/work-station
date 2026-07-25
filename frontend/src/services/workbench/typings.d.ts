// 工作台自己后端的类型定义，独立于 src/services/ant-design-pro（那套是模板自带 mock 的自动生成代码，
// 参见项目 CLAUDE.md：不要手改，也不需要为我们自己的后端复用它）。

declare namespace WB {
  interface CurrentUser {
    id: number;
    username: string;
    role: string;
  }

  interface Task {
    id: number;
    module: string;
    task_type: string;
    status: 'pending' | 'running' | 'success' | 'failed';
    params: Record<string, unknown>;
    result_summary: string | null;
    created_at: string;
    started_at: string | null;
    finished_at: string | null;
  }

  interface TaskCenterResponse {
    running: Task[];
    completed: Task[];
    failed: Task[];
  }

  interface DataSourceStatus {
    module: string;
    last_run_at: string | null;
    last_status: string | null;
    total_tasks: number;
  }

  interface HomeSummary {
    total_tasks: number;
    success_count: number;
    failed_count: number;
    running_count: number;
  }

  interface HomeResponse {
    data_sources: DataSourceStatus[];
    recent_tasks: Task[];
    summary: HomeSummary;
  }
}
