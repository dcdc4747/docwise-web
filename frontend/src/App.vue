<script setup>
/**
 * docwise 前端外壳：**登录分发 + 路由分发 + 各视图挂载点 + 弹层**。
 *
 * 形态与样式**全部照** `frontend/prototype/product-form.html`（设计权威）搬过来——
 * 那部分内容现在拆在 `views/`（库页 / 阅读工作区的模板）与 `stores/`（状态与操作）里，
 * 这个文件只剩"该显示谁"这一层。
 *
 * - 结构：模板里的层级与类名与原型一一对应（topbar / lib-wrap / hero / upload-card /
 *   grid3 / reader-top / thin-bar / note-line / doc-pane / assist / tabs / chips /
 *   thread / guide-card / termlist / composer / sheet / toast …）；
 * - 交互：原型末尾那段命令式 JS 已经**重写成响应式状态**（openMenu / assistTab /
 *   flashId / sheetState / selChip / toast …），不再用 querySelector 查改 DOM；
 *   只有"把某一段滚进视野"本来就必须命令式，用模板 ref 做，不用 getElementById。
 *
 * 三条不能违反的硬约束（都写在 docs/产品形态说明.md 第四节）：
 * ① 出处永远说人话（2026-09-17 口径修订后是「第 X 页 ·「这一句的开头…」」——**不再说第几段**，
 *   段号靠 PDF 版面切分算、在没见过的期刊上只有五六成准，不准的段号比没有更糟；块编号只进 title / 详情）；
 * ② 死链不许做成活链样式（无出处的要点置灰不可点，并说明为什么没有）；
 * ③ 坐标只在有出处时才显示（术语表没有出处字段 → 命中后才回填）。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import { apiUrl } from './api'
import {
  clearToken,
  fetchMe,
  getToken,
  logout as apiLogout,
  setToken,
  setUnauthorizedHandler,
} from './auth'
import AdminView from './components/AdminView.vue'
import LoginView from './components/LoginView.vue'
import TaskPanels from './components/TaskPanels.vue'
import { buildHash, currentRoute, navigate, onRouteChange } from './router'
import { initAsk, lastQuestion } from './stores/useAsk'
import {
  fileInput,
  initLibrary,
  libraryEmpty,
  loadTasksAndSync,
  onFilePicked,
  syncActiveDetail,
  disposeLibrary,
} from './stores/useLibrary'
import {
  blocks,
  currentTask,
  disposeReader,
  initReader,
  loadBlocks,
  openTask,
  pickedBlockId,
  selChip,
  stopProgress,
} from './stores/useReader'
import { clearTasks, tasks } from './stores/useTasks'
import {
  closeMenus,
  disposeUi,
  openMenu,
  runToastUndo,
  setNote,
  showToast,
  syncNarrow,
  toast,
  toggleMenu,
} from './stores/useUi'
import LibraryView from './views/LibraryView.vue'
import ReadView from './views/ReadView.vue'
import { NConfigProvider, NSpin, zhCN, dateZhCN } from 'naive-ui'

// ============================================================ 屏与账号

/** L1 库页 / L2 阅读工作区。回 L1 **不清 currentTask**——后台翻译的进度还要继续推。 */
const view = ref('library')
const authUser = ref(null)
const authChecking = ref(true)
const authNotice = ref('')
const demoAutologin = ref(false)
const showAdmin = ref(false)
const backendStatus = ref('checking')
const healthInfo = ref(null)

const isAdmin = computed(() => authUser.value?.role === 'admin')
const accountLabel = computed(() => {
  const user = authUser.value
  if (!user) return ''
  return `${user.username}（${user.role === 'admin' ? '管理员' : '普通用户'}）`
})

/**
 * 把外壳才有的能力交给 store。
 *
 * `stores/useReader` / `stores/useLibrary` 都**不 import 这个文件**（那就绕成环了），
 * 所以由这里注入——与 `useAsk` 的 `initAsk()` 同一个路子，也与它在一行里调用。
 * 下面的 `navigateToHash` / `loadTasksAndSync` 是函数声明，会提升，所以引用它们是安全的。
 */
initAsk({ blocks, currentTask, loadBlocks })
initReader({ view, navigateToHash, loadTasksAndSync })
initLibrary({ view, navigateToHash })

/** 手机抽屉收起时那一行摘要（要显示"当前问题"，所以依赖 useAsk 的 lastQuestion，
 *  这也正是它不放进 useUi 的原因——放进去两个 store 就绕成环了）。 */
const peekSummary = computed(() =>
  lastQuestion.value
    ? `当前问题：${lastQuestion.value}`
    : '读到有问题的地方，点段落浮出「就这段提问」',
)

// ============================================================ 数据加载（后端健康检查）

async function checkBackend() {
  try {
    const res = await fetch(apiUrl('/api/health'))
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const health = await res.json()
    healthInfo.value = health
    backendStatus.value = health.status === 'ok' ? 'ok' : 'degraded'
    demoAutologin.value = Boolean(health.auth && health.auth.demo_autologin)
  } catch {
    backendStatus.value = 'down'
  }
}

// ============================================================ 哈希路由
//
// 分工：**状态是唯一真源，地址跟着状态走**。
// - 主动切页（点卡片 / 点返回）→ 先改状态，再把地址写上（`openTask` / `backToLibrary`）；
// - 被动切页（用户按后退、改地址栏、刷新）→ 地址变了，`syncFromRoute` 把状态对上。
//
// ⚠️ **防来回触发**：写地址时把目标 hash 记进 `expectedHash`，
// 紧接着到达的那一次 `hashchange` 一看目标一致就知道"是我们自己写的"，直接返回、不重复加载。
// 这个不能省：`openTask` 会真的去拉数据，重复触发就是白白拉两遍。

/** 我们自己刚写下的 hash（= 正在等待的那个 hashchange）。 */
let expectedHash = ''
/** 路由订阅的取消函数（组件卸载时要调，否则监听会越积越多）。 */
let stopRouteWatch = null
/** 启动时的"回原页"只做一次——不能让后续任何一次登录都重新跳一次。 */
let bootRouteApplied = false

/** 改地址，并记下这是"我们自己写的"（广播与去重都在 router.js 里，这里只管接线）。 */
function navigateToHash(target, { replace = false } = {}) {
  const hash = buildHash(target.name, target.params || {})
  if (window.location.hash === hash) return
  expectedHash = hash
  navigate(target.name, target.params || {}, { replace })
}

/** 地址 → 状态的唯一入口。**它只做"该显示什么"，不自己拼地址**（那会绕开 `expectedHash` 防抖）。 */
async function syncFromRoute() {
  const route = currentRoute()

  if (route.name === 'library') {
    if (view.value !== 'library') view.value = 'library'
    return
  }

  if (route.name === 'read') {
    const id = route.params.taskId
    // `router.js` 已经把不合法的任务号挡在外面（落库页），所以走到这里必有 id；
    // 这一段是防御性的：真出现了也别硬编一个号去请求，如实说 + 回库页（replace，免得后退打转）
    if (!id) {
      showToast('这条地址里没有有效的论文编号，已回到「我的论文」')
      navigateToHash({ name: 'library' }, { replace: true })
      return
    }
    if (view.value === 'reader' && currentTask.value?.id === id) return
    const task = tasks.value.find((item) => item.id === id)
    if (!task) {
      // 还没有任务列表（或这一篇不属于当前账号）时，交给后端如实回答：
      // `refreshWorkbench` 对不存在的任务会走既有的报错路径，不在这里硬编一套
      if (!tasks.value.length && getToken()) await loadTasksAndSync()
    }
    const found = tasks.value.find((item) => item.id === id)
    if (!found) {
      showToast('找不到这篇文献——可能已被删除，或不属于当前账号')
      navigateToHash({ name: 'library' }, { replace: true })
      return
    }
    // 状态已经是它了就不重复加载（这是防抖的最后一道，也是刷新时唯一的入口）
    if (view.value === 'reader' && currentTask.value?.id === id) return
    await openTask(found, { skipHash: true })
    return
  }

  // 已经声明、但这一期还没做的页面（#/write、#/memory、#/process、#/me、#/admin）。
  // **不假装能打开**：如实说 + 指出它要做的事，然后回库页，绝不白屏。
  const NOT_BUILT_YET = {
    write: '起草页',
    memory: '记忆页',
    process: '处理过程页',
    me: '个人中心',
    admin: '管理后台',
  }
  if (NOT_BUILT_YET[route.name]) {
    showToast(`${NOT_BUILT_YET[route.name]}还没做（形态 v2 的分期任务），先回「我的论文」`)
    navigateToHash({ name: 'library' }, { replace: true })
  }
}

/** 订阅地址变化。 */
function startRouteWatch() {
  if (stopRouteWatch) return
  stopRouteWatch = onRouteChange((route) => {
    const hash = buildHash(route.name, route.params || {})
    if (hash === expectedHash) {
      expectedHash = '' // 是我们自己写的那一次，状态早就改好了
      return
    }
    syncFromRoute()
  })
}

/** 启动时按地址回到该在的页（刷新不丢页 / PWA 从主屏进来回到原处）。只做一次。 */
async function applyBootRoute() {
  if (bootRouteApplied) return
  bootRouteApplied = true
  const route = currentRoute()
  if (route.name === 'library') return
  await syncFromRoute()
}

// ============================================================ 账号与会话

onMounted(async () => {
  syncNarrow()
  window.addEventListener('resize', syncNarrow)
  window.addEventListener('keydown', onGlobalKeydown)
  setUnauthorizedHandler(handleUnauthorized)
  startRouteWatch()
  await checkBackend()
  await restoreSession()
})

/** Esc 取消段落精读里的选中（和 PDF 视图一个手感）。 */
function onGlobalKeydown(event) {
  if (event.key !== 'Escape') return
  selChip.value = null
  pickedBlockId.value = ''
}

onUnmounted(() => {
  window.removeEventListener('resize', syncNarrow)
  window.removeEventListener('keydown', onGlobalKeydown)
  if (stopRouteWatch) stopRouteWatch()
  stopProgress()
  // 定时器都跟着状态搬进了各自的 store，由它们自己收尾
  // （原来在本地声明，搬走之后这里再 clear 就会报 `xxxTimer is not defined`——上一轮真踩过）
  disposeUi()
  disposeReader()
  disposeLibrary()
})

watch(view, () => {
  if (view.value === 'library') syncActiveDetail()
})

async function restoreSession() {
  authChecking.value = true
  try {
    if (getToken()) {
      authUser.value = await fetchMe()
      await loadTasksAndSync()
      // 任务列表就位之后再按地址回原页（顺序不能反：`#/read/12` 要先能在库里找到 12）
      await applyBootRoute()
    }
  } catch {
    authUser.value = null
  } finally {
    authChecking.value = false
  }
}

async function onLoginSuccess({ token, user, remember }) {
  setToken(token, remember)
  authUser.value = user
  authNotice.value = ''
  showAdmin.value = false
  await loadTasksAndSync()
  // 登录后同样按地址回到该在的页（例：分享出去的 `#/read/12`，登录完直接落在那篇上）
  await applyBootRoute()
}

async function onLogout() {
  closeMenus()
  try {
    await apiLogout()
  } catch {
    clearToken()
  }
  authUser.value = null
  currentTask.value = null
  clearTasks()
  showAdmin.value = false
  stopProgress()
  // 退出后回库页并清掉地址里的那一篇（否则换个账号登录还会去开上一个账号的任务号）；
  // 同时把"启动只做一次"的闸放开，让下一个账号登录时还能按地址落位。
  navigateToHash({ name: 'library' }, { replace: true })
  bootRouteApplied = false
}

function handleUnauthorized() {
  authUser.value = null
  showAdmin.value = false
  stopProgress()
  authNotice.value = '登录已过期，请重新登录'
}
</script>

<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN">
    <!-- 正在用已存令牌恢复登录态 -->
    <div v-if="authChecking" class="boot-screen">
      <n-spin size="large" />
    </div>

    <!-- 未登录：整页登录 / 注册 -->
    <LoginView v-else-if="!authUser" :demo-autologin="demoAutologin" @success="onLoginSuccess" />

    <div v-else class="dw" @click="closeMenus">
      <AdminView v-if="showAdmin" class="admin-page" />

      <template v-else>
        <!-- ==================== L1 库页 ==================== -->
        <section v-if="view === 'library'">
          <div class="topbar">
            <span class="brand">docwise</span>
            <span class="brand-sub">学术文献理解智能体</span>
            <span class="spacer" />
            <span v-if="authNotice" class="tiny" style="color: var(--danger)">{{ authNotice }}</span>
            <button v-if="libraryEmpty" class="btn ghost sm" @click="loadTasksAndSync">我的论文</button>
            <!-- 管理后台收进账号菜单（仅管理员可见），不占顶栏主位 -->
            <div class="menu-wrap">
              <button class="btn ghost sm" @click.stop="toggleMenu('acct')">
                {{ authUser.username }} ▾
              </button>
              <div class="menu" :class="{ open: openMenu === 'acct' }">
                <button @click="setNote('当前账号：' + accountLabel)">{{ accountLabel }}</button>
                <button v-if="isAdmin" @click="showAdmin = true">管理后台</button>
                <button @click="onLogout">退出</button>
              </div>
            </div>
          </div>
          <LibraryView />
        </section>

        <!-- ==================== L2 阅读工作区 ==================== -->
        <section v-else-if="currentTask" class="screen-reader">
          <ReadView :peek-summary="peekSummary" />
        </section>
      </template>

      <!-- 隐藏的文件选择器（上传 / 换档位重译都用它） -->
      <input ref="fileInput" type="file" accept="application/pdf" class="hidden-file" @change="onFilePicked" />

      <!-- 任务弹层：文档信息 / 详情 / 问题反馈 / 删除确认 / 换档位重译 -->
      <TaskPanels />

      <!-- toast：阅读位置提示 / 可撤销的动作 -->
      <div class="toast" :class="{ show: toast.show }">
        <span>{{ toast.text }}</span>
        <button v-if="toast.undoLabel" @click="runToastUndo">{{ toast.undoLabel }}</button>
      </div>
    </div>
  </n-config-provider>
</template>
