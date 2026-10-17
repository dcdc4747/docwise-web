<script setup>
/**
 * 登录 / 注册（E17：**重写成手写**，不再用 Naive UI）。
 *
 * 契约 `契约_前端命名与拆分` §7 定的路数：**校验先抽出去单测，模板只动表现层**，
 * 且 **不许改登录逻辑**。所以这里只有"表现 + 调接口"：
 *
 * - 校验全在 `../authForm.js`（纯函数，有单测）；
 * - 接口调用仍然是 `../auth` 里那三个（`login` / `register` / `demoLogin`），**一个都没换**；
 * - 出错文案照旧往 `error` 里塞，页面底部一条提示。
 *
 * ⚠️ 结构类名保持 `auth-*`（**不在 `.dw` 命名空间里**）：`.dw` 是产品形态的命名空间，
 * 登录页与后台在它之外，样式互不污染。
 * ⚠️ 密码框做成**手写显隐**（原 `show-password-on="click"`）：`type` 在 password/text 间切。
 */
import { computed, ref } from 'vue'

import { login, register, demoLogin } from '../auth'
import { AUTH_HINTS, errorAfterSwitch, isSubmitDisabled, validateCredentials } from '../authForm'

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
const showPassword = ref(false)

const hints = computed(() => AUTH_HINTS[mode.value] || AUTH_HINTS.login)
const submitDisabled = computed(() => isSubmitDisabled({ loading: loading.value }))
const submitLabel = computed(() => hints.value.submit)

/** 切页签：**只清错误，不清输入**（输了半天的用户名不该白输）。 */
function switchMode(next) {
  if (mode.value === next) return
  mode.value = next
  error.value = errorAfterSwitch()
}

async function submit() {
  const checked = validateCredentials({
    mode: mode.value,
    username: username.value,
    password: password.value,
  })
  if (!checked.ok) {
    error.value = checked.error
    return
  }

  loading.value = true
  error.value = ''
  try {
    const data =
      mode.value === 'login'
        ? await login(checked.username, checked.password)
        : await register(checked.username, checked.password)
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

      <!-- 页签：手写两个按钮 + 下划线（原 Naive 的 NTabs，有一模一样的语义） -->
      <div class="auth-tabs" role="tablist" aria-label="登录或注册">
        <button
          type="button"
          class="auth-tab"
          :class="{ on: mode === 'login' }"
          role="tab"
          :aria-selected="mode === 'login' ? 'true' : 'false'"
          data-mode="login"
          @click="switchMode('login')"
        >
          登录
        </button>
        <button
          type="button"
          class="auth-tab"
          :class="{ on: mode === 'register' }"
          role="tab"
          :aria-selected="mode === 'register' ? 'true' : 'false'"
          data-mode="register"
          @click="switchMode('register')"
        >
          注册
        </button>
      </div>

      <div class="auth-form">
        <input
          v-model="username"
          class="auth-input"
          type="text"
          name="username"
          autocomplete="username"
          :placeholder="hints.username"
          :disabled="loading"
          @keydown.enter="submit"
        />

        <div class="auth-pw-row">
          <input
            v-model="password"
            class="auth-input"
            :type="showPassword ? 'text' : 'password'"
            name="password"
            :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
            :placeholder="hints.password"
            :disabled="loading"
            @keydown.enter="submit"
          />
          <button
            type="button"
            class="auth-pw-toggle"
            :aria-label="showPassword ? '隐藏密码' : '显示密码'"
            :title="showPassword ? '隐藏密码' : '显示密码'"
            @click="showPassword = !showPassword"
          >
            {{ showPassword ? '隐藏' : '显示' }}
          </button>
        </div>

        <label v-if="mode === 'login'" class="auth-remember">
          <input v-model="remember" type="checkbox" />
          <span>记住我（这台设备下次自动登录）</span>
        </label>

        <button
          type="button"
          class="auth-submit"
          :disabled="submitDisabled"
          data-action="submit"
          @click="submit"
        >
          {{ loading ? '处理中…' : submitLabel }}
        </button>

        <p v-if="mode === 'register'" class="auth-tip auth-tip-muted">
          第一个注册的账号自动成为管理员（可进管理后台）。
        </p>
      </div>

      <p v-if="error" class="auth-alert" role="alert">{{ error }}</p>

      <div v-if="props.demoAutologin" class="auth-demo">
        <button type="button" class="auth-ghost" :disabled="loading" @click="enterDemo">
          演示账号一键进入
        </button>
        <p class="auth-tip auth-tip-muted">现场演示用；平时该按钮不会出现。</p>
      </div>
    </div>
  </div>
</template>
