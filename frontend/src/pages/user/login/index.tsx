import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { LoginForm, ProFormText } from '@ant-design/pro-components';
import { FormattedMessage, Helmet, useIntl, useModel } from '@umijs/max';
import { Alert, App } from 'antd';
import { createStyles } from 'antd-style';
import React, { startTransition, useState } from 'react';
import { Footer } from '@/components';
import { login } from '@/services/workbench/api';
import { setToken } from '@/services/workbench/token';
import Settings from '../../../../config/defaultSettings';

/**
 * Validate redirect URL to prevent open redirect attacks.
 * Only allow same-origin relative paths starting with '/'.
 */
const getSafeRedirectUrl = (redirect: string | null): string => {
  if (!redirect?.startsWith('/')) return '/';
  if (redirect.startsWith('//')) return '/';
  try {
    const parsed = new URL(redirect, window.location.origin);
    if (parsed.origin !== window.location.origin) return '/';
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return '/';
  }
};

const useStyles = createStyles(() => ({
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    overflow: 'auto',
    backgroundImage:
      "url('https://mdn.alipayobjects.com/yuyan_qk0oxh/afts/img/V-_oS6r-i7wAAAAAAAAAAAAAFl94AQBr')",
    backgroundSize: '100% 100%',
  },
}));

const Login: React.FC = () => {
  const [loginError, setLoginError] = useState<string | null>(null);
  const { initialState, setInitialState } = useModel('@@initialState');
  const { styles } = useStyles();
  const { message } = App.useApp();
  const intl = useIntl();

  const fetchUserInfo = async () => {
    const userInfo = await initialState?.fetchUserInfo?.();
    if (userInfo) {
      startTransition(() => {
        setInitialState((s) => ({ ...s, currentUser: userInfo }));
      });
    }
  };

  const handleSubmit = async (values: { username: string; password: string }) => {
    try {
      const result = await login(values.username, values.password);
      setToken(result.access_token);
      message.success(intl.formatMessage({ id: 'pages.login.success', defaultMessage: '登录成功！' }));
      await fetchUserInfo();
      const urlParams = new URL(window.location.href).searchParams;
      window.location.href = getSafeRedirectUrl(urlParams.get('redirect'));
    } catch {
      setLoginError('用户名或密码错误');
    }
  };

  return (
    <div className={styles.container}>
      <Helmet>
        <title>
          {intl.formatMessage({ id: 'menu.login', defaultMessage: '登录页' })}
          {Settings.title && ` - ${Settings.title}`}
        </title>
      </Helmet>
      <div style={{ flex: '1', padding: '32px 0' }}>
        <LoginForm
          contentStyle={{ minWidth: 280, maxWidth: '75vw' }}
          logo={<img alt="logo" src="/logo.svg" />}
          title="统一工作台"
          subTitle="股票分析 · 小红书分析 · 数据中心"
          onFinish={async (values) => {
            await handleSubmit(values as { username: string; password: string });
          }}
        >
          {loginError && (
            <Alert style={{ marginBottom: 24 }} message={loginError} type="error" showIcon />
          )}
          <ProFormText
            name="username"
            fieldProps={{ size: 'large', prefix: <UserOutlined /> }}
            placeholder="用户名"
            rules={[
              {
                required: true,
                message: <FormattedMessage id="pages.login.username.required" defaultMessage="请输入用户名!" />,
              },
            ]}
          />
          <ProFormText.Password
            name="password"
            fieldProps={{ size: 'large', prefix: <LockOutlined /> }}
            placeholder="密码"
            rules={[
              {
                required: true,
                message: <FormattedMessage id="pages.login.password.required" defaultMessage="请输入密码！" />,
              },
            ]}
          />
        </LoginForm>
      </div>
      <Footer />
    </div>
  );
};

export default Login;
