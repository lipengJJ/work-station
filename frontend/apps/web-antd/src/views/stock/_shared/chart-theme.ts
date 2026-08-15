/**
 * ECharts 主题感知取色：从 CSS 变量（--card/--border/--muted-foreground 等）读取颜色，
 * 转成 echarts 可用的 hsl() 字符串。主题切换后下次重绘自动跟随，保证图表与页面统一。
 */
export function chartColor(varName: string, fallback = '#64748b'): string {
  if (typeof window === 'undefined') return fallback;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
  if (!raw) return fallback;
  const inner = raw.startsWith('hsl(') ? raw.slice(4, -1) : raw;
  const parts = inner.replace(/deg/g, '').split(/\s+/).filter(Boolean);
  if (parts.length >= 3) {
    return `hsl(${parts[0]}, ${parts[1]}, ${parts[2]})`;
  }
  return fallback;
}
