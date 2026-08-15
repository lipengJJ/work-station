import { requestClient } from '#/api/request';

export namespace FundamentalsApi {
  export interface Envelope<T = Record<string, any>> {
    data: T;
    sources: string[];
    partial_failures: string[];
    fetched_at: string;
    from_cache: boolean;
  }

  export interface SearchResult {
    symbol: string;
    cik: number | null;
    cik_str: string | null;
    title: string;
  }

  export interface OverviewData {
    symbol: string;
    name: string;
    sector: string | null;
    industry: string | null;
    price: number;
    change: number;
    change_percent: number | null;
    prev_close: number;
    market_cap: number | null;
    enterprise_value: number | null;
    shares_outstanding: number | null;
    beta: number | null;
    employees: number | null;
    pe_ttm: number | null;
    pe_forward: number | null;
    peg_ratio: number | null;
    ps_ttm: number | null;
    pb: number | null;
    ev_ebitda: number | null;
    ev_revenue: number | null;
    dividend_yield: number | null;
    earnings_yield: number | null;
    fcf_yield: number | null;
    roe: number | null;
    roa: number | null;
    roic: number | null;
    gross_margin: number | null;
    operating_margin: number | null;
    net_margin: number | null;
    ebitda: number | null;
    debt_to_equity: number | null;
    total_debt: number | null;
    total_cash: number | null;
    net_debt: number | null;
    current_ratio: number | null;
    quick_ratio: number | null;
    revenue_growth: number | null;
    earnings_growth: number | null;
    eps_ttm: number | null;
    eps_forward: number | null;
    book_value: number | null;
    next_earnings_date: string | null;
    eps_estimate_avg: number | null;
    eps_estimate_low: number | null;
    eps_estimate_high: number | null;
    revenue_estimate_avg: number | null;
    revenue_estimate_low: number | null;
    revenue_estimate_high: number | null;
    cik: number | null;
    sec_entity_name: string | null;
  }

  export interface SeriesPoint {
    end: string;
    val: number | null;
    [key: string]: unknown;
  }

  export interface RedFlag {
    key: string;
    title: string;
    result: string;
    detail: string;
  }

  export interface FinancialsData {
    series: {
      quarterly: Record<string, SeriesPoint[]>;
      annual: Record<string, SeriesPoint[]>;
      instant: Record<string, SeriesPoint[]>;
    };
    growth_and_margins: {
      quarterly: Record<string, SeriesPoint[]>;
      annual: Record<string, SeriesPoint[]>;
    };
    red_flags: RedFlag[];
  }

  export interface MultipleSummary {
    series: SeriesPoint[];
    current: number | null;
    median: number | null;
    percentile: number | null;
    min: number | null;
    max: number | null;
  }

  export interface ValuationScenario {
    pe_multiple: number;
    eps_assumption: number;
    implied_price: number;
    vs_current_percent: number;
    growth_assumption_note: string;
  }

  export interface ValuationData {
    current: OverviewData;
    historical: { pe: MultipleSummary; ps: MultipleSummary; pb: MultipleSummary };
    scenarios: {
      bear: ValuationScenario;
      base: ValuationScenario;
      bull: ValuationScenario;
      disclaimer: string;
    } | null;
  }

  export interface EpsSurpriseRow {
    report_date: string;
    eps_estimate: number | null;
    eps_actual: number | null;
    eps_surprise_percent: number | null;
  }

  export interface PostEarningsReaction {
    report_date: string;
    after_hours_change_percent: number | null;
    after_hours_available: boolean;
    next_day_change_percent: number | null;
    five_day_change_percent: number | null;
  }

  export interface EarningsData {
    revenue_estimate: Record<string, any>[];
    earnings_estimate: Record<string, any>[];
    eps_trend: Record<string, any>[];
    eps_surprise_history: EpsSurpriseRow[];
    recent_90d_upgrades: number | null;
    recent_90d_downgrades: number | null;
    recent_grade_changes: Record<string, any>[];
    post_earnings_reactions: PostEarningsReaction[];
  }

  export interface Filing {
    form: string;
    category: string;
    filed_at: string | null;
    financial_period: string | null;
    accession_number: string;
    is_amendment: boolean;
    primary_document: string;
    description: string | null;
    url: string | null;
    index_url: string;
    event_categories?: string[];
    is_material?: boolean;
  }

  export interface FilingsData {
    filings: Filing[];
    grouped: Record<string, number>;
  }

  export interface InstitutionHolding {
    institution: string;
    report_period: string;
    shares: number | null;
    shares_change: number | null;
    market_value: number | null;
  }

  export interface InstitutionsData {
    configured: boolean;
    provider: string | null;
    holdings: InstitutionHolding[];
    message: string | null;
    caveats: string[];
  }

  export interface InsiderTransaction {
    security_title: string | null;
    transaction_date: string | null;
    transaction_code: string | null;
    code: string;
    label: string;
    category: string;
    is_open_market_buy: boolean;
    shares: number | null;
    price_per_share: number | null;
    acquired_or_disposed: string | null;
    shares_owned_after: number | null;
    direct_or_indirect: string | null;
    is_derivative: boolean;
  }

  export interface InsiderFiling {
    issuer_symbol: string | null;
    owner_name: string | null;
    is_officer: boolean;
    is_director: boolean;
    is_ten_percent_owner: boolean;
    officer_title: string | null;
    period_of_report: string | null;
    transactions: InsiderTransaction[];
    filed_at: string;
    accession_number: string;
    index_url: string;
  }

  export interface InsidersData {
    transactions: InsiderFiling[];
    total_form4_filings: number;
  }

  export interface RiskItem {
    key: string;
    title: string;
    level: 'high' | 'low' | 'medium' | 'unknown';
    trigger: string | null;
    data_used: string | null;
    recent_change: unknown;
    source: string | null;
    invalidation: string | null;
    needs_data_source?: string;
  }

  export interface RisksData {
    items: RiskItem[];
  }

  export interface AiAnalysisData {
    symbol: string;
    model: string;
    markdown: string;
  }
}

function upper(symbol: string) {
  return encodeURIComponent(symbol.trim().toUpperCase());
}

export async function searchFundamentalsSymbolApi(query: string) {
  return requestClient.get<FundamentalsApi.SearchResult[]>(
    `/stock/fundamentals/search?q=${encodeURIComponent(query)}`,
  );
}

export async function getFundamentalsOverviewApi(symbol: string, config?: Record<string, unknown>) {
  return requestClient.get<FundamentalsApi.Envelope<FundamentalsApi.OverviewData>>(
    `/stock/fundamentals/${upper(symbol)}/overview`,
    config,
  );
}

export async function getFundamentalsFinancialsApi(symbol: string) {
  return requestClient.get<FundamentalsApi.Envelope<FundamentalsApi.FinancialsData>>(
    `/stock/fundamentals/${upper(symbol)}/financials`,
  );
}

export async function getFundamentalsValuationApi(symbol: string) {
  return requestClient.get<FundamentalsApi.Envelope<FundamentalsApi.ValuationData>>(
    `/stock/fundamentals/${upper(symbol)}/valuation`,
  );
}

export async function getFundamentalsEarningsApi(symbol: string) {
  return requestClient.get<FundamentalsApi.Envelope<FundamentalsApi.EarningsData>>(
    `/stock/fundamentals/${upper(symbol)}/earnings`,
  );
}

export async function getFundamentalsFilingsApi(symbol: string) {
  return requestClient.get<FundamentalsApi.Envelope<FundamentalsApi.FilingsData>>(
    `/stock/fundamentals/${upper(symbol)}/filings`,
  );
}

export async function getFundamentalsInstitutionsApi(symbol: string) {
  return requestClient.get<FundamentalsApi.Envelope<FundamentalsApi.InstitutionsData>>(
    `/stock/fundamentals/${upper(symbol)}/institutions`,
  );
}

export async function getFundamentalsInsidersApi(symbol: string) {
  return requestClient.get<FundamentalsApi.Envelope<FundamentalsApi.InsidersData>>(
    `/stock/fundamentals/${upper(symbol)}/insiders`,
  );
}

export async function getFundamentalsRisksApi(symbol: string) {
  return requestClient.get<FundamentalsApi.Envelope<FundamentalsApi.RisksData>>(
    `/stock/fundamentals/${upper(symbol)}/risks`,
  );
}

export async function getFundamentalsCachedAiAnalysisApi(symbol: string) {
  return requestClient.get<FundamentalsApi.Envelope<FundamentalsApi.AiAnalysisData> | null>(
    `/stock/fundamentals/${upper(symbol)}/ai-analysis`,
  );
}

export async function postFundamentalsAiAnalysisApi(symbol: string) {
  return requestClient.post<FundamentalsApi.Envelope<FundamentalsApi.AiAnalysisData>>(
    `/stock/fundamentals/${upper(symbol)}/ai-analysis`,
  );
}

export async function postFundamentalsRefreshApi(symbol: string, dataset?: string) {
  return requestClient.post<{ success: boolean }>(`/stock/fundamentals/${upper(symbol)}/refresh`, {
    dataset: dataset ?? null,
  });
}
