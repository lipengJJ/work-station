import { request } from '@umijs/max';

/** POST /api/auth/login —— 后端用的是标准 OAuth2PasswordRequestForm，要求 form-urlencoded body */
export async function login(username: string, password: string) {
  return request<{ access_token: string; token_type: string }>('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    data: new URLSearchParams({ username, password }).toString(),
  });
}

export async function currentUser() {
  return request<WB.CurrentUser>('/api/auth/me', { method: 'GET' });
}

export async function getHome() {
  return request<WB.HomeResponse>('/api/home', { method: 'GET' });
}

export async function getTasksCenter() {
  return request<WB.TaskCenterResponse>('/api/tasks-center', { method: 'GET' });
}

export async function getPlaceholder(path: string) {
  return request<{ status: string; label: string; message: string }>(path, { method: 'GET' });
}
