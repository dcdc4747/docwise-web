<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
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
  elapsedTextFor,
  engineText as engineTextFor,
  etaTextFor,
  formatDuration,
  stageTextFor,
} from './progressText'
import { blockLabel, buildParagraphRows, findBlockByText } from './blockLabel'
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
  NDropdown,
} from 'naive-ui'

const backendStatus = ref('checking')
const healthInfo = ref(null)
const taskCount = ref(null)
const uploading = ref(false)
const uploadError = ref('')
const currentTask = ref(null)
/**
 * 形态：L1 库页（我的论文）/ L2 阅读工作区，两级结构。
 * 打开任意一篇（上传完成或历史"继续读"）都进 L2；点「← 我的论文」回 L1。
 * 注意：回 L1 时**不清 currentTask**——后台翻译的 SSE 还要继续推，进度条在 L1 的任务条上继续走。
 */
const view = ref('library')
function backToLibrary() {
  view.value = 'library'
}
watch(currentTask, (task) => {
  if (task) view.value = 'reader'
})

/**
 * 阅读工作区的「⋯」菜单。
 * 形态约定：单层级、项数≤7、**任意两项的动作名不许共享动词**（所以是"重试翻译"而不是"重新翻译"×2）。
 */
const readerMenuOptions = computed(() => {
  const task = currentTask.value
  if (!task) return []
  const items = [{ label: '文档信息', key: 'info' }]
  if (['pending', 'in_progress'].includes(task.status)) {
    items.push({ label: '取消翻译', key: 'cancel' })
  }
  if (RETRYABLE_STATES.includes(task.status)) {
    items.push({ label: '重试翻译', key: 'retry' })
  }
  items.push({ type: 'divider', key: 'divider-1' })
  items.push({ label: '删除…', key: 'delete' })
  return items
})

function onReaderMenuSelect(key) {
  const task = currentTask.value
  if (!task) return
  if (key === 'info') {
    openTaskDetail(task)
  } else if (key === 'cancel') {
    cancelTask(task)
  } else if (key === 'retry') {
    retryTask(task)
  } else if (key === 'delete') {
    deleteConfirmId.value = task.id
  }
}
const uploadRef = ref(null)
const previewMode = ref('mono')
const previewSrc = ref('')
const fileAvailability = ref({ mono: false, dual: false })
const previewCheckDone = ref(false)
const previewLoading = ref(true)
const selectedTier = ref('fast')
// 文献语言：对象是"文献本身"，中文文献也支持——中文不翻译，直接抽字出导读与出处
const selectedLang = ref('en')
// 当前任务是不是"不需要翻译"的中文文献（后端按语言对判定，前端不重复实现一遍口径）
const isNativeTask = computed(() => currentTask.value?.native === true)
// 中文文献没有"双语稿"这一说，产物就是原文本身
const bilingualTabLabel = computed(() => (isNativeTask.value ? '原文' : '双语稿'))
const previewEmptyText = computed(() => {
  if (isNativeTask.value) return '该任务暂无可预览的原文'
  return previewMode.value === 'dual' ? '该任务暂无双语稿可预览' : '该任务暂无中文稿可预览'
})
const uploadHint = computed(() =>
  selectedLang.value === 'zh'
    ? '上传后自动抽取文字并生成导读；完成后可读原文、导读、术语表与带出处的问答'
    : '上传后自动开始翻译；完成后可读双语稿、导读与术语表'
)
const workbenchError = ref('')

// ---- 账号（B 批）：登录态、管理后台入口、演示一键登录开关 ----
const authUser = ref(null)
const authChecking = ref(true)
const authNotice = ref('')
const demoAutologin = ref(false)
const showAdmin = ref(false)

// ---- 阅读工作台（理解层：导读 / 术语表 / 点溯源）----
const workbenchTab = ref('ask')
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
      body: JSON.stringify({
        question: q,
        // 形态：提问锚点与出处是同一个坐标系——把划词选中的那段带给后端，
        // 模型才知道问题里的「这句话」指哪一段（后端会按本任务的块编号校验）
        focus_block_ids: askAnchor.value?.blockId ? [askAnchor.value.blockId] : [],
      }),
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
  { value: 'fast', label: '快档', desc: '最快，先看个大概' },
  { value: 'medium', label: '中档', desc: '版式更稳，适合正式阅读' },
  { value: 'precise', label: '慢档', desc: '最准，多一道审校，适合定稿引用' },
]

// 文献语言：外文要翻译，中文不用翻译（直接进理解层）
const langOptions = [
  { value: 'en', label: '外文文献', desc: '译成中文，出双语对照稿' },
  { value: 'zh', label: '中文文献', desc: '不翻译，直接出导读与出处' },
]

// 档位只有一个写法：快/中/慢 + 各自的一句话特征（形态约定：选择处、工具条、卡片一律用这一套）
const tierTextMap = {
  fast: '快档 · 最快',
  medium: '中档 · 平衡',
  precise: '慢档 · 最准',
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
// 具体文案逻辑在 src/progressText.js（那边有单测）。

const isRunning = computed(() => isRunningTask(currentTask.value))

const hasEngineProgress = computed(() => !!engineProgress.value)

const stageText = computed(() =>
  stageTextFor(currentTask.value, engineProgress.value),
)

// 引擎自报的页进度单独一行文字（标着"引擎自报"，它不是我们的承诺）
const engineText = computed(() => engineTextFor(engineProgress.value))

const elapsedText = computed(() => {
  const task = currentTask.value
  if (!task || !task.started_at) return ''
  const running = isRunningTask(task)
  const drift = running
    ? Math.max(0, (elapsedTick.value - elapsedBase.at) / 1000)
    : 0
  return elapsedTextFor(task, elapsedBase.seconds + drift)
})

const etaText = computed(() =>
  etaTextFor(currentTask.value, currentTask.value?.eta_seconds),
)

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
  workbenchTab.value = 'ask'
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
  // 语言对：zh → zh 表示"中文文献，不翻译"（后端据此走取字引擎，见 engine/registry.py）
  form.append('source_lang', selectedLang.value)
  form.append('target_lang', 'zh')

  try {
    const res = await authFetch('/api/tasks/upload', { method: 'POST', body: form })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail || `上传失败（HTTP ${res.status}）`)
    }
    const task = await res.json()
    currentTask.value = task
    workbenchTab.value = 'ask'
    // 中文文献只有一份产物（原稿），预览固定用 mono，避免出现"中英对照"却是同一份文件
    if (task.native) previewMode.value = 'mono'
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
    const parts = [`翻译中 ${Math.round((task.progress ?? 0) * 100)}%`]
    if (typeof task.elapsed_seconds === 'number' && task.elapsed_seconds >= 1) {
      parts.push(`已用 ${formatDuration(task.elapsed_seconds)}`)
    }
    if (typeof task.eta_seconds === 'number' && task.eta_seconds > 0) {
      parts.push(`引擎自报还需 ${formatDuration(task.eta_seconds)}`)
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

/* ===== 出处人话化（形态硬约定：出处永远显示「第 X 页 · 第 Y 段」） =====
   - 块编号对用户是乱码，只留在 title 里供排查；
   - 段号按页内重算（块编号里的 b 是全文档全局序号）；
   - 解析不出 → 显示"位置待定"，**绝不裸露编号、也不假装**。 */
const blockOrder = computed(() => Object.keys(blocksById.value))

function labelOf(blockId) {
  return blockLabel(blockId, blockOrder.value)
}

const traceSourceLabel = computed(() => {
  const ids = (tracePoint.value && tracePoint.value.source) || []
  const labels = ids.map((id) => labelOf(id)).filter(Boolean)
  return labels.length ? labels.join('、') : '位置待定'
})

/** 导读字段有没有真出处（LLM 返回的 source_block_ids）；没有的那条要置灰不可点。 */
function guideHasSource(key) {
  const field = (understandingGuide.value || {})[key]
  return Array.isArray(field?.source_block_ids) && field.source_block_ids.length > 0
}

/** 点导读要点：有出处才跳，没出处就别装成能点（降级态）。 */
function openGuideTrace(key) {
  if (!guideHasSource(key)) return
  const field = understandingGuide.value[key]
  focusBlock(field.source_block_ids[0], { label: guideFieldLabel[key], text: field.text })
}

/* ===== 左栏：段落精读（我们自己的 DOM）/ 原版 PDF（iframe，浏览器自带阅读器） =====
   为什么要有段落精读：iframe 里是黑盒插件，拿不到 DOM——「点出处 → 滚到那一段 → 高亮」
   在 iframe 上物理上做不到。段落精读用的是自己的 DOM，锚点与出处才真正同一个坐标系。 */
const docMode = ref('paragraph')

const paragraphRows = computed(() =>
  buildParagraphRows(blockOrder.value.map((id) => blocksById.value[id]).filter(Boolean)),
)

/**
 * 这批块里到底有没有译文？
 *
 * 真接口冒烟 + 查库发现（2026-09-14）：**全库 1510 个块的 `translated` 一律为空**——
 * 引擎包装脚本只写 `{block_id, text}`，翻译结果只在 PDF 产物里。
 * 所以左栏选「纯中文」时其实是回退显示原文。界面不能装作有译文：没有就直说。
 */
const hasBlockTranslations = computed(() =>
  paragraphRows.value.some(
    (row) => row.kind === 'block' && (row.block.translated || '').trim().length > 0,
  ),
)

/** 划词提问：选区落在哪一段 → 锚到那个块；提问内容里就带着选中的那句话。 */
const askAnchor = ref(null)

const askAnchorLabel = computed(() => {
  if (!askAnchor.value) return ''
  const label = labelOf(askAnchor.value.blockId)
  return label ? `已锚定 · ${label}` : '已锚定（位置待定）'
})

function onDocMouseUp() {
  const selection = typeof window !== 'undefined' && window.getSelection
    ? window.getSelection()
    : null
  const text = (selection?.toString() || '').trim()
  if (!text) return
  let node = selection.anchorNode
  while (node && node.nodeType !== 1) node = node.parentNode
  const holder = node && node.closest ? node.closest('[data-block-id]') : null
  askAnchor.value = {
    blockId: holder?.dataset?.blockId || '',
    text: text.slice(0, 200),
  }
  askQuestion.value = text.length > 80 ? `${text.slice(0, 80)}…` : text
}

/** 点出处：滚到那一段 + 高亮脉冲；这一段没渲染出来才退回抽屉（诚实降级，不假装跳成功）。 */function focusBlock(blockId, meta = {}) {
  const node =
    typeof document !== 'undefined' ? document.getElementById(`block-${blockId}`) : null
  if (!node) {
    openTrace({ label: meta.label, text: meta.text, source: [blockId] })
    return false
  }
  docMode.value = 'paragraph'
  // 手机上：点出处要把助手降到 peek、露一行「已定位到…」——
  // 否则抽屉把正文盖住，跳了等于没跳（评审 R-02 的要点）
  if (isNarrow.value) {
    sheetState.value = 'peek'
    locatedHint.value = `已定位到 ${labelOf(blockId) || '该段落'}`
  }
  if (node.scrollIntoView) node.scrollIntoView({ behavior: 'smooth', block: 'center' })
  node.classList.remove('block-flash')
  void node.offsetWidth
  node.classList.add('block-flash')
  if (typeof window !== 'undefined') {
    window.setTimeout(() => node.classList.remove('block-flash'), 2200)
  }
  return true
}

/* ===== 阅读位置记忆（形态：卡片显示「上次读到第 X 页」，进来跳回原处） =====
   没记录就显示「开始阅读」而不是「继续读」——不假装记得。
   位置是体验数据：写失败静默忽略，绝不因为它影响阅读。 */
const resumeHint = ref('')
let positionSent = { page: 0, at: 0 }
let resumedForTask = null

async function saveReadingPosition(page) {
  const task = currentTask.value
  if (!task || !page) return
  const now = Date.now()
  if (page === positionSent.page && now - positionSent.at < 5000) return
  positionSent = { page, at: now }
  try {
    await authFetch(`/api/tasks/${task.id}/reading-position`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ page }),
    })
  } catch {
    /* 位置没记上不影响阅读，下次滚动还会再试 */
  }
}

/** 滚动时把"当前页"记下来：取最后一个已经滚过顶部的页分隔条所在的页。 */
function onPaneScroll(event) {
  const pane = event.target
  const separators = pane.querySelectorAll('.page-sep[data-page]')
  let current = 1
  separators.forEach((separator) => {
    if (separator.offsetTop <= pane.scrollTop + 12) {
      current = Number(separator.dataset.page) || current
    }
  })
  saveReadingPosition(current)
}

async function applyResumePosition() {
  const page = currentTask.value?.last_read_page
  if (!page || page <= 1 || docMode.value !== 'paragraph') return
  await nextTick()
  const target =
    typeof document !== 'undefined' ? document.getElementById(`page-${page}`) : null
  if (!target) return
  if (target.scrollIntoView) target.scrollIntoView({ block: 'start' })
  resumeHint.value = `已回到上次读到的地方（第 ${page} 页）`
}

watch([currentTask, paragraphRows], () => {
  const task = currentTask.value
  if (!task || view.value !== 'reader') return
  if (resumedForTask === task.id) return
  resumedForTask = task.id
  applyResumePosition()
})

/* ===== 手机端助手：底部抽屉三档（peek / 半屏 / 近全屏） =====
   形态约定：peek 只露页签（正文让出来）；点出处自动降到 peek 并露一行「已定位到…」。 */
const isNarrow = ref(false)
const sheetState = ref('peek')
const locatedHint = ref('')

const sheetHint = computed(() => {
  if (sheetState.value === 'peek') return '上拖展开助手'
  if (sheetState.value === 'half') return '上拖到近全屏'
  return '下拖回到半屏'
})

function syncNarrow() {
  if (typeof window === 'undefined') return
  isNarrow.value = window.innerWidth < 1024
}

if (typeof window !== 'undefined') {
  syncNarrow()
  window.addEventListener('resize', syncNarrow)
}
onUnmounted(() => {
  if (typeof window !== 'undefined') window.removeEventListener('resize', syncNarrow)
})

function cycleSheet() {
  const order = ['peek', 'half', 'full']
  const next = order[(order.indexOf(sheetState.value) + 1) % order.length]
  sheetState.value = next
}

/* ===== 下载与账号：入口统一（形态：下载只有一个名字；管理后台不占顶栏主位） ===== */
const downloadOptions = computed(() => {
  if (isNativeTask.value) return [{ label: '下载原稿 PDF', key: 'mono' }]
  return [
    { label: '下载双语稿（默认）', key: 'dual' },
    { label: '下载纯中文稿', key: 'mono' },
  ]
})

const accountOptions = computed(() => {
  const items = [{ label: authUser.value?.username || '账号', key: 'me', disabled: true }]
  if (authUser.value?.role === 'admin') {
    items.push({ label: '管理后台', key: 'admin' })
  }
  items.push({ type: 'divider', key: 'divider-1' })
  items.push({ label: '退出登录', key: 'logout' })
  return items
})

function onAccountSelect(key) {
  if (key === 'admin') showAdmin.value = true
  else if (key === 'logout') onLogout()
}

/* ===== 术语定位（术语表没有出处字段 → 只能"命中后回填"，不许预填坐标） ===== */
const termLocateState = ref({})

function termLocateLabel(term) {
  return termLocateState.value[term?.term] || '在原文中定位'
}

async function locateTerm(term) {
  const key = term?.term
  if (!key || !currentTask.value) return
  if (!Object.keys(blocksById.value).length) {
    await loadBlocks(currentTask.value.id)
  }
  const blocks = Object.values(blocksById.value)
  const hit = findBlockByText(key, blocks) || findBlockByText(term.cn, blocks)
  if (!hit) {
    termLocateState.value = { ...termLocateState.value, [key]: '没找到，可能在图/表里' }
    return
  }
  const label = labelOf(hit.block_id)
  termLocateState.value = {
    ...termLocateState.value,
    [key]: label ? `已定位 · ${label}` : '已定位（位置待定）',
  }
  openTrace({ label: key, text: term.definition, source: [hit.block_id] })
  focusBlock(hit.block_id, { label: key, text: term.definition })
}

/* ===== 问答快捷提问（形态：chips 只放**导读与术语都没答**的问题，不重复） ===== */
const askChips = [
  '这项研究有什么局限？',
  '论文提到的未来工作是什么？',
  '研究用了哪些数据或样本？',
  '主要结果是什么？',
  '这些结论有多可靠？',
]

function askPreset(question) {
  askQuestion.value = question
  return submitAsk()
}

/* ===== L1 完成横幅（翻译完成后不静默消失；最多保留一条，可关掉） ===== */
const dismissedBannerId = ref(null)

const completedBannerTask = computed(() => {
  const done = tasks.value.find((task) => task.status === 'completed' && task.finished_at)
  if (!done || done.id === dismissedBannerId.value) return null
  const finishedAt = new Date(done.finished_at).getTime()
  if (!Number.isFinite(finishedAt)) return null
  const fresh = Date.now() - finishedAt < 10 * 60 * 1000
  return fresh ? done : null
})

function dismissBanner(task) {
  dismissedBannerId.value = task.id
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
          <!-- 形态：管理后台不占顶栏主位，收进账号菜单（仅管理员可见） -->
          <n-dropdown
            trigger="click"
            :options="accountOptions"
            @select="onAccountSelect"
          >
            <n-button size="small" quaternary>
              {{ authUser.username }} ▾
            </n-button>
          </n-dropdown>
        </div>
      </n-layout-header>

      <n-layout-content content-style="padding: 0">
        <main class="page-main">
          <AdminView v-if="showAdmin" />
          <template v-else>
          <!-- L1 空库态：只有一篇都没有时才出大 hero（有历史后收成标题行） -->
          <section v-if="view === 'library' && !tasks.length && !historyLoading" class="page-hero">
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
            <n-card title="上传文献 PDF" class="upload-card" v-if="view === 'library'">
              <div class="tier-picker">
                <div class="tier-picker-head">
                  <n-text strong>文献语言</n-text>
                  <n-text depth="3" class="tier-picker-sub">
                    中文文献不翻译，直接抽字出导读、术语与带出处的问答
                  </n-text>
                </div>
                <n-radio-group v-model:value="selectedLang" :disabled="uploading">
                  <n-radio-button
                    v-for="lang in langOptions"
                    :key="lang.value"
                    :value="lang.value"
                  >
                    {{ lang.label }} · {{ lang.desc }}
                  </n-radio-button>
                </n-radio-group>
              </div>

              <div v-if="selectedLang !== 'zh'" class="tier-picker">
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
                  <div class="upload-sub">{{ uploadHint }}</div>
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
          <section v-if="view === 'reader' && currentTask" class="reader-section">
            <n-card ref="workbenchRef" class="reader-card">
              <template #header>
                <div class="workbench-head">
                  <n-button size="small" quaternary @click="backToLibrary">← 我的论文</n-button>
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
                  <!-- 形态：次要动作收进「⋯」，菜单单层级、动作名不共享动词 -->
                  <n-dropdown
                    trigger="click"
                    :options="readerMenuOptions"
                    @select="onReaderMenuSelect"
                  >
                    <n-button size="small" quaternary>⋯</n-button>
                  </n-dropdown>
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
                <!-- 诚实进度（F 批）：进度条**永远在**——引擎报了页数就画确定进度条，
                     没报就画一根流动的条纹条（不写百分比）。理由是实测发现这台引擎十几秒
                     不更新一次进度条，若"没数字就不画"，用户看到的会是"进度条消失"。 -->
                <!-- 引擎报了页数 → 确定进度条（百分比标在条里）；
                     没报 → 一根流动的条纹条，**不写百分比**（naive-ui 的
                     show-indicator 只在 indicator-placement="outside" 下生效，
                     所以这一支干脆不放指示器）。 -->
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
                  v-else-if="isRunning"
                  type="line"
                  :percentage="0"
                  :processing="true"
                  :show-indicator="false"
                  :height="18"
                />
                <n-progress
                  v-else
                  type="line"
                  :percentage="progressPercent()"
                  :status="currentTask.status === 'failed' ? 'error' : currentTask.status === 'cancelled' ? 'warning' : 'success'"
                  indicator-placement="inside"
                  :height="18"
                />
                <div class="progress-facts">
                  <span class="progress-stage">{{ stageText }}</span>
                  <span v-if="elapsedText" class="progress-elapsed">{{ elapsedText }}</span>
                  <span v-if="engineText" class="progress-engine">{{ engineText }}</span>
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

                <div v-if="currentTask.status === 'completed'" class="reader-body">
                  <!-- 左：文档区（本批仍是现有 iframe 预览；pdf.js 与段落视图放下一批） -->
                  <div class="reader-doc">
                      <div class="result-toolbar">
                        <!-- 左栏渲染方式：段落精读（自己的 DOM，锚点成立）/ 原版 PDF（iframe，只读） -->
                        <n-radio-group v-model:value="docMode" size="small">
                          <n-radio-button value="paragraph">段落精读</n-radio-button>
                          <n-radio-button value="pdf">原版 PDF</n-radio-button>
                        </n-radio-group>
                        <n-radio-group
                          v-if="!isNativeTask"
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
                        <n-text v-else depth="3" class="tier-picker-sub">
                          中文文献不翻译，这里就是原文
                        </n-text>
                          <!-- 形态：下载入口只有一个名字（「下载译稿」），具体下哪份在里面选 -->
                          <n-dropdown
                            trigger="click"
                            :options="downloadOptions"
                            @select="downloadFile"
                          >
                            <n-button size="small">⤓ 下载译稿 ▾</n-button>
                          </n-dropdown>
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
                        v-if="docMode === 'pdf' && previewCheckDone && !fileAvailability[previewMode]"
                        :description="previewEmptyText"
                        class="result-empty"
                      />
                      <n-spin v-else-if="docMode === 'pdf'" :show="previewLoading" size="small">
                        <iframe
                          v-if="fileAvailability[previewMode] && previewSrc"
                          :key="previewSrc"
                          class="pdf-preview"
                          :src="previewSrc"
                          title="译文预览"
                        />
                      </n-spin>

                      <!-- 段落精读：按块重排（原文小字灰 + 译文主文），跨页插页分隔条、段号页内重算 -->
                      <div
                        v-else
                        class="paragraph-pane"
                        @mouseup="onDocMouseUp"
                        @scroll="onPaneScroll"
                      >
                        <!-- 诚实降级：没有块级译文就说没有，别让「纯中文」显示着英文 -->
                        <n-alert
                          v-if="!isNativeTask && !hasBlockTranslations"
                          type="warning"
                          :show-icon="true"
                          class="no-translation-msg"
                        >
                          这篇文献暂无「块级」译文（译文在 PDF 产物里，段落视图拿不到），
                          下面显示的是原文；问答与检索同样基于原文。
                        </n-alert>
                        <div v-if="resumeHint" class="resume-hint">
                          <span>{{ resumeHint }}</span>
                          <n-button size="tiny" quaternary @click="resumeHint = ''">
                            知道了
                          </n-button>
                        </div>
                        <div v-if="askAnchor" class="sel-chip">
                          <span class="sel-chip-note">{{ askAnchorLabel }}</span>
                          <n-button size="tiny" type="primary" @click="workbenchTab = 'ask'">
                            去提问
                          </n-button>
                        </div>
                        <n-empty
                          v-if="!paragraphRows.length"
                          description="这篇文献还没有可读的段落块"
                          class="result-empty"
                        />
                        <template v-for="(row, rowIndex) in paragraphRows" :key="rowIndex">
                          <div
                            v-if="row.kind === 'page'"
                            :id="`page-${row.page + 1}`"
                            class="page-sep"
                            :data-page="row.page + 1"
                          >
                            —— {{ row.label }} ——
                          </div>
                          <div
                            v-else
                            :id="`block-${row.block.block_id}`"
                            class="paragraph-row"
                            :data-block-id="row.block.block_id"
                          >
                            <span class="paragraph-no">{{ row.label }}</span>
                            <div class="paragraph-body">
                              <div
                                v-if="previewMode === 'dual' && !isNativeTask && row.block.text"
                                class="paragraph-source"
                              >
                                {{ row.block.text }}
                              </div>
                              <div class="paragraph-translated">
                                {{ row.block.translated || row.block.text }}
                              </div>
                            </div>
                          </div>
                        </template>
                      </div>
                  </div>

                  <!-- 右：助手区（窄屏时变底部抽屉：peek / 半屏 / 近全屏） -->
                  <div
                    class="reader-assist"
                    :class="{ 'assist-sheet': isNarrow, ['sheet-' + sheetState]: isNarrow }"
                  >
                    <div v-if="isNarrow" class="sheet-grip" @click="cycleSheet">
                      <i></i>
                      <span>{{ sheetHint }}</span>
                    </div>
                    <div v-if="isNarrow && locatedHint" class="peek-line">
                      {{ locatedHint }}
                    </div>
                    <n-tabs
                      v-model:value="workbenchTab"
                      type="line"
                      size="small"
                      @update:value="switchWorkbenchTab"
                    >

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
                            :class="{ 'guide-point--dead': !guideHasSource(key) }"
                            @click="openGuideTrace(key)"
                          >
                            <b>{{ guideFieldLabel[key] }}</b>
                            <span class="g-t">{{ (understandingGuide[key] || {}).text }}</span>
                            <span v-if="guideHasSource(key)" class="g-src">
                              看原文 · {{ labelOf((understandingGuide[key] || {}).source_block_ids[0]) || '位置待定' }} ▸
                            </span>
                            <span v-else class="g-src g-src--dead">
                              无单一段落出处（这条由全文综合）
                            </span>
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
                            <div class="t-ops">
                              <n-button
                                size="tiny"
                                quaternary
                                @click="locateTerm(t)"
                              >
                                {{ termLocateLabel(t) }}
                              </n-button>
                            </div>
                          </div>
                        </div>
                      </n-spin>
                    </n-tab-pane>

                    <n-tab-pane name="ask" tab="问答">
                      <div class="ask-panel">
                        <div v-if="askAnchor" class="ask-anchor">
                          <span class="ask-anchor-text">
                            {{ askAnchorLabel }} —— 这次提问会带上你选中的那段
                          </span>
                          <n-button size="tiny" quaternary @click="askAnchor = null">
                            取消锚定
                          </n-button>
                        </div>
                        <div class="ask-chips">
                          <n-button
                            v-for="chip in askChips"
                            :key="chip"
                            size="tiny"
                            quaternary
                            :disabled="askLoading"
                            @click="askPreset(chip)"
                          >
                            {{ chip }}
                          </n-button>
                        </div>
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
                                :title="'原文块 ' + id"
                                @click="focusBlock(id, { label: '问答出处', text: askResult.answer })"
                              >
                                {{ labelOf(id) || '出处未能定位' }} ▸
                              </n-tag>
                            </div>
                            <div v-else class="ask-sources-label">（回答未给出处）</div>
                          </div>
                        </n-spin>
                      </div>
                    </n-tab-pane>
                  </n-tabs>
                </div>
                </div>

                <!-- 点溯源底部抽屉 -->
                <n-drawer v-model:show="traceVisible" placement="bottom" :height="'46%'">
                  <n-drawer-content closable>
                    <template #header>
                      <div class="trace-head">
                        <n-text strong>{{ (tracePoint && tracePoint.label) || '溯源' }}</n-text>
                        <n-text depth="3" class="trace-src">
                          出处：{{ traceSourceLabel }}
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

          <!-- 形态：翻译完成后不静默消失——变绿给下一步（最多一条，可关掉） -->
          <section v-if="view === 'library' && completedBannerTask" class="page-section">
            <n-alert type="success" :show-icon="true" class="complete-banner">
              <template #header>
                翻译完成 · {{ completedBannerTask.filename }}
              </template>
              <n-space size="small" align="center">
                <n-button
                  size="small"
                  type="primary"
                  @click="openWorkbench(completedBannerTask)"
                >
                  开始阅读
                </n-button>
                <n-button
                  size="small"
                  quaternary
                  @click="dismissBanner(completedBannerTask)"
                >
                  关闭
                </n-button>
              </n-space>
            </n-alert>
          </section>

          <section v-if="view === 'library'" class="page-section">
            <n-card class="history-card">
              <template #header>
                <div class="history-head">
                  <span class="history-title">最近在读</span>
                  <n-text depth="3" class="history-sub">
                    点开任意一篇，接着读原文 / 双语稿 / 导读 / 术语表，也可以继续提问
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
                        <n-tag v-if="task.native" size="small" type="info" :bordered="false">
                          中文文献
                        </n-tag>
                        <n-tag v-else-if="task.tier" size="small" :bordered="false">
                          {{ tierTextMap[task.tier] || task.tier }}
                        </n-tag>
                      </div>
                      <div class="task-row-meta">
                        <span>{{ formatTime(task.created_at) }}</span>
                        <span v-if="task.last_read_page">
                          上次读到第 {{ task.last_read_page }} 页
                        </span>
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
                        {{ task.status === 'completed' ? (task.last_read_page ? '继续读' : '开始阅读') : '查看进度' }}
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

          <section v-if="view === 'library' && !tasks.length" class="page-section">
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

          <!-- 形态：健康状态正常时不出现，只在异常时提醒 -->
          <section
            v-if="view === 'library' && backendStatus !== 'ok'"
            class="page-section status-row"
          >
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
