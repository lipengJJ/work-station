import type { EChartsOption } from 'echarts';

import type { Ref } from 'vue';

import type { Nullable } from '@vben/types';

import type EchartsUI from './echarts-ui.vue';

import {
  computed,
  nextTick,
  onActivated,
  onBeforeUnmount,
  onDeactivated,
  onMounted,
  ref,
  unref,
  watch,
} from 'vue';

import { usePreferences } from '@vben/preferences';

import {
  tryOnUnmounted,
  useDebounceFn,
  useResizeObserver,
  useTimeoutFn,
  useWindowSize,
} from '@vueuse/core';

import echarts from './echarts';

type EchartsUIType = typeof EchartsUI | undefined;

type EchartsThemeType = 'dark' | 'light' | null;

function useEcharts(chartRef: Ref<EchartsUIType>) {
  let chartInstance: echarts.ECharts | null = null;
  let cacheOptions: EChartsOption = {};
  // echarts是否处于激活状态
  const isActiveRef = ref(false);

  const { isDark } = usePreferences();
  const { height, width } = useWindowSize();
  const resizeHandler: () => void = useDebounceFn(resize, 200);

  const getChartEl = (): HTMLElement | null => {
    const refValue = chartRef?.value as unknown;
    if (!refValue) return null;
    if (refValue instanceof HTMLElement) {
      return refValue;
    }
    const maybeComponent = refValue as { $el?: HTMLElement };
    return maybeComponent.$el ?? null;
  };

  onMounted(() => (isActiveRef.value = true));
  onActivated(() => (isActiveRef.value = true));
  onDeactivated(() => (isActiveRef.value = false));
  onBeforeUnmount(() => (isActiveRef.value = false));

  const isElHidden = (el: HTMLElement | null): boolean => {
    if (!el) return true;
    return el.offsetHeight === 0 || el.offsetWidth === 0;
  };

  const getOptions = computed((): EChartsOption => {
    if (!isDark.value) {
      return {};
    }

    return {
      backgroundColor: 'transparent',
    };
  });

  const initCharts = (t?: EchartsThemeType) => {
    const el = chartRef?.value?.$el;
    if (!el) {
      return;
    }
    chartInstance = echarts.init(el, t || isDark.value ? 'dark' : null);

    return chartInstance;
  };

  const renderEcharts = (
    options: EChartsOption,
    clear = true,
  ): Promise<Nullable<echarts.ECharts>> => {
    // 缓存放在 isActiveRef 判断之前：调用方常见写法是 watch(deps, () => renderEcharts(...),
    // { immediate: true })，这个 immediate 回调在 setup 阶段就同步执行，早于 onMounted
    // 把 isActiveRef 置为 true。如果依赖的数据这时候已经就绪（比如页面间共享的 state、
    // 或者组件被 keep-alive 缓存过一次），会命中下面的提前返回、且此前从不缓存 options，
    // 之后除非依赖再变一次否则永远不会补渲染，图表就一直空着——直到用户手动切一次
    // tab 之类的操作才会重新触发。提前缓存，让下面 isActiveRef 的 watch 一旦变 true
    // 就能把这次没渲染成的 options 补上。
    cacheOptions = options;
    if (!unref(isActiveRef)) {
      return Promise.resolve(null);
    }
    const currentOptions = {
      ...options,
      ...getOptions.value,
    };
    return new Promise((resolve) => {
      if (chartRef.value?.offsetHeight === 0) {
        useTimeoutFn(async () => {
          resolve(await renderEcharts(currentOptions));
        }, 30);
        return;
      }
      nextTick(() => {
        const el = getChartEl();
        if (isElHidden(el)) {
          useTimeoutFn(async () => {
            resolve(await renderEcharts(currentOptions));
          }, 30);
          return;
        }
        useTimeoutFn(() => {
          if (!chartInstance || chartInstance?.getDom() !== el) {
            chartInstance?.dispose();
            const instance = initCharts();
            if (!instance) return;
            chartInstance = instance;
          }
          clear && chartInstance?.clear();
          chartInstance?.setOption(currentOptions);
          resolve(chartInstance);
        }, 30);
      });
    });
  };

  const updateData = (
    option: EChartsOption,
    notMerge = false, // false = 合并（保留动画），true = 完全替换
    lazyUpdate = false, // true 时不立即重绘，适合短时间内多次调用
  ): Promise<echarts.ECharts | null> => {
    return new Promise((resolve) => {
      nextTick(() => {
        if (!chartInstance) {
          // 还没初始化 → 当作首次渲染
          renderEcharts(option).then(resolve);
          return;
        }

        // 合并你原有的全局配置（比如 backgroundColor）
        const finalOption = {
          ...option,
          ...getOptions.value,
        };

        chartInstance.setOption(finalOption, {
          notMerge,
          lazyUpdate,
          // silent: true,     // 如果追求极致性能可开启（关闭所有事件）
        });

        resolve(chartInstance);
      });
    });
  };

  function resize() {
    const el = getChartEl();
    if (isElHidden(el)) {
      return;
    }
    chartInstance?.resize({
      animation: {
        duration: 300,
        easing: 'quadraticIn',
      },
    });
  }

  watch([width, height], () => {
    resizeHandler?.();
  });

  useResizeObserver(chartRef as never, resizeHandler);

  watch([isDark, isActiveRef], () => {
    if (!unref(isActiveRef)) return;
    if (chartInstance) {
      chartInstance.dispose();
      initCharts();
    }
    // chartInstance 为空说明还从没渲染成功过——常见于 renderEcharts 在 isActiveRef 变
    // true 之前就被调用过一次（见上面 renderEcharts 里的注释），这里用缓存的 options
    // 补一次；Object.keys 判断只是避免组件刚创建、renderEcharts 从没被调用过时拿一个
    // 空对象去初始化一次没有意义的图表
    if (chartInstance || Object.keys(cacheOptions).length > 0) {
      renderEcharts(cacheOptions);
    }
    resize();
  });

  tryOnUnmounted(() => {
    // 销毁实例，释放资源
    chartInstance?.dispose();
  });
  return {
    isActive: isActiveRef,
    renderEcharts,
    resize,
    updateData,
    getChartInstance: () => chartInstance,
  };
}

export { useEcharts };

export type { EchartsUIType };
