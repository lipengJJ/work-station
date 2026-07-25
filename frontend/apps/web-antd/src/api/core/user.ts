import type { UserInfo } from '@vben/types';

import { useAccessStore } from '@vben/stores';

import { requestClient } from '#/api/request';

interface BackendCurrentUser {
  id: number;
  username: string;
  role: string;
}

/**
 * 获取用户信息
 * 后端 /api/auth/me 只返回 { id, username, role }，这里映射成模板期望的 UserInfo 形状。
 */
export async function getUserInfoApi(): Promise<UserInfo> {
  const user = await requestClient.get<BackendCurrentUser>('/api/auth/me');
  const accessStore = useAccessStore();
  return {
    avatar: '',
    desc: '',
    homePath: '/home',
    realName: user.username,
    roles: [user.role],
    token: accessStore.accessToken ?? '',
    userId: String(user.id),
    username: user.username,
  };
}
