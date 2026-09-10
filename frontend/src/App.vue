<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { apiUrl } from './api'
import {
  authFetch,
  clearToken,
  fetchMe,
  getToken,
  logout as apiLogout,
  setToken,
  setUnauthorizedHandler,
  urlWithTicket,
} from './auth'
import LoginView from './components/LoginView.vue'
import AdminView from './components/AdminView.vue'
import {
  zhCN,
  dateZhCN,
  NConfigProvider,
  NLayout,
  NLayoutHeader,
  NLayoutContent,
  NLayoutFooter,
  NGrid,
  NGi,
  NCard,
  NTag,
  NUpload,
  NUploadDragger,
  NText,
  NProgress,
  NAlert,
  NButton,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NRadioButton,
  NRadioGroup,
  NSpace,
  NSpin,
  NInput,
  NTabs,
  NTabPane,
} from 'naive-ui'

const backendStatus = ref('checking')
const healthInfo = ref(null)
const taskCount = ref(null)
const uploading = ref(false)
const uploadError = ref('')
const currentTask = ref(null)
const uploadRef = ref(null)
const previewMode = ref('mono')
const previewSrc = ref('')
const fileAvailability = ref({ mono: false, dual: false })
const previewCheckDone = ref(false)
const previewLoading = ref(true)
const selectedTier = ref('fast')
const workbenchError = ref('')

// ---- 账号（B 批）：登录态、管理后台入口、演示一键登录开关 ----
const authUser = ref(null)
const authChecking = ref(true)
const authNotice = ref('')
const demoAutologin = ref(false)
const showAdmin = ref(false)

// ---- 阅读工作台（理解层：导读 / 术语表 / 点溯源）----
const workbenchTab = ref('bilingual')
const understandingLoading = ref(false)
const understandingStatus = ref('pending')
const understandingGuide = ref(null)
const understandingTerms = ref([])
const understandingError = ref('')
// 本任务是否已自动尝试生成过（避免失败后每次切页签都重复调 LLM 烧钱）
const understandingTried = ref(false)
const blocksById = ref({})
const traceVisible = ref(false)
const tracePoint = ref(null)

// ---- 论文问答（M4：全量入上下文 + FTS5 兜底，回答带出处）----
const askQuestion = ref('')
const askLoading = ref(false)
const askResult = ref(null)
const askError = ref('')

async function submitAsk() {
  const q = (askQuestion.value || '').trim()
  if (!q || askLoading.value || !currentTask.value) return
  askLoading.value = true
  askError.value = ''
  askResult.value = null
  try {
    if (!Object.keys(blocksById.value).length) {
      await loadBlocks(currentTask.value.id)
    }
    const res = await authFetch(`/api/tasks/${currentTask.value.id}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail || `问答失败（HTTP ${res.status}）`)
    }
    askResult.value = await res.json()
  } catch (err) {
    askError.value = err.message || '问答失败，请重试'
  } finally {
    askLoading.value = false
  }
}

const guideFields = ['research_question', 'method', 'conclusion', 'innovation', 'contribution']
const guideFieldLabel = {
  research_question: '研究问题',
  method: '方法',
  conclusion: '结论',
  innovation: '创新点',
  contribution: '核心贡献',
}

const tierOptions = [
  { value: 'fast', label: '快', desc: '速度优先' },
  { value: 'medium', label: '中', desc: '质量与速度平衡' },
  { value: 'precise', label: '慢', desc: '质量优先' },
]

const tierTextMap = {
  fast: '快',
  medium: '中',
  precise: '慢',
}

const tasks = ref([])
const historyLoading = ref(false)
const historyError = ref('')

const drawerVisible = ref(false)
const detailTaskId = ref(null)
const detailTitle = ref('')
const detailLoading = ref(false)
const detailError = ref('')
const detailTask = ref(null)

const statusMeta = {
  checking: { type: 'default', text: '检测中…' },
  ok: { type: 'success', text: '已连接' },
  degraded: { type: 'warning', text: '部分异常（数据库或后台处理程序）' },
  down: { type: 'error', text: '未连接（请先启动后端）' },
}

const statusTextMap = {
  pending: '等待中',
  in_progress: '翻译中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const statusTypeMap = {
  pending: 'default',
  in_progress: 'info',
  completed: 'success',
  failed: 'error',
  cancelled: 'warning',
}

// 终态：到了这里进度推送就收工（E 批加了"已取消"）
const TERMINAL_STATES = ['completed', 'failed', 'cancelled']
// 可以重试的状态（失败 / 已取消）
const RETRYABLE_STATES = ['failed', 'cancelled']

const blockStatusMeta = {
  success: { type: 'success', text: '成功' },
  overflow: { type: 'warning', text: '溢出' },
  failed: { type: 'error', text: '失败' },
}

let eventSource = null
let pollTimer = null

onMounted(async () => {
  setUnauthorizedHandler(handleUnauthorized)
  await checkBackend()
  await restoreSession()
})

/** 后端状态（公开接口，无需登录）。 */
async function checkBackend() {
  try {
    const res = await fetch(apiUrl('/api/health'))
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    // 后端返回"真检查"结果：数据库可写？后台处理程序心跳新鲜？队列排了几篇？
    const health = await res.json()
    healthInfo.value = health
    backendStatus.value = health.status === 'ok' ? 'ok' : 'degraded'
    demoAutologin.value = Boolean(health.auth && health.auth.demo_autologin)
  } catch {
    backendStatus.value = 'down'
  }
}

/** 用已存令牌恢复登录态（没有令牌或令牌失效就显示登录页）。 */
async function restoreSession() {
  authChecking.value = true
  try {
    if (getToken()) {
      authUser.value = await fetchMe()
      await loadTasks()
    }
  } catch {
    authUser.value = null // 令牌失效时 auth.js 已清掉本地令牌
  } finally {
    authChecking.value = false
  }
}

function handleUnauthorized() {
  authUser.value = null
  showAdmin.value = false
  stopProgress()
  authNotice.value = '登录已过期，请重新登录'
}

async function onLoginSuccess({ token, user, remember }) {
  setToken(token, remember)
  authUser.value = user
  authNotice.value = ''
  showAdmin.value = false
  await loadTasks()
}

async function onLogout() {
  try {
    await apiLogout()
  } catch {
    clearToken()
  }
  authUser.value = null
  currentTask.value = null
  tasks.value = []
  taskCount.value = null
  showAdmin.value = false
  stopProgress()
}

function progressPercent() {
  if (!currentTask.value) return 0
  // 优先用引擎刚报的页进度：库里那份是后台每 1.5 秒搬一次的，最多会旧 1.5 秒，
  // 而详情接口里的 engine_progress 是当场从日志里解析的（更准）
  if (isRunningTask(currentTask.value) && engineProgress.value) {
    return Math.round((engineProgress.value.percent ?? 0) * 100)
  }
  return Math.round((currentTask.value.progress ?? 0) * 100)
}

// ---- 诚实进度（F 批）----
// 进度、阶段、预计剩余全部来自后端（后端又是从引擎自己的进度条里读的）；
// 读不到就不显示，绝不编一个百分比糊弄人。
const engineProgress = ref(null)
let elapsedBase = { seconds: 0, at: Date.now() }
const elapsedTick = ref(Date.now())
let elapsedTimer = null

function startElapsedTimer() {
  if (elapsedTimer) return
  elapsedTimer = setInterval(() => {
    elapsedTick.value = Date.now()
  }, 1000)
}

function stopElapsedTimer() {
  if (elapsedTimer) {
    clearInterval(elapsedTimer)
    elapsedTimer = null
  }
}

/** 记录后端给的"已耗时"，然后本地走秒（避免手机与电脑时钟不一致时数字乱跳）。 */
function rememberElapsed(task) {
  if (!task || typeof task.elapsed_seconds !== 'number') return
  elapsedBase = { seconds: task.elapsed_seconds, at: Date.now() }
  elapsedTick.value = Date.now()
}

function isRunningTask(task) {
  return !!task && task.status === 'in_progress'
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  if (minutes <= 0) return `${rest} 秒`
  return `${minutes} 分 ${rest} 秒`
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// —— 下面几个是模板里直接用的"诚实进度"文案（读到的都是真实数据）——
// 一律用 computed 而不是普通函数：模板里写 {{ stageText }} 也能正常取值，
// 不会再出现"少写一对括号 → Vue 把函数 toString 印在页面上"的低级事故。

const isRunning = computed(() => isRunningTask(currentTask.value))

const hasEngineProgress = computed(() => !!engineProgress.value)

const stageText = computed(() => {
  const task = currentTask.value
  if (!task) return ''
  if (task.status === 'pending') {
    const ahead = task.queue_position
    return ahead ? `排队中 · 前面还有 ${ahead} 篇` : '排队中'
  }
  if (task.status === 'in_progress') {
    const engine = engineProgress.value
    // 引擎还没打进度条时，只说"还在准备"，不把内部实现细节（抽结构/加载模型）端给用户
    if (!engine) return '正在翻译 · 引擎还在准备'
    const rate = engine.rate ? ` · ${engine.rate.toFixed(2)} 页/秒` : ''
    return `正在翻译 · 第 ${engine.done}/${engine.total} 页${rate}`
  }
  if (task.status === 'completed') return '翻译完成'
  if (task.status === 'cancelled') return '已取消'
  return '翻译失败'
})

const elapsedText = computed(() => {
  const task = currentTask.value
  if (!task || !task.started_at) return ''
  const running = isRunningTask(task)
  const drift = running
    ? Math.max(0, (elapsedTick.value - elapsedBase.at) / 1000)
    : 0
  const seconds = elapsedBase.seconds + drift
  // 刚点下去显示"已用 0 秒"很傻，满一秒再说
  if (running && seconds < 1) return ''
  return `${running ? '已用' : '总耗时'} ${formatDuration(seconds)}`
})

const etaText = computed(() => {
  const task = currentTask.value
  if (!task || !isRunningTask(task)) return ''
  // 引擎自报 0 秒时不必写出来（tqdm 会四舍五入到 0，那不是"马上好"，只是精度不够）
  if (typeof task.eta_seconds !== 'number' || task.eta_seconds <= 0) return ''
  return `引擎预计还需 ${formatDuration(task.eta_seconds)}`
})

async function loadTasks() {
  historyLoading.value = true
  historyError.value = ''
  try {
    const res = await authFetch('/api/tasks')
    if (!res.ok) throw new Error(`历史任务加载失败（HTTP ${res.status}）`)
    tasks.value = await res.json()
    taskCount.value = tasks.value.length
  } catch (err) {
    historyError.value = err.message || '历史任务加载失败'
  } finally {
    historyLoading.value = false
  }
}

async function fetchTaskDetail(taskId) {
  detailLoading.value = true
  detailError.value = ''
  try {
    const res = await authFetch(`/api/tasks/${taskId}`)
    if (!res.ok) throw new Error(`任务详情加载失败（HTTP ${res.status}）`)
    const data = await res.json()
    detailTask.value = data
    return data
  } catch (err) {
    detailError.value = err.message || '任务详情加载失败'
    return null
  } finally {
    detailLoading.value = false
  }
}

function openTaskDetail(task) {
  detailTaskId.value = task.id
  detailTitle.value = task.filename
  drawerVisible.value = true
  detailTask.value = null
  fetchTaskDetail(task.id)
}

// ---- 任务生命周期动作（E 批）：取消 / 重试 / 删除 ----
const taskActionBusy = ref(false)
const taskActionError = ref('')
// 删除是破坏性操作：先点一次"删除"进入确认态，再点"确认删除"才真删
const deleteConfirmId = ref(null)

async function cancelTask(task) {
  taskActionBusy.value = true
  taskActionError.value = ''
  try {
    const res = await authFetch(`/api/tasks/${task.id}/cancel`, { method: 'POST' })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(body.detail || `取消失败（HTTP ${res.status}）`)
    await loadTasks()
    // 正在跑的会在半秒内停下来（worker 会推 cancelled 事件），这里先刷新一次状态
    if (currentTask.value?.id === task.id) await refreshWorkbench(task.id)
  } catch (err) {
    taskActionError.value = err.message || '取消失败'
  } finally {
    taskActionBusy.value = false
  }
}

async function retryTask(task) {
  taskActionBusy.value = true
  taskActionError.value = ''
  try {
    const res = await authFetch(`/api/tasks/${task.id}/retry`, { method: 'POST' })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(body.detail || `重试失败（HTTP ${res.status}）`)
    await loadTasks()
    if (currentTask.value?.id === task.id) await openWorkbench(body)
  } catch (err) {
    taskActionError.value = err.message || '重试失败'
  } finally {
    taskActionBusy.value = false
  }
}

async function deleteTask(task) {
  taskActionBusy.value = true
  taskActionError.value = ''
  try {
    const res = await authFetch(`/api/tasks/${task.id}`, { method: 'DELETE' })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(body.detail || `删除失败（HTTP ${res.status}）`)
    deleteConfirmId.value = null
    // 删掉的正好是当前打开的任务：工作台与详情抽屉一起收起来
    if (currentTask.value?.id === task.id) {
      stopProgress()
      currentTask.value = null
    }
    if (detailTaskId.value === task.id) drawerVisible.value = false
    await loadTasks()
  } catch (err) {
    taskActionError.value = err.message || '删除失败'
  } finally {
    taskActionBusy.value = false
  }
}

// ---- 统一的"打开任务到阅读工作台"：上传完成后与历史回看走同一条路径 ----
const workbenchRef = ref(null)

function resetUnderstanding() {
  understandingLoading.value = false
  understandingStatus.value = 'pending'
  understandingGuide.value = null
  understandingTerms.value = []
  understandingError.value = ''
  understandingTried.value = false
}

function applyUnderstanding(data) {
  understandingStatus.value = data.status || 'pending'
  understandingGuide.value = data.guide || null
  understandingTerms.value = data.terms || []
  understandingError.value = data.error || ''
}

function pickPreviewMode() {
  const { mono, dual } = fileAvailability.value
  if (!mono && dual) previewMode.value = 'dual'
  else if (!dual && mono) previewMode.value = 'mono'
}

/** 取任务全量信息（块 + 文件就绪 + 导读状态），刷新工作台。 */
async function refreshWorkbench(taskId) {
  const data = await fetchTaskDetail(taskId)
  if (!data) return
  currentTask.value = { ...(currentTask.value || {}), ...data }
  // 诚实进度：把后端给的阶段/耗时/引擎进度接过来（没有就是 null，界面显示"没报进度"）
  engineProgress.value = data.engine_progress || null
  rememberElapsed(data)
  if (isRunningTask(data)) startElapsedTimer()
  else stopElapsedTimer()
  blocksById.value = Object.fromEntries(
    (data.blocks || []).map((b) => [b.block_id, b]),
  )
  fileAvailability.value = data.files_ready || { mono: false, dual: false }
  pickPreviewMode()
  previewCheckDone.value = true
  previewLoading.value = false
  await refreshPreviewUrl()
  // 已经算过导读/术语就直接取缓存，没算过则等用户打开页签再算（惰性）
  if (data.understanding_status === 'ready') {
    loadUnderstanding(taskId)
  }
}

/** 打开任意任务到阅读工作台（历史回看 / 上传后 / 轮询恢复都走这里）。 */
async function openWorkbench(task) {
  stopProgress()
  currentTask.value = task
  workbenchTab.value = 'bilingual'
  previewCheckDone.value = false
  previewLoading.value = true
  fileAvailability.value = { mono: false, dual: false }
  engineProgress.value = null
  rememberElapsed(task)
  resetUnderstanding()
  askQuestion.value = ''
  askResult.value = null
  askError.value = ''
  scrollToWorkbench()

  const data = await refreshWorkbench(task.id)
  if (['pending', 'in_progress'].includes(task.status)) startProgress(task.id)
  return data
}
function scrollToWorkbench() {
  requestAnimationFrame(() => {
    workbenchRef.value?.$el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

async function handleUpload({ file: fileInfo, onFinish, onError }) {
  uploading.value = true
  uploadError.value = ''
  currentTask.value = null
  previewCheckDone.value = false
  previewLoading.value = false
  fileAvailability.value = { mono: false, dual: false }
  resetUnderstanding()
  askQuestion.value = ''
  askResult.value = null
  askError.value = ''
  stopProgress()

  const form = new FormData()
  form.append('file', fileInfo.file)
  form.append('tier', selectedTier.value)

  try {
    const res = await authFetch('/api/tasks/upload', { method: 'POST', body: form })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail || `上传失败（HTTP ${res.status}）`)
    }
    const task = await res.json()
    currentTask.value = task
    workbenchTab.value = 'bilingual'
    engineProgress.value = null
    rememberElapsed(task)
    startElapsedTimer()
    onFinish()
    startProgress(task.id)
    scrollToWorkbench()
  } catch (err) {
    uploadError.value = err.message || '上传失败，请重试'
    onError()
  } finally {
    uploading.value = false
    loadTasks()
    // 关键：naive-ui 的 onFinish() 只把文件标成 finished，**不会从内部文件列表里移除**
    // （Upload.mjs: onFinish -> doChange({status:'finished'})）。配上 :max="1"，
    // 列表长度已到 1 → maxReached 为真 → 触发器点击直接 return、拖入的文件被
    // slice(0,0) 丢掉，表现就是"翻译完再想传一篇，点也没反应、拖也没反应"。
    // 这里手动清空列表，恢复可上传（工作台上已经有文件名了，列表不需要留着）。
    uploadRef.value?.clear()
  }
}

function handleFilesChange({ fileList }) {
  // 选择/拖拽文件后自动提交，进入翻译任务
  if (fileList.length && fileList.some((f) => f.status === 'pending')) {
    // Naive UI 在 on-change 回调时内部列表尚未更新，推迟到下一轮事件循环再提交
    setTimeout(() => uploadRef.value?.submit(), 0)
  }
}

async function startProgress(taskId) {
  stopProgress()
  // EventSource 带不了请求头，所以先用令牌换一张 events 用途的票据
  let url
  try {
    url = await urlWithTicket(`/api/tasks/${taskId}/events`, taskId, 'events')
  } catch {
    startPolling(taskId)
    return
  }
  const es = new EventSource(url)
  eventSource = es
  es.onmessage = (e) => {
    let evt
    try {
      evt = JSON.parse(e.data)
    } catch {
      return
    }
    applyEvent(evt)
    if (TERMINAL_STATES.includes(evt.type)) stopProgress()
  }
  es.onerror = () => {
    // SSE 断开时轮询兜底，避免进度卡死
    stopProgress()
    startPolling(taskId)
  }
}

function startPolling(taskId) {
  pollTimer = setInterval(async () => {
    try {
      const res = await authFetch(`/api/tasks/${taskId}`)
      if (!res.ok) return
      const task = await res.json()
      // 轮询兜底也要把"阶段/耗时/引擎进度"接过来（否则断线后进度就不动了）
      engineProgress.value = task.engine_progress || null
      rememberElapsed(task)
      applyEvent({
        type: task.status,
        status: task.status,
        progress: task.progress,
        eta_seconds: task.eta_seconds,
        error: task.error_message,
      })
      if (TERMINAL_STATES.includes(task.status)) stopProgress()
    } catch {
      // 后端暂不可达，等待下一轮
    }
  }, 2000)
}

function applyEvent(evt) {
  if (!currentTask.value) return
  currentTask.value.status = evt.status || currentTask.value.status
  if (typeof evt.progress === 'number') currentTask.value.progress = evt.progress
  if (evt.error) currentTask.value.error_message = evt.error
  // 诚实进度：SSE 会把引擎自报的页进度与预计剩余一起推过来
  if (typeof evt.eta_seconds === 'number' || evt.eta_seconds === null) {
    currentTask.value.eta_seconds = evt.eta_seconds
  }
  if (typeof evt.engine_done === 'number' && typeof evt.engine_total === 'number') {
    engineProgress.value = {
      done: evt.engine_done,
      total: evt.engine_total,
      percent: evt.progress ?? 0,
      eta_seconds: evt.eta_seconds ?? null,
      rate: evt.engine_rate ?? null,
    }
    startElapsedTimer()
  }
  if (TERMINAL_STATES.includes(evt.type)) {
    // 终态：没有阶段、没有预计剩余，进度条收在终值上
    engineProgress.value = null
    stopElapsedTimer()
    currentTask.value.stage = null
    currentTask.value.eta_seconds = null
    loadTasks()
    // 完成后一次性取全（块 + 文件就绪 + 导读状态），不再单独探测
    if (evt.type === 'completed') refreshWorkbench(currentTask.value.id)
  }
}

/** 预览地址带文件票据（iframe 也是浏览器发起的请求，带不了请求头）。 */
async function refreshPreviewUrl() {
  if (!currentTask.value || !fileAvailability.value[previewMode.value]) {
    previewSrc.value = ''
    return
  }
  try {
    previewSrc.value = await urlWithTicket(
      `/api/tasks/${currentTask.value.id}/files/${previewMode.value}`,
      currentTask.value.id,
      'files',
    )
  } catch {
    previewSrc.value = ''
  }
}

/** 下载：先换票据再把浏览器导航过去（<a href> 同样带不了请求头）。 */
async function downloadFile(kind) {
  if (!currentTask.value) return
  workbenchError.value = ''
  try {
    const url = await urlWithTicket(
      `/api/tasks/${currentTask.value.id}/files/${kind}?download=1`,
      currentTask.value.id,
      'files',
    )
    window.location.assign(url)
  } catch (err) {
    workbenchError.value = err.message || '下载失败，请重试'
  }
}

function stopProgress() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  stopElapsedTimer()
}

/** 历史列表里那一小行状态说明（同样是真实数据：排队位置 / 已用 / 引擎自报剩余）。 */
function rowProgressText(task) {
  if (task.status === 'in_progress') {
    const percent = Math.round((task.progress ?? 0) * 100)
    const parts = [`翻译中 ${percent}%`]
    if (typeof task.elapsed_seconds === 'number') {
      parts.push(`已用 ${formatDuration(task.elapsed_seconds)}`)
    }
    if (typeof task.eta_seconds === 'number' && task.eta_seconds > 0) {
      parts.push(`引擎预计还需 ${formatDuration(task.eta_seconds)}`)
    }
    return parts.join(' · ')
  }
  if (task.status === 'pending') return '排队中'
  if (typeof task.elapsed_seconds === 'number' && task.elapsed_seconds > 0) {
    return `总耗时 ${formatDuration(task.elapsed_seconds)}`
  }
  return ''
}

async function loadBlocks(taskId) {
  try {
    const res = await authFetch(`/api/tasks/${taskId}`)
    if (!res.ok) return
    const data = await res.json()
    const map = {}
    ;(data.blocks || []).forEach((b) => { map[b.block_id] = b })
    blocksById.value = map
  } catch { /* ignore */ }
}

async function loadUnderstanding(taskId, { generate = false } = {}) {
  if (!taskId) return
  understandingLoading.value = true
  try {
    let res = await authFetch(`/api/tasks/${taskId}/understanding`)
    if (!res.ok) throw new Error(`加载失败（HTTP ${res.status}）`)
    let data = await res.json()
    if (generate && data.status !== 'ready') {
      // 惰性：用户打开"导读/术语表"页签时才触发计算（每个任务只自动试一次）
      understandingTried.value = true
      const post = await authFetch(`/api/tasks/${taskId}/understanding`, {
        method: 'POST',
      })
      if (post.ok) data = await post.json()
    }
    applyUnderstanding(data)
  } catch (err) {
    understandingStatus.value = 'failed'
    understandingError.value = err.message || '理解层加载失败'
  } finally {
    understandingLoading.value = false
  }
}

function retryUnderstanding() {
  if (!currentTask.value) return
  understandingTried.value = false
  loadUnderstanding(currentTask.value.id, { generate: true })
}

function switchWorkbenchTab(tab) {
  workbenchTab.value = tab
  if (tab !== 'guide' && tab !== 'terms') return
  if (!currentTask.value) return
  if (understandingLoading.value || understandingStatus.value === 'ready') return
  if (understandingTried.value) return // 失败过就不再自动重试，交给"重试"按钮
  loadUnderstanding(currentTask.value.id, { generate: true })
}

function openTrace(point) {
  tracePoint.value = point
  traceVisible.value = true
}

function sourceBlockText() {
  const ids = (tracePoint.value && tracePoint.value.source) || []
  const id = ids[0]
  return id ? (blocksById.value[id] || null) : null
}

onUnmounted(stopProgress)
</script>

<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN">
    <!-- 正在用已存令牌恢复登录态 -->
    <div v-if="authChecking" class="boot-screen">
      <n-spin size="large" />
    </div>

    <!-- 未登录：整页登录 / 注册 -->
    <LoginView
      v-else-if="!authUser"
      :demo-autologin="demoAutologin"
      @success="onLoginSuccess"
    />

    <n-layout v-else class="page-layout">
      <n-layout-header bordered class="page-header">
        <div class="page-header-inner">
          <span class="brand">docwise</span>
          <span class="brand-sub">学术文献理解智能体</span>
          <span class="header-spacer" />
          <n-text depth="3" v-if="authNotice" class="header-notice">
            {{ authNotice }}
          </n-text>
          <n-button
            size="small"
            quaternary
            @click="showAdmin = !showAdmin"
          >
            {{ showAdmin ? '返回阅读' : '我的论文' }}
          </n-button>
          <n-button
            v-if="authUser.role === 'admin'"
            size="small"
            quaternary
            @click="showAdmin = true"
          >
            管理后台
          </n-button>
          <n-text depth="3" class="header-user">{{ authUser.username }}</n-text>
          <n-button size="small" quaternary @click="onLogout">退出</n-button>
        </div>
      </n-layout-header>

      <n-layout-content content-style="padding: 0">
        <main class="page-main">
          <AdminView v-if="showAdmin" />
          <template v-else>
          <section class="page-hero">
            <h1>把英文文献读懂</h1>
            <p class="tagline">翻译只是起点，理解才是价值</p>
            <p class="description">
              上传英文文献 PDF，得到双语对照稿、结构化导读与统一术语表；
              还能就论文提问，每条答案都标明来自哪一段原文。
            </p>
            <div class="tech-tags">
              <n-tag round type="info">结构化导读</n-tag>
              <n-tag round type="info">统一术语表</n-tag>
              <n-tag round type="success">带出处问答</n-tag>
            </div>
          </section>

          <section class="page-section">
            <n-card title="上传英文文献 PDF" class="upload-card">
              <div class="tier-picker">
                <div class="tier-picker-head">
                  <n-text strong>翻译档位</n-text>
                  <n-text depth="3" class="tier-picker-sub">
                    档位影响速度与质量，请在上传前选择
                  </n-text>
                </div>
                <n-radio-group v-model:value="selectedTier" :disabled="uploading">
                  <n-radio-button
                    v-for="tier in tierOptions"
                    :key="tier.value"
                    :value="tier.value"
                  >
                    {{ tier.label }} · {{ tier.desc }}
                  </n-radio-button>
                </n-radio-group>
              </div>

              <n-upload
                ref="uploadRef"
                accept="application/pdf"
                :max="1"
                :default-upload="false"
                :custom-request="handleUpload"
                :disabled="uploading"
                :on-change="handleFilesChange"
              >
                <n-upload-dragger>
                  <div class="upload-hint">点击或拖拽 PDF 到此处</div>
                  <div class="upload-sub">
                    上传后自动开始翻译；完成后可读双语稿、导读与术语表
                  </div>
                </n-upload-dragger>
              </n-upload>

              <n-alert
                v-if="uploadError"
                type="error"
                class="upload-feedback"
                :show-icon="true"
              >
                {{ uploadError }}
              </n-alert>
            </n-card>
          </section>

          <!-- 阅读工作台：上传完成后与历史"继续读"共用同一处 -->
          <section v-if="currentTask" class="page-section">
            <n-card ref="workbenchRef" class="workbench-card">
              <template #header>
                <div class="workbench-head">
                  <span class="workbench-name">{{ currentTask.filename }}</span>
                  <n-tag
                    v-if="currentTask.tier"
                    size="small"
                    :bordered="false"
                    type="warning"
                  >
                    档位：{{ tierTextMap[currentTask.tier] || currentTask.tier }}
                  </n-tag>
                  <n-tag
                    :type="statusTypeMap[currentTask.status] || 'default'"
                    :bordered="false"
                  >
                    {{ statusTextMap[currentTask.status] || currentTask.status }}
                  </n-tag>
                  <n-space size="small" class="workbench-actions">
                    <n-button
                      v-if="['pending', 'in_progress'].includes(currentTask.status)"
                      size="small"
                      :loading="taskActionBusy"
                      @click="cancelTask(currentTask)"
                    >
                      取消翻译
                    </n-button>
                    <n-button
                      v-if="RETRYABLE_STATES.includes(currentTask.status)"
                      size="small"
                      type="primary"
                      ghost
                      :loading="taskActionBusy"
                      @click="retryTask(currentTask)"
                    >
                      重新翻译
                    </n-button>
                    <n-button
                      v-if="deleteConfirmId === currentTask.id"
                      size="small"
                      type="error"
                      :loading="taskActionBusy"
                      @click="deleteTask(currentTask)"
                    >
                      确认删除
                    </n-button>
                    <n-button
                      v-else
                      size="small"
                      quaternary
                      @click="deleteConfirmId = currentTask.id"
                    >
                      删除
                    </n-button>
                    <n-button
                      v-if="deleteConfirmId === currentTask.id"
                      size="small"
                      quaternary
                      @click="deleteConfirmId = null"
                    >
                      再想想
                    </n-button>
                  </n-space>
                </div>
              </template>

              <n-alert
                v-if="taskActionError"
                type="error"
                class="task-error"
                :show-icon="true"
              >
                {{ taskActionError }}
              </n-alert>

              <div class="task-progress">
                <!-- 诚实进度（F 批）：能拿到引擎自报的页进度就画确定进度条，
                     拿不到就只转圈 + 一行"引擎还在准备"，不编百分比、也不写内部实现细节 -->
                <n-progress
                  v-if="isRunning && hasEngineProgress"
                  type="line"
                  :percentage="progressPercent()"
                  status="info"
                  :processing="true"
                  indicator-placement="inside"
                  :height="18"
                />
                <n-progress
                  v-else-if="!isRunning"
                  type="line"
                  :percentage="progressPercent()"
                  :status="currentTask.status === 'failed' ? 'error' : currentTask.status === 'cancelled' ? 'warning' : 'success'"
                  indicator-placement="inside"
                  :height="18"
                />
                <div class="progress-facts">
                  <n-spin v-if="isRunning && !hasEngineProgress" :size="14" />
                  <span class="progress-stage">{{ stageText }}</span>
                  <span v-if="elapsedText">{{ elapsedText }}</span>
                  <span v-if="etaText" class="progress-eta">{{ etaText }}</span>
                </div>
                <n-alert
                  v-if="currentTask.error_message"
                  :type="currentTask.status === 'cancelled' ? 'warning' : 'error'"
                  class="task-error"
                  :show-icon="true"
                >
                  {{ currentTask.error_message }}
                  <template v-if="RETRYABLE_STATES.includes(currentTask.status)" #action>
                    <n-button size="tiny" @click="retryTask(currentTask)">
                      重新翻译
                    </n-button>
                  </template>
                </n-alert>

                <div
                  v-if="currentTask.status === 'completed'"
                  class="result-panel"
                >
                  <n-tabs
                    v-model:value="workbenchTab"
                    type="line"
                    size="small"
                    @update:value="switchWorkbenchTab"
                  >
                    <n-tab-pane name="bilingual" tab="双语稿">
                      <div class="result-toolbar">
                        <n-radio-group
                          v-model:value="previewMode"
                          size="small"
                          @update:value="refreshPreviewUrl"
                        >
                          <n-radio-button
                            value="mono"
                            :disabled="previewCheckDone && !fileAvailability.mono"
                          >
                            纯中文
                          </n-radio-button>
                          <n-radio-button
                            value="dual"
                            :disabled="previewCheckDone && !fileAvailability.dual"
                          >
                            中英对照
                          </n-radio-button>
                        </n-radio-group>
                        <n-space size="small">
                          <n-button
                            size="small"
                            :disabled="previewCheckDone && !fileAvailability.mono"
                            @click="downloadFile('mono')"
                          >
                            下载纯中文 PDF
                          </n-button>
                          <n-button
                            size="small"
                            :disabled="previewCheckDone && !fileAvailability.dual"
                            @click="downloadFile('dual')"
                          >
                            下载双语 PDF
                          </n-button>
                        </n-space>
                      </div>

                      <n-alert
                        v-if="workbenchError"
                        type="error"
                        :show-icon="true"
                        class="workbench-msg"
                      >
                        {{ workbenchError }}
                      </n-alert>
                      <n-empty
                        v-if="previewCheckDone && !fileAvailability[previewMode]"
                        :description="
                          previewMode === 'dual'
                            ? '该任务暂无双语稿可预览'
                            : '该任务暂无中文稿可预览'
                        "
                        class="result-empty"
                      />
                      <n-spin v-else :show="previewLoading" size="small">
                        <iframe
                          v-if="fileAvailability[previewMode] && previewSrc"
                          :key="previewSrc"
                          class="pdf-preview"
                          :src="previewSrc"
                          title="译文预览"
                        />
                      </n-spin>
                    </n-tab-pane>

                    <n-tab-pane name="guide" tab="导读">
                      <n-spin :show="understandingLoading" size="small">
                        <n-alert
                          v-if="understandingStatus === 'failed'"
                          type="error"
                          :show-icon="true"
                          class="workbench-msg"
                        >
                          {{ understandingError || '导读生成失败' }}
                          <template #action>
                            <n-button size="small" @click="retryUnderstanding">
                              重试
                            </n-button>
                          </template>
                        </n-alert>
                        <n-empty
                          v-else-if="understandingStatus !== 'ready' || !understandingGuide"
                          description="正在生成导读（读取全文 → 提炼要点 → 对齐术语），请稍候…"
                        />
                        <div v-else class="guide-card">
                          <div
                            v-for="key in guideFields"
                            :key="key"
                            class="guide-point"
                            @click="
                              openTrace({
                                label: guideFieldLabel[key],
                                text: (understandingGuide[key] || {}).text,
                                source: (understandingGuide[key] || {}).source_block_ids,
                              })
                            "
                          >
                            <b>{{ guideFieldLabel[key] }}</b>
                            <span class="g-t">{{ (understandingGuide[key] || {}).text }}</span>
                            <span class="g-src">溯源 ▸</span>
                          </div>
                        </div>
                      </n-spin>
                    </n-tab-pane>

                    <n-tab-pane name="terms" tab="术语表">
                      <n-spin :show="understandingLoading" size="small">
                        <n-alert
                          v-if="understandingStatus === 'failed'"
                          type="error"
                          :show-icon="true"
                          class="workbench-msg"
                        >
                          {{ understandingError || '术语表生成失败' }}
                          <template #action>
                            <n-button size="small" @click="retryUnderstanding">
                              重试
                            </n-button>
                          </template>
                        </n-alert>
                        <n-empty
                          v-else-if="!understandingTerms.length"
                          description="正在生成术语表（与导读一同产出），请稍候…"
                        />
                        <div v-else class="terms-list">
                          <div
                            v-for="(t, idx) in understandingTerms"
                            :key="idx"
                            class="term-item"
                          >
                            <b class="t-term">{{ t.term }}</b>
                            <span class="t-cn">{{ t.cn }}</span>
                            <span class="t-def">{{ t.definition }}</span>
                          </div>
                        </div>
                      </n-spin>
                    </n-tab-pane>

                    <n-tab-pane name="ask" tab="问答">
                      <div class="ask-panel">
                        <div class="ask-input-row">
                          <n-input
                            v-model:value="askQuestion"
                            type="textarea"
                            :autosize="{ minRows: 1, maxRows: 4 }"
                            placeholder="就这篇论文提问，例如：这篇论文的核心贡献是什么？"
                            :disabled="askLoading"
                            @keydown.enter.prevent="submitAsk"
                          />
                          <n-button
                            type="primary"
                            :loading="askLoading"
                            :disabled="!askQuestion.trim()"
                            @click="submitAsk"
                          >
                            提问
                          </n-button>
                        </div>

                        <n-alert
                          v-if="askError"
                          type="error"
                          :show-icon="true"
                          class="workbench-msg"
                        >
                          {{ askError }}
                        </n-alert>
                        <n-empty
                          v-else-if="!askResult && !askLoading"
                          description="向这篇论文提问，答案会给出处（点击出处块可溯源原文）"
                          class="result-empty"
                        />
                        <n-spin :show="askLoading" size="small">
                          <div v-if="askResult" class="ask-answer">
                            <div class="ask-answer-head">
                              <n-tag
                                v-if="askResult.mode === 'fts'"
                                size="small"
                                type="warning"
                                :bordered="false"
                              >
                                长文 · 检索模式
                              </n-tag>
                            </div>
                            <div class="ask-answer-text">{{ askResult.answer }}</div>
                            <div
                              v-if="askResult.source_block_ids && askResult.source_block_ids.length"
                              class="ask-sources"
                            >
                              <span class="ask-sources-label">出处：</span>
                              <n-tag
                                v-for="id in askResult.source_block_ids"
                                :key="id"
                                size="small"
                                type="info"
                                class="ask-src-tag"
                                @click="
                                  openTrace({
                                    label: '问答出处',
                                    text: askResult.answer,
                                    source: [id],
                                  })
                                "
                              >
                                {{ id }} ▸
                              </n-tag>
                            </div>
                            <div v-else class="ask-sources-label">（回答未给出处）</div>
                          </div>
                        </n-spin>
                      </div>
                    </n-tab-pane>
                  </n-tabs>
                </div>

                <!-- 点溯源底部抽屉 -->
                <n-drawer v-model:show="traceVisible" placement="bottom" :height="'46%'">
                  <n-drawer-content closable>
                    <template #header>
                      <div class="trace-head">
                        <n-text strong>{{ (tracePoint && tracePoint.label) || '溯源' }}</n-text>
                        <n-text depth="3" class="trace-src">
                          来源块：{{ ((tracePoint && tracePoint.source) || []).join(', ') || '未知' }}
                        </n-text>
                      </div>
                    </template>
                    <div class="trace-pair">
                      <div class="trace-side">
                        <div class="trace-lh">原文</div>
                        <div class="trace-text">
                          {{ (sourceBlockText() && sourceBlockText().text) || ((tracePoint && tracePoint.text) || '—') }}
                        </div>
                      </div>
                      <div class="trace-side">
                        <div class="trace-lh">译文</div>
                        <div class="trace-text">
                          {{ (sourceBlockText() && sourceBlockText().translated) || '—' }}
                        </div>
                      </div>
                    </div>
                  </n-drawer-content>
                </n-drawer>
              </div>
            </n-card>
          </section>

          <section class="page-section">
            <n-card class="history-card">
              <template #header>
                <div class="history-head">
                  <span class="history-title">最近在读</span>
                  <n-text depth="3" class="history-sub">
                    点开任意一篇，接着读双语稿 / 导读 / 术语表，也可以继续提问
                  </n-text>
                </div>
              </template>
              <template #header-extra>
                <n-button size="small" quaternary @click="loadTasks">刷新</n-button>
              </template>
              <n-spin :show="historyLoading">
                <n-empty
                  v-if="!historyLoading && !historyError && tasks.length === 0"
                  description="还没有论文，上传 PDF 后会出现在这里"
                  class="history-empty"
                />
                <n-alert v-else-if="historyError" type="error" :show-icon="true">
                  {{ historyError }}
                </n-alert>
                <div v-else-if="tasks.length" class="task-list">
                  <n-alert
                    v-if="taskActionError"
                    type="error"
                    :show-icon="true"
                    class="task-action-error"
                  >
                    {{ taskActionError }}
                  </n-alert>
                  <div v-for="task in tasks" :key="task.id" class="task-row">
                    <div class="task-row-info">
                      <div class="task-row-name">
                        <n-text strong>{{ task.filename }}</n-text>
                        <n-tag
                          :type="statusTypeMap[task.status] || 'default'"
                          size="small"
                          :bordered="false"
                        >
                          {{ statusTextMap[task.status] || task.status }}
                        </n-tag>
                        <n-tag v-if="task.tier" size="small" :bordered="false">
                          {{ tierTextMap[task.tier] || task.tier }}
                        </n-tag>
                      </div>
                      <div class="task-row-meta">
                        <span>{{ formatTime(task.created_at) }}</span>
                        <span v-if="rowProgressText(task)">
                          {{ rowProgressText(task) }}
                        </span>
                      </div>
                    </div>
                    <n-space size="small" class="task-row-actions">
                      <n-button
                        size="small"
                        type="primary"
                        ghost
                        @click="openWorkbench(task)"
                      >
                        {{ task.status === 'completed' ? '继续读' : '查看进度' }}
                      </n-button>
                      <n-button
                        v-if="['pending', 'in_progress'].includes(task.status)"
                        size="small"
                        :loading="taskActionBusy"
                        @click="cancelTask(task)"
                      >
                        取消
                      </n-button>
                      <n-button
                        v-if="RETRYABLE_STATES.includes(task.status)"
                        size="small"
                        :loading="taskActionBusy"
                        @click="retryTask(task)"
                      >
                        重试
                      </n-button>
                      <n-button size="small" quaternary @click="openTaskDetail(task)">
                        详情
                      </n-button>
                      <template v-if="deleteConfirmId === task.id">
                        <n-button
                          size="small"
                          type="error"
                          :loading="taskActionBusy"
                          @click="deleteTask(task)"
                        >
                          确认删除
                        </n-button>
                        <n-button size="small" quaternary @click="deleteConfirmId = null">
                          取消
                        </n-button>
                      </template>
                      <n-button
                        v-else
                        size="small"
                        quaternary
                        @click="deleteConfirmId = task.id"
                      >
                        删除
                      </n-button>
                    </n-space>
                  </div>
                </div>
              </n-spin>
            </n-card>
          </section>

          <section class="page-section">
            <n-grid :cols="3" :x-gap="16" responsive="screen" item-responsive>
              <n-gi span="3 s:1 m:1" v-for="feature in [
                { title: '双语对照稿', desc: '保留原论文的结构与排版，可在线预览、可下载。' },
                { title: '结构化导读', desc: '研究问题 / 方法 / 结论 / 创新点，每条都能点回原文。' },
                { title: '带出处问答', desc: '就论文提问，答案标明来自哪一段，找不回就直说。' },
              ]" :key="feature.title">
                <n-card :title="feature.title" class="feature-card">
                  <n-text depth="3">{{ feature.desc }}</n-text>
                </n-card>
              </n-gi>
            </n-grid>
          </section>

          <section class="page-section status-row">
            <span>后端状态：</span>
            <n-tag :type="statusMeta[backendStatus].type" :bordered="false">
              {{ statusMeta[backendStatus].text }}
            </n-tag>
            <n-text v-if="backendStatus === 'ok' && taskCount !== null" depth="3" class="task-count">
              任务列表共 {{ taskCount }} 条
            </n-text>
            <n-text v-if="healthInfo" depth="3" class="task-count">
              排队 {{ healthInfo.queue_size ?? 0 }} 篇<template
                v-if="healthInfo.running_task_id"
              >，正在处理 #{{ healthInfo.running_task_id }}</template>
            </n-text>
            <n-text v-if="healthInfo?.database_error" depth="3" class="task-count">
              数据库：{{ healthInfo.database_error }}
            </n-text>
          </section>
          </template>
        </main>
      </n-layout-content>

      <n-layout-footer bordered class="page-footer">
        docwise · 让读不懂英文文献的人，把它读懂
      </n-layout-footer>
    </n-layout>

    <n-drawer v-model:show="drawerVisible" placement="right" :width="'min(720px, 100vw)'">
      <n-drawer-content>
        <template #header>
          <div class="drawer-title">
            <n-text strong>{{ detailTitle }}</n-text>
            <n-tag
              v-if="detailTask"
              :type="statusTypeMap[detailTask.status] || 'default'"
              :bordered="false"
            >
              {{ statusTextMap[detailTask.status] || detailTask.status }}
            </n-tag>
          </div>
        </template>

        <n-spin :show="detailLoading">
          <n-alert v-if="detailError" type="error" :show-icon="true" class="detail-error">
            {{ detailError }}
            <template #action>
              <n-button size="small" @click="fetchTaskDetail(detailTaskId)">
                重试
              </n-button>
            </template>
          </n-alert>

          <template v-else-if="detailTask">
            <div class="detail-meta">
              <span>创建时间：{{ formatTime(detailTask.created_at) }}</span>
              <span>档位：{{ tierTextMap[detailTask.tier] || detailTask.tier }}</span>
              <span v-if="detailTask.status === 'in_progress'">
                进度：{{ Math.round((detailTask.progress ?? 0) * 100) }}%
              </span>
            </div>

            <n-alert
              v-if="detailTask.status === 'failed' && detailTask.error_message"
              type="error"
              :show-icon="true"
              class="detail-error"
            >
              {{ detailTask.error_message }}
            </n-alert>

            <div class="block-section-title">
              <n-text strong>分块处理状态</n-text>
              <n-text depth="3" class="block-count">
                共 {{ detailTask.blocks?.length ?? 0 }} 块（排查用；阅读请点"继续读"）
              </n-text>
            </div>

            <n-empty
              v-if="!detailTask.blocks?.length"
              description="该任务暂无分块结果（任务尚未处理完成）"
              class="detail-empty"
            />

            <div v-else class="block-list">
              <div
                v-for="(block, index) in detailTask.blocks"
                :key="`${block.block_id}-${index}`"
                class="block-card"
              >
                <div class="block-card-head">
                  <n-text depth="3">{{ block.block_id }}</n-text>
                  <n-tag
                    :type="blockStatusMeta[block.status]?.type || 'default'"
                    size="small"
                    :bordered="false"
                  >
                    {{ blockStatusMeta[block.status]?.text || block.status }}
                  </n-tag>
                </div>
                <div class="block-pair">
                  <div class="block-side">
                    <div class="block-label">原文</div>
                    <div class="block-text">{{ block.text }}</div>
                  </div>
                  <div class="block-side">
                    <div class="block-label">译文</div>
                    <div class="block-text">{{ block.translated || '—' }}</div>
                  </div>
                </div>
                <n-alert
                  v-if="block.error"
                  type="error"
                  class="block-error"
                  :show-icon="true"
                >
                  {{ block.error }}
                </n-alert>
              </div>
            </div>
          </template>
        </n-spin>
      </n-drawer-content>
    </n-drawer>
  </n-config-provider>
</template>
