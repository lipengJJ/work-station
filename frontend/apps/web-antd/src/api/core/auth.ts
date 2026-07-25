import { requestClient } from '#/api/request';

export namespace AuthApi {
  /** 登录接口参数 */
  export interface LoginParams {
    password?: string;
    username?: string;
  }

  /** 登录接口返回值 */
  export interface LoginResult {
    accessToken: string;
  }
}

/**
 * 登录
 * 后端 /api/auth/login 是标准 OAuth2PasswordRequestForm，要求 form-urlencoded body，
 * 返回 { access_token, token_type }（不是驼峰），这里做一层转换适配模板约定的 LoginResult 形状。
 */
export async function loginApi(data: AuthApi.LoginParams) {
  const form = new URLSearchParams();
  form.set('username', data.username ?? '');
  form.set('password', data.password ?? '');
  const result = await requestClient.post<{
    access_token: string;
    token_type: string;
  }>('/auth/login', form.toString(), {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });
  return { accessToken: result.access_token } satisfies AuthApi.LoginResult;
}

/**
 * 退出登录
 * 后端没有单独的 logout 接口（无状态 JWT，前端清 token 即可），这里保持空实现，
 * 避免 authStore.logout() 里 await logoutApi() 报错。
 */
export async function logoutApi() {
  return Promise.resolve();
}

/**
 * 获取用户权限码
 * 后端目前只有单管理员角色，没有细粒度权限码体系，用 role 映射成一个简单的 code 数组。
 */
export async function getAccessCodesApi() {
  const user = await requestClient.get<{ role: string }>('/auth/me');
  return [user.role];
}
