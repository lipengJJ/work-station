<script lang="ts" setup>
import type { XhsApi } from '#/api/core/xhs';

import { onBeforeUnmount, onMounted, reactive, ref } from 'vue';

import { Alert, Button, Input, message, Modal, Tabs } from 'ant-design-vue';

import {
  clearXhsTokenApi,
  getXhsTokenApi,
  getXhsTokenFullApi,
  pollXhsQrcodeLoginApi,
  sendXhsPhoneCodeApi,
  setXhsTokenApi,
  startXhsQrcodeLoginApi,
  verifyXhsPhoneLoginApi,
} from '#/api/core/xhs';

// 小红书登录态管理，从 collect-tasks/index.vue 抽出来的独立组件——采集/追踪任务都
// 依赖这份 cookie，不管挂在哪个页面顶部都是同一份状态（后端就一份 xhs_cookie 配置）。

const TextArea = Input.TextArea;

const tokenStatus = ref<XhsApi.TokenStatus>({
  has_token: false,
  preview: null,
  updated_at: null,
});
const tokenModalOpen = ref(false);
const loginTab = ref('qrcode');

const qrcode = reactive({ loading: false, image: '', qrId: '', message: '' });
let qrcodeTimer: ReturnType<typeof setInterval> | undefined;

const phone = reactive({
  zone: '86',
  number: '',
  code: '',
  sending: false,
  verifying: false,
  message: '',
});
const manual = reactive({ cookies: '', saving: false, message: '' });

async function refreshTokenStatus() {
  tokenStatus.value = await getXhsTokenApi();
}

async function startQrcode() {
  if (qrcodeTimer) clearInterval(qrcodeTimer);
  qrcode.loading = true;
  qrcode.image = '';
  try {
    const data = await startXhsQrcodeLoginApi();
    if (data.status !== 'ok' || !data.qr_id || !data.qr_image) {
      message.error(`获取二维码失败：${data.msg}`);
      return;
    }
    qrcode.image = data.qr_image;
    qrcode.qrId = data.qr_id;
    qrcode.message = '请使用小红书 App 扫描二维码';
    qrcodeTimer = setInterval(pollQrcode, 2000);
  } catch (e: any) {
    message.error(`获取二维码失败：${e.message}`);
  } finally {
    qrcode.loading = false;
  }
}

async function pollQrcode() {
  try {
    const s = await pollXhsQrcodeLoginApi(qrcode.qrId);
    if (s.status === 'success') {
      clearInterval(qrcodeTimer);
      qrcode.message = `登录成功：${s.nickname}`;
      message.success('登录成功');
      refreshTokenStatus();
    } else if (s.status === 'expired') {
      clearInterval(qrcodeTimer);
      qrcode.message = s.msg || '二维码已过期，请重新获取';
    } else {
      qrcode.message = s.msg || '等待扫码...';
    }
  } catch (e: any) {
    clearInterval(qrcodeTimer);
    qrcode.message = `轮询失败：${e.message}`;
  }
}

async function sendPhoneCode() {
  if (!phone.number.trim()) {
    phone.message = '请输入手机号';
    return;
  }
  phone.sending = true;
  try {
    const res = await sendXhsPhoneCodeApi(phone.number.trim(), phone.zone.trim() || '86');
    phone.message = res.success ? '验证码已发送' : `发送失败：${res.msg}`;
  } catch (e: any) {
    phone.message = `发送失败：${e.message}`;
  } finally {
    phone.sending = false;
  }
}

async function verifyPhone() {
  if (!phone.number.trim() || !phone.code.trim()) {
    phone.message = '请输入手机号和验证码';
    return;
  }
  phone.verifying = true;
  try {
    const res = await verifyXhsPhoneLoginApi(
      phone.number.trim(),
      phone.code.trim(),
      phone.zone.trim() || '86',
    );
    if (res.success) {
      phone.message = `登录成功：${res.nickname}`;
      message.success('登录成功');
      refreshTokenStatus();
    } else {
      phone.message = `登录失败：${res.msg}`;
    }
  } catch (e: any) {
    phone.message = `登录失败：${e.message}`;
  } finally {
    phone.verifying = false;
  }
}

async function saveManualCookie() {
  const val = manual.cookies.trim();
  if (!val) {
    manual.message = '请粘贴 cookie 内容';
    return;
  }
  manual.saving = true;
  try {
    await setXhsTokenApi(val);
    manual.message = '保存成功';
    message.success('Token 已保存');
    refreshTokenStatus();
  } catch (e: any) {
    manual.message = `保存失败：${e.message}`;
  } finally {
    manual.saving = false;
  }
}

async function viewFullCookie() {
  try {
    const data = await getXhsTokenFullApi();
    manual.cookies = data.cookies;
    manual.message = '已加载当前完整 cookie';
  } catch (e: any) {
    manual.message = `获取失败：${e.message}`;
  }
}

function clearToken() {
  Modal.confirm({
    title: '确定清除已保存的 token 吗？',
    content: '仅清除本系统里保存的 cookie，不影响其它地方。',
    okType: 'danger',
    onOk: async () => {
      await clearXhsTokenApi();
      manual.cookies = '';
      manual.message = '已清除';
      refreshTokenStatus();
    },
  });
}

onMounted(() => {
  refreshTokenStatus();
});

onBeforeUnmount(() => {
  if (qrcodeTimer) clearInterval(qrcodeTimer);
});
</script>

<template>
  <Alert :type="tokenStatus.has_token ? 'success' : 'warning'" show-icon>
    <template #message>
      <span v-if="tokenStatus.has_token">Token 已配置 {{ tokenStatus.preview }}</span>
      <span v-else>尚未配置小红书 Token，请先获取</span>
    </template>
    <template #action>
      <Button size="small" @click="tokenModalOpen = true">获取 / 管理 Token</Button>
    </template>
  </Alert>

  <Modal v-model:open="tokenModalOpen" title="获取 / 管理 Token" :footer="null" width="480px">
    <Tabs v-model:active-key="loginTab">
      <Tabs.TabPane key="qrcode" tab="扫码登录">
        <div style="text-align: center">
          <Button type="primary" :loading="qrcode.loading" @click="startQrcode">获取二维码</Button>
          <div v-if="qrcode.image" style="margin-top: 16px">
            <img :src="qrcode.image" width="200" height="200" style="border-radius: 8px" />
            <p style="margin-top: 8px; color: rgba(0, 0, 0, 0.65)">{{ qrcode.message }}</p>
          </div>
        </div>
      </Tabs.TabPane>
      <Tabs.TabPane key="phone" tab="手机号登录">
        <div style="display: flex; gap: 8px; margin-bottom: 8px">
          <Input v-model:value="phone.zone" style="width: 70px" />
          <Input v-model:value="phone.number" placeholder="手机号" />
          <Button :loading="phone.sending" @click="sendPhoneCode">发送验证码</Button>
        </div>
        <div style="display: flex; gap: 8px">
          <Input v-model:value="phone.code" placeholder="验证码" />
          <Button type="primary" :loading="phone.verifying" @click="verifyPhone">
            验证并登录
          </Button>
        </div>
        <p style="margin-top: 8px; color: rgba(0, 0, 0, 0.65)">{{ phone.message }}</p>
      </Tabs.TabPane>
      <Tabs.TabPane key="manual" tab="手动粘贴">
        <TextArea
          v-model:value="manual.cookies"
          :rows="4"
          placeholder="key1=value1; key2=value2; ..."
        />
        <div style="margin-top: 8px; display: flex; gap: 8px">
          <Button type="primary" :loading="manual.saving" @click="saveManualCookie">保存</Button>
          <Button @click="viewFullCookie">查看当前完整值</Button>
          <Button danger @click="clearToken">清除</Button>
        </div>
        <p style="margin-top: 8px; color: rgba(0, 0, 0, 0.65)">{{ manual.message }}</p>
      </Tabs.TabPane>
    </Tabs>
  </Modal>
</template>
