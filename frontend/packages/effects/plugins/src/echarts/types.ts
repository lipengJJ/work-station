import type {
  BarSeriesOption,
  CandlestickSeriesOption,
  LineSeriesOption,
  PieSeriesOption,
  RadarSeriesOption,
} from 'echarts/charts';
import type {
  DatasetComponentOption,
  DataZoomComponentOption,
  GridComponentOption,
  LegendComponentOption,
  MarkLineComponentOption,
  MarkPointComponentOption,
  TitleComponentOption,
  ToolboxComponentOption,
  TooltipComponentOption,
} from 'echarts/components';
import type { ComposeOption } from 'echarts/core';

export type ECOption = ComposeOption<
  | BarSeriesOption
  | CandlestickSeriesOption
  | DatasetComponentOption
  | DataZoomComponentOption
  | GridComponentOption
  | LegendComponentOption
  | LineSeriesOption
  | MarkLineComponentOption
  | MarkPointComponentOption
  | PieSeriesOption
  | RadarSeriesOption
  | TitleComponentOption
  | ToolboxComponentOption
  | TooltipComponentOption
>;
