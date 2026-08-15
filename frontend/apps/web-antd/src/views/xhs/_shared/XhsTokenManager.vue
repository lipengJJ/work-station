<script lang="ts" setup>
import { computed, onBeforeUnmount, reactive, ref } from 'vue';

import { Button, Input, message, Modal, Select, Tabs } from 'ant-design-vue';

import {
  cancelXhsQrcodeLoginApi,
  getXhsTokenApi,
  pollXhsQrcodeLoginApi,
  sendXhsPhoneCodeApi,
  setXhsTokenApi,
  startXhsQrcodeLoginApi,
  verifyXhsPhoneLoginApi,
} from '#/api/core/xhs';

// 小红书 token 登录弹窗（供系统设置 → 服务凭证复用）。
// 三个 tab：扫码登录 / 验证码登录 / 手动粘贴。前端任何位置都不展示 token 明文
// 或片段；扫码/验证码登录由后端直接把登录态写入 xhs_cookie 配置，前端不接触。
// 登录会话有超时机制（后端 5 分钟），弹窗关闭即释放。

defineOptions({ name: 'XhsTokenManager' });

const modalOpen = ref(false);
const loginTab = ref('qrcode');
const updatedAt = ref<string | null>(null);

const ZONE_OPTIONS: { label: string; value: string }[] = [
  { value: '86', label: '+86' },
  { value: '852', label: '+852' },
  { value: '853', label: '+853' },
  { value: '886', label: '+886' },
];

// ------------------------------------------------------------- 扫码登录 ----
const qrcode = reactive({
  loading: false,
  image: '',
  qrId: '',
  status: 'idle' as 'idle' | 'pending' | 'scanned' | 'expired' | 'success' | 'error',
  message: '',
  expiresAt: 0,
});
let qrcodeTimer: ReturnType<typeof setInterval> | undefined;
let closeTimer: ReturnType<typeof setTimeout> | undefined;
const countdownText = ref('');

function stopPolling() {
  if (qrcodeTimer) {
    clearInterval(qrcodeTimer);
    qrcodeTimer = undefined;
  }
  if (closeTimer) {
    clearTimeout(closeTimer);
    closeTimer = undefined;
  }
}

/** 关闭弹窗/切换 tab 时释放会话 */
function releaseSession() {
  stopPolling();
  if (qrcode.qrId) {
    const id = qrcode.qrId;
    qrcode.qrId = '';
    cancelXhsQrcodeLoginApi(id).catch(() => {});
  }
}

async function startQrcode() {
  stopPolling();
  qrcode.loading = true;
  qrcode.image = '';
  qrcode.status = 'idle';
  qrcode.message = '';
  qrcode.expiresAt = 0;
  try {
    const data = await startXhsQrcodeLoginApi();
    if (data.status !== 'ok' || !data.qr_id || !data.qr_image) {
      qrcode.status = 'error';
      qrcode.message = data.msg || '获取二维码失败';
      return;
    }
    qrcode.image = data.qr_image;
    qrcode.qrId = data.qr_id;
    qrcode.status = 'pending';
    qrcode.message = '请使用小红书 App 扫描二维码';
    qrcode.expiresAt = data.expires_at
      ? new Date(data.expires_at).getTime()
      : Date.now() + 300_000;
    updateCountdown();
    qrcodeTimer = setInterval(pollQrcode, 2000);
  } catch (e: any) {
    qrcode.status = 'error';
    qrcode.message = `获取二维码失败：${e.message}`;
  } finally {
    qrcode.loading = false;
  }
}

function updateCountdown() {
  const left = Math.max(0, Math.floor((qrcode.expiresAt - Date.now()) / 1000));
  const m = Math.floor(left / 60);
  const s = left % 60;
  countdownText.value = `剩余 ${m}:${s.toString().padStart(2, '0')}`;
  if (left > 0) {
    setTimeout(updateCountdown, 1000);
  }
}

async function pollQrcode() {
  if (!qrcode.qrId) return;
  try {
    const s = await pollXhsQrcodeLoginApi(qrcode.qrId);
    if (s.status === 'success') {
      stopPolling();
      qrcode.status = 'success';
      qrcode.message = `登录成功：${s.nickname || ''}`;
      message.success('小红书 token 已保存');
      await refreshUpdatedAt();
      closeTimer = setTimeout(() => {
        modalOpen.value = false;
      }, 1500);
    } else if (s.status === 'scanned') {
      qrcode.status = 'scanned';
      qrcode.message = '已扫描，请在手机上确认';
    } else if (s.status === 'expired') {
      stopPolling();
      qrcode.status = 'expired';
      qrcode.message = s.msg || '二维码已过期';
    } else {
      qrcode.status = 'pending';
      qrcode.message = s.msg || '等待扫码…';
    }
  } catch (e: any) {
    qrcode.status = 'error';
    qrcode.message = `轮询失败：${e.message}`;
  }
}

// ------------------------------------------------------------- 验证码登录 ----
const phone = reactive({
  zone: '86',
  number: '',
  code: '',
  sending: false,
  verifying: false,
  message: '',
  countdown: 0,
});
let phoneTimer: ReturnType<typeof setInterval> | undefined;
const phoneValid = computed(() => /^1\d{10}$/.test(phone.number.trim()));

function validatePhone() {
  if (phone.number.trim() && !phoneValid.value) {
    phone.message = '手机号格式不正确（应为 11 位数字）';
  } else if (phone.message.includes('格式不正确')) {
    phone.message = '';
  }
}

async function sendPhoneCode() {
  if (!phoneValid.value) {
    phone.message = '请输入正确的手机号';
    return;
  }
  phone.sending = true;
  phone.message = '';
  try {
    const res = await sendXhsPhoneCodeApi(phone.number.trim(), phone.zone || '86');
    if (res.success) {
      phone.message = '验证码已发送';
      phone.countdown = 60;
      if (phoneTimer) clearInterval(phoneTimer);
      phoneTimer = setInterval(() => {
        phone.countdown -= 1;
        if (phone.countdown <= 0 && phoneTimer) {
          clearInterval(phoneTimer);
          phoneTimer = undefined;
        }
      }, 1000);
    } else {
      phone.message = `发送失败：${res.msg}`;
    }
  } catch (e: any) {
    phone.message = `发送失败：${e.message}`;
  } finally {
    phone.sending = false;
  }
}

async function verifyPhone() {
  if (!phoneValid.value || !phone.code.trim()) {
    phone.message = '请输入正确的手机号和验证码';
    return;
  }
  phone.verifying = true;
  phone.message = '';
  try {
    const res = await verifyXhsPhoneLoginApi(
      phone.number.trim(),
      phone.code.trim(),
      phone.zone || '86',
    );
    if (res.success) {
      phone.message = `登录成功：${res.nickname || ''}`;
      message.success('小红书 token 已保存');
      await refreshUpdatedAt();
      setTimeout(() => {
        modalOpen.value = false;
      }, 1200);
    } else {
      phone.message = `登录失败：${res.msg}`;
    }
  } catch (e: any) {
    phone.message = `登录失败：${e.message}`;
  } finally {
    phone.verifying = false;
  }
}

// ------------------------------------------------------------- 手动粘贴 ----
const manual = reactive({ cookies: '', saving: false, message: '' });

async function saveManualCookie() {
  const val = manual.cookies.trim();
  manual.saving = true;
  manual.message = '';
  try {
    if (!val) {
      manual.message = '未输入新值，未做修改';
      return;
    }
    await setXhsTokenApi(val);
    manual.message = '保存成功';
    message.success('小红书 token 已保存');
    manual.cookies = '';
    await refreshUpdatedAt();
  } catch (e: any) {
    manual.message = `保存失败：${e.message}`;
  } finally {
    manual.saving = false;
  }
}

// ------------------------------------------------------------- 通用 ----
async function refreshUpdatedAt() {
  try {
    const st = await getXhsTokenApi();
    updatedAt.value = st.updated_at
      ? new Date(st.updated_at).toLocaleString('zh-CN', { hour12: false })
      : null;
  } catch {
    /* 忽略状态刷新失败 */
  }
}

function open() {
  modalOpen.value = true;
  loginTab.value = 'qrcode';
  refreshUpdatedAt();
  startQrcode();
}

defineExpose({ open });

onBeforeUnmount(() => {
  stopPolling();
  if (phoneTimer) clearInterval(phoneTimer);
});
</script>

<template>
  <Modal
    v-model:open="modalOpen"
    title="小红书 token"
    :footer="null"
    width="480px"
    :after-close="releaseSession"
  >
    <Tabs v-model:active-key="loginTab" @change="releaseSession">
      <!-- ===================== 扫码登录 ===================== -->
      <Tabs.TabPane key="qrcode" tab="扫码登录">
        <div style="text-align: center; padding: 4px 0">
          <div v-if="qrcode.loading" style="padding: 40px 0">
            <span class="text-[hsl(var(--muted-foreground))]">正在获取二维码…</span>
          </div>
          <div v-else-if="qrcode.image" style="position: relative; display: inline-block">
            <img
              :src="qrcode.image"
              width="200"
              height="200"
              :style="{ borderRadius: '8px', filter: qrcode.status === 'expired' ? 'grayscale(1)' : 'none' }"
            />
            <!-- 已扫描待确认遮罩 -->
            <div
              v-if="qrcode.status === 'scanned'"
              class="absolute inset-0 flex items-center justify-center rounded-lg"
              style="background: rgba(0, 0, 0, 0.45)"
            >
              <span class="text-sm font-medium text-white">已扫描，请在手机上确认</span>
            </div>
            <!-- 已过期遮罩 -->
            <div
              v-if="qrcode.status === 'expired'"
              class="absolute inset-0 flex flex-col items-center justify-center gap-2 rounded-lg"
              style="background: rgba(0, 0, 0, 0.55)"
            >
              <span class="text-sm font-medium text-white">二维码已过期</span>
              <Button size="small" @click="startQrcode">点击刷新</Button>
            </div>
          </div>
          <p style="margin-top: 10px; font-size: 12px; color: hsl(var(--muted-foreground))">
            {{ qrcode.message || '使用小红书 App 扫码登录' }}
          </p>
          <p v-if="qrcode.status === 'pending' && countdownText" style="font-size: 12px; color: hsl(var(--muted-foreground))">
            {{ countdownText }}
          </p>
          <Button
            v-if="!qrcode.image && qrcode.status === 'error'"
            style="margin-top: 8px"
            @click="startQrcode"
          >
            重新获取
          </Button>
        </div>
      </Tabs.TabPane>

      <!-- ===================== 验证码登录 ===================== -->
      <Tabs.TabPane key="phone" tab="验证码登录">
        <div style="display: flex; flex-direction: column; gap: 10px">
          <div style="display: flex; gap: 8px">
            <Select
              v-model:value="phone.zone"
              style="width: 100px"
              :options="ZONE_OPTIONS"
            />
            <Input
              v-model:value="phone.number"
              placeholder="手机号"
              :maxlength="11"
              @blur="validatePhone"
            />
          </div>
          <div style="display: flex; gap: 8px">
            <Input
              v-model:value="phone.code"
              placeholder="验证码"
              :maxlength="6"
              @press-enter="verifyPhone"
            />
            <Button
              :disabled="!phoneValid || phone.countdown > 0"
              :loading="phone.sending"
              style="width: 150px"
              @click="sendPhoneCode"
            >
              {{ phone.countdown > 0 ? `重新获取(${phone.countdown}s)` : '获取验证码' }}
            </Button>
          </div>
          <p style="font-size: 12px; color: hsl(var(--muted-foreground))">{{ phone.message }}</p>
          <Button
            type="primary"
            block
            :disabled="!phoneValid || !phone.code.trim()"
            :loading="phone.verifying"
            @click="verifyPhone"
          >
            登录并保存
          </Button>
        </div>
      </Tabs.TabPane>

      <!-- ===================== 手动粘贴 ===================== -->
      <Tabs.TabPane key="manual" tab="手动粘贴">
        <div style="display: flex; flex-direction: column; gap: 8px">
          <Input.Password
            v-model:value="manual.cookies"
            :visibility-toggle="true"
            placeholder="粘贴新的小红书登录态 cookie（留空则不修改）"
          />
          <Button type="primary" block :loading="manual.saving" @click="saveManualCookie">
            保存
          </Button>
          <p style="font-size: 12px; color: hsl(var(--muted-foreground))">{{ manual.message }}</p>
        </div>
      </Tabs.TabPane>
    </Tabs>

    <!-- 上次更新时间（不展示任何 token 值） -->
    <div
      v-if="updatedAt"
      style="margin-top: 14px; padding-top: 10px; border-top: 1px solid hsl(var(--border)); font-size: 12px; color: hsl(var(--muted-foreground))"
    >
      上次更新时间：{{ updatedAt }}
    </div>
    <div style="margin-top: 6px; font-size: 11px; color: hsl(var(--muted-foreground)); opacity: 0.7">
      登录会话 5 分钟内有效，关闭弹窗即释放
    </div>
  </Modal>
</template>
