import type { BuiltinThemeType, TimezoneOption } from '@vben-core/typings';

interface BuiltinThemePreset {
  color: string;
  darkPrimaryColor?: string;
  primaryColor?: string;
  type: BuiltinThemeType;
}

const BUILT_IN_THEME_PRESETS: BuiltinThemePreset[] = [
  // ---- 热门推荐主题（浅色/深色均有完整色板，直接点选切换）----
  {
    color: 'hsl(212 100% 45%)',
    type: 'default',
  },
  {
    color: 'hsl(231 98% 65%)',
    type: 'sky-blue',
  },
  {
    color: 'hsl(245 82% 67%)',
    type: 'violet',
  },
  {
    color: 'hsl(347 77% 60%)',
    type: 'pink',
  },
  {
    color: 'hsl(210 34% 52%)',
    darkPrimaryColor: 'hsl(200 39% 67%)',
    primaryColor: 'hsl(210 34% 52%)',
    type: 'nord',
  },
  {
    color: 'hsl(265 65% 58%)',
    darkPrimaryColor: 'hsl(265 89% 78%)',
    primaryColor: 'hsl(265 65% 58%)',
    type: 'dracula',
  },
  {
    color: 'hsl(220 89% 60%)',
    darkPrimaryColor: 'hsl(220 89% 72%)',
    primaryColor: 'hsl(220 89% 60%)',
    type: 'tokyo-night',
  },
];

/**
 * 时区选项
 */
const DEFAULT_TIME_ZONE_OPTIONS: TimezoneOption[] = [
  {
    offset: -5,
    timezone: 'America/New_York',
    label: 'America/New_York(GMT-5)',
  },
  {
    offset: 0,
    timezone: 'Europe/London',
    label: 'Europe/London(GMT0)',
  },
  {
    offset: 8,
    timezone: 'Asia/Shanghai',
    label: 'Asia/Shanghai(GMT+8)',
  },
  {
    offset: 9,
    timezone: 'Asia/Tokyo',
    label: 'Asia/Tokyo(GMT+9)',
  },
  {
    offset: 9,
    timezone: 'Asia/Seoul',
    label: 'Asia/Seoul(GMT+9)',
  },
];

export const COLOR_PRESETS = [...BUILT_IN_THEME_PRESETS].slice(0, 7);

export { BUILT_IN_THEME_PRESETS, DEFAULT_TIME_ZONE_OPTIONS };

export type { BuiltinThemePreset };
