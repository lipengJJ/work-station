import { reactive } from 'vue';

// 全局「发送通知」函数式入口：任意模块按钮一行唤起发送弹窗。
// 用法：
//   const { state, openNotifySender } = useNotifySender();
//   <button @click="openNotifySender({ context: '任务中心', title, content })">通知我</button>
//   <NotifySenderModal v-model:open="state.open" :context="state.context" />
export interface NotifySenderOptions {
  /** 来源模块名（展示在弹窗头部） */
  context?: string;
  /** 预填标题 */
  title?: string;
  /** 预填内容 */
  content?: string;
}

export function useNotifySender() {
  const state = reactive({
    open: false,
    context: '',
    title: '',
    content: '',
  });

  function openNotifySender(options?: NotifySenderOptions) {
    state.context = options?.context ?? '';
    state.title = options?.title ?? '';
    state.content = options?.content ?? '';
    state.open = true;
  }

  function closeNotifySender() {
    state.open = false;
  }

  return { state, openNotifySender, closeNotifySender };
}
