<script setup>
import { ref } from 'vue'
import { NAlert, NButton, NInput, NTabPane, NTabs, NText } from 'naive-ui'
import { login, register, demoLogin } from '../auth'

const props = defineProps({
  /** 是否显示「演示账号一键进入」（由后端 /api/health 的 auth.demo_autologin 决定） */
  demoAutologin: { type: Boolean, default: false },
})

const emit = defineEmits(['success'])

const mode = ref('login')
const username = ref('')
const password = ref('')
const remember = ref(true)
const loading = ref(false)
const error = ref('')

async function submit() {
  const name = (username.value || '').trim()
  if (!name || !password.value) {
    error.value = '请填写用户名和密码'
    return
  }
  if (mode.value === 'register' && password.value.length < 8) {
    error.value = '密码至少 8 位'
    return
  }

  loading.value = true
  error.value = ''
  try {
    const data =
      mode.value === 'login'
        ? await login(name, password.value)
        : await register(name, password.value)
    emit('success', { ...data, remember: remember.value })
  } catch (err) {
    error.value = err.message || '操作失败，请重试'
  } finally {
    loading.value = false
  }
}

async function enterDemo() {
  loading.value = true
  error.value = ''
  try {
    const data = await demoLogin()
    emit('success', { ...data, remember: true })
  } catch (err) {
    error.value = err.message || '演示登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-brand">
        <span class="auth-logo">docwise</span>
        <span class="auth-sub">学术文献理解智能体</span>
      </div>
      <p class="auth-slogan">翻译只是起点，理解才是价值</p>

      <n-tabs v-model:value="mode" type="line" size="small" animated>
        <n-tab-pane name="login" tab="登录">
          <div class="auth-form">
            <n-input
              v-model:value="username"
              placeholder="用户名"
              :disabled="loading"
              @keydown.enter="submit"
            />
            <n-input
              v-model:value="password"
              type="password"
              show-password-on="click"
              placeholder="密码"
              :disabled="loading"
              @keydown.enter="submit"
            />
            <label class="auth-remember">
              <input v-model="remember" type="checkbox" />
              <span>记住我（这台设备下次自动登录）</span>
            </label>
            <n-button type="primary" block :loading="loading" @click="submit">
              登录
            </n-button>
          </div>
        </n-tab-pane>

        <n-tab-pane name="register" tab="注册">
          <div class="auth-form">
            <n-input
              v-model:value="username"
              placeholder="用户名（3–32 位，字母/数字/下划线）"
              :disabled="loading"
            />
            <n-input
              v-model:value="password"
              type="password"
              show-password-on="click"
              placeholder="密码（至少 8 位）"
              :disabled="loading"
              @keydown.enter="submit"
            />
            <n-button type="primary" block :loading="loading" @click="submit">
              注册并进入
            </n-button>
            <n-text depth="3" class="auth-tip">
              第一个注册的账号自动成为管理员（可进管理后台）。
            </n-text>
          </div>
        </n-tab-pane>
      </n-tabs>

      <n-alert v-if="error" type="error" :show-icon="true" class="auth-error">
        {{ error }}
      </n-alert>

      <div v-if="props.demoAutologin" class="auth-demo">
        <n-button block :loading="loading" @click="enterDemo">
          演示账号一键进入
        </n-button>
        <n-text depth="3" class="auth-tip">现场演示用；平时该按钮不会出现。</n-text>
      </div>
    </div>
  </div>
</template>
