<script lang="ts" setup>
import { computed } from 'vue';

import { useAntdDesignTokens } from '@vben/hooks';
import { preferences, usePreferences } from '@vben/preferences';

import { App, ConfigProvider, theme } from 'ant-design-vue';

import { antdLocale } from '#/locales';

defineOptions({ name: 'App' });

const { isDark } = usePreferences();
const { tokens } = useAntdDesignTokens();

const tokenTheme = computed(() => {
  const algorithm = isDark.value
    ? [theme.darkAlgorithm]
    : [theme.defaultAlgorithm];

  // antd 紧凑模式算法
  if (preferences.app.compact) {
    algorithm.push(theme.compactAlgorithm);
  }

  return {
    algorithm,
    token: tokens,
  };
});
</script>

<template>
  <ConfigProvider :locale="antdLocale" :theme="tokenTheme">
    <App>
      <RouterView />
    </App>
  </ConfigProvider>
</template>

<style>
/* ========== 全局移动端适配（UI Designer 设计规范） ==========
   手机端（<768px）统一压缩页面内容区内边距，让内容更充分利用屏幕：
   页面级容器 p-6(24px) → 16px。桌面端不受影响。 */
@media (max-width: 767px) {
  /* 页面内容容器 */
  .p-6 {
    padding: 1rem !important;
  }
  /* 卡片/区块内边距 */
  .p-5 {
    padding: 1rem !important;
  }
  /* 图表卡标题区 */
  .p-4 {
    padding: 0.75rem !important;
  }
}
</style>
