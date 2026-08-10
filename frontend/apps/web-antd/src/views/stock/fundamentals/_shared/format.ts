/**
 * 基本面页面统一数字格式化。yfinance 的 .info 字段单位不统一——毛利率/ROE/营收增速这些是
 * 小数形式的比例（0.4865 = 48.65%），需要 ×100；但 dividendYield 这个字段 Yahoo 自己
 * 已经改成直接给百分比数值了（实测 AAPL 是 0.35，不是 0.0035），不能再乘一次。后端算好的
 * 同比/环比/估值分位这些已经是百分比数值，也不用再乘。调用方必须用对函数，别混用。
 */

const NO_DATA = '暂无数据';

export function formatCompactUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_DATA;
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(2)}`;
}

export function formatCompactNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_DATA;
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  if (abs >= 1e12) return `${sign}${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
  return `${sign}${abs.toFixed(0)}`;
}

/** 输入已经是百分比数值（比如 12.34 表示 12.34%），只管格式化不做换算 */
export function formatPercent(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_DATA;
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

/** 输入是小数形式的比例（0.1234 表示 12.34%），先 ×100 再格式化 */
export function formatRatioAsPercent(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_DATA;
  return formatPercent(value * 100, digits);
}

export function formatMultiple(value: number | null | undefined, suffix = 'x'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_DATA;
  return `${value.toFixed(2)}${suffix}`;
}

export function formatUsdPerShare(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_DATA;
  return `$${value.toFixed(2)}`;
}

export function formatPlainNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_DATA;
  return value.toFixed(digits);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return NO_DATA;
  return value.slice(0, 10);
}

export const NO_DATA_TEXT = NO_DATA;
