import { requestClient } from '#/api/request';

export namespace StrategyAiApi {
  /** 策略规则：关注范围/风险偏好/关键因子/买入倾向等，结构灵活 */
  export interface StrategyRules {
    focus?: string[];
    risk_preference?: 'low' | 'medium' | 'high';
    key_factors?: string[];
    buy_bias?: Record<string, unknown>;
    hold_condition?: string;
    avoid_condition?: string;
    output_sections?: string[];
  }

  export interface StrategyItem {
    id: number;
    name: string;
    description: string;
    is_preset: boolean;
    rules: StrategyRules;
    created_at?: string;
    updated_at?: string;
  }

  export interface StrategyInput {
    name: string;
    description?: string;
    rules?: StrategyRules;
  }

  export interface KeyIndicator {
    name: string;
    value: string;
    verdict: string;
  }

  export interface RatingPayload {
    label: string;
    reason: string;
    key_indicators: KeyIndicator[];
  }

  export interface ReportListItem {
    id: number;
    symbol: string;
    strategy_id: number;
    strategy_name: string;
    rating: string;
    rating_label: string;
    rating_reason: string;
    key_indicators: KeyIndicator[];
    provider: string;
    model: string;
    status: 'running' | 'completed' | 'failed';
    error_message?: string;
    created_at?: string;
    finished_at?: string;
  }

  export interface ReportDetail extends ReportListItem {
    report_markdown: string;
  }

  export interface ReportListResult {
    items: ReportListItem[];
    total: number;
    page: number;
    page_size: number;
  }

  export interface AnalyzeHandlers {
    onDelta: (text: string) => void;
    onRating?: (rating: RatingPayload) => void;
    onError: (message: string) => void;
    onEnd: () => void;
  }
}

/** 策略库列表（首次访问自动初始化内置预设） */
export async function listStrategiesApi() {
  return requestClient.get<StrategyAiApi.StrategyItem[]>('/stock/strategy-ai/strategies');
}

/** 新建自定义策略 */
export async function createStrategyApi(input: StrategyAiApi.StrategyInput) {
  return requestClient.post<StrategyAiApi.StrategyItem>('/stock/strategy-ai/strategies', input);
}

/** 修改策略（预设策略只允许改名称/描述，rules 保持内置框架） */
export async function updateStrategyApi(id: number, input: StrategyAiApi.StrategyInput) {
  return requestClient.put<StrategyAiApi.StrategyItem>(`/stock/strategy-ai/strategies/${id}`, input);
}

/** 删除策略（已有报告引用时后端拒绝） */
export async function deleteStrategyApi(id: number) {
  return requestClient.delete(`/stock/strategy-ai/strategies/${id}`);
}

/**
 * 发起策略分析（SSE 流式）：选策略 + 选股票 → AI 按策略框架输出 markdown 报告，
 * 流结束后端落库并返回分级结论（rating）。支持 AbortController 取消。
 */
export async function streamStrategyAnalysisApi(
  symbol: string,
  strategyId: number,
  handlers: StrategyAiApi.AnalyzeHandlers,
  signal?: AbortSignal,
) {
  let buffer = '';
  await requestClient.postSSE(
    '/stock/strategy-ai/analyze',
    { symbol, strategy_id: strategyId },
    {
      headers: { 'Content-Type': 'application/json' },
      signal,
      onMessage: (raw: string) => {
        buffer += raw;
        const events = buffer.split('\n\n');
        buffer = events.pop() ?? '';
        for (const event of events) {
          const line = event.trim();
          if (!line.startsWith('data:')) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            const parsed = JSON.parse(payload) as {
              delta?: string;
              rating?: StrategyAiApi.RatingPayload;
              done?: boolean;
              error?: string;
            };
            if (parsed.error) {
              handlers.onError(parsed.error);
            } else if (parsed.delta) {
              handlers.onDelta(parsed.delta);
            } else if (parsed.rating) {
              handlers.onRating?.(parsed.rating);
            }
          } catch {
            // 忽略解析失败的单个事件，不影响后续流
          }
        }
      },
      onEnd: handlers.onEnd,
    },
  );
}

/** 分析报告历史（分页，可按股票/策略过滤） */
export async function listStrategyReportsApi(params?: {
  symbol?: string;
  strategy_id?: number;
  page?: number;
  page_size?: number;
}) {
  return requestClient.get<StrategyAiApi.ReportListResult>('/stock/strategy-ai/reports', { params });
}

/** 报告详情（含 markdown 全文） */
export async function getStrategyReportApi(id: number) {
  return requestClient.get<StrategyAiApi.ReportDetail>(`/stock/strategy-ai/reports/${id}`);
}

/** 删除报告 */
export async function deleteStrategyReportApi(id: number) {
  return requestClient.delete(`/stock/strategy-ai/reports/${id}`);
}
