import type { XhsApi } from '#/api/core/xhs';

// 采集任务的选项定义/状态与阶段文案/表单默认值：独立采集任务页已下线（笔记管理页
// 本身就能新建/删除采集任务），这里统一放一份，供笔记管理页和共享的
// CreateCollectTaskModal 一起用，避免各写一份慢慢改出差异（比如 PHASE_LABEL
// 漏了后来新加的 structuring 阶段）。

export const SORT_OPTIONS = [
  { value: 0, label: '综合排序' },
  { value: 1, label: '最新' },
  { value: 2, label: '最多点赞' },
  { value: 3, label: '最多评论' },
  { value: 4, label: '最多收藏' },
];
export const NOTE_TYPE_OPTIONS = [
  { value: 0, label: '不限' },
  { value: 1, label: '视频笔记' },
  { value: 2, label: '普通笔记' },
];
export const NOTE_TIME_OPTIONS = [
  { value: 0, label: '不限' },
  { value: 1, label: '一天内' },
  { value: 2, label: '一周内' },
  { value: 3, label: '半年内' },
];
export const NOTE_RANGE_OPTIONS = [
  { value: 0, label: '不限' },
  { value: 1, label: '已看过' },
  { value: 2, label: '未看过' },
  { value: 3, label: '已关注' },
];

export const STATUS_LABEL: Record<string, string> = {
  pending: '排队中',
  running: '运行中',
  success: '已完成',
  failed: '失败',
};
export const STATUS_COLOR: Record<string, string> = {
  pending: 'default',
  running: 'processing',
  success: 'success',
  failed: 'error',
};

// 和后端 tasks.py::_set_progress 的阶段顺序一一对应：
// queued -> searching -> fetching_notes -> structuring -> downloading_media
// -> fetching_comments（可选） -> exporting（可选） -> done/failed
export const PHASE_LABEL: Record<string, string> = {
  queued: '等待开始',
  searching: '搜索候选笔记',
  fetching_notes: '数据爬取',
  structuring: '数据清洗',
  downloading_media: '素材下载',
  fetching_comments: '抓取评论',
  exporting: '导出文件',
  done: '已完成',
  failed: '失败',
};

export function statusLabel(s: string): string {
  return STATUS_LABEL[s] ?? s;
}
export function statusColor(s: string): string {
  return STATUS_COLOR[s] ?? 'default';
}
export function phaseLabel(p: string): string {
  return PHASE_LABEL[p] ?? p;
}
export function progressPercent(task: XhsApi.CollectTask): number {
  if (!task.progress_total) return 0;
  return Math.min(100, Math.round((task.progress_current / task.progress_total) * 100));
}

export function defaultTaskForm(): XhsApi.CollectTaskParams {
  return {
    keyword: '',
    require_num: 50,
    sort_type_choice: 0,
    note_type: 0,
    note_time: 0,
    note_range: 0,
    // 直接抓全部：Excel + 图文 + 视频素材，不再让用户选保存方式
    save_choice: 'all',
    fetch_comments: false,
    max_comments_per_note: null,
    comment_interval_seconds: null,
  };
}
