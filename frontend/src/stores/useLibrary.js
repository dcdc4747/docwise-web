/**
 * 我的库（L1）：列表、上传、取消 / 重试 / 删除、完成横幅、进行中任务条，
 * 以及那组**任务弹层**（文档信息 / 详情 / 问题反馈 / 删除确认 / 换档位重译）。
 *
 * **为什么单独一个模块**：App.vue 里「L1 库页」+「上传」+「任务动作」+「弹层」原本是一整片，
 * 5 个人同时改那一个文件，谁动一下都碰着别人。分开之后各改各的。
 *
 * ⚠️ **状态定义在模块顶层（单例），不在函数里面**：定义在函数里的话，每次调用都会新建一份
 * 「上传卡展开没有」，两个组件看到的就不一样了。
 *
 * ⚠️ **依赖方向只有"它 → useReader"这一条**：库页点卡片要调阅读区的「打开」、
 * 任务动作要读 `currentTask`。反过来阅读区刷新列表要用 `loadTasksAndSync`，
 * 所以**那一份由 App.vue 注入**（`initLibrary`，与 `useAsk` 的 `initAsk` 同一个路子），
 * 本模块不 import `useReader` 的反方向，环就断了。
 */

import { computed, ref } from 'vue'

import { authFetch } from '../auth'
import { parseBlockId } from '../blockLabel'
import { formatDuration, relativeTime, runningLine } from '../progressText'
import {
  currentTask,
  fetchTaskDetail,
  openTask,
  refreshWorkbench,
  stopProgress,
} from './useReader'
import {
  ACTIVE_STATES,
  RETRYABLE_STATES,
  historyLoading,
  loadTasks,
  statusChipMap,
  statusTextMap,
  tasks,
  tierTextMap,
} from './useTasks'
import { closeMenus, setNote, showToast } from './useUi'

// ============================================================ 外壳注入（App.vue 调一次）

/** 当前屏（L1 库页 / L2 阅读工作区）。删除当前正在读的那篇时要把屏切回库页。 */
let view = { value: 'library' }
/** 把地址写进 hash（`expectedHash` 防来回触发那套接线在外壳里）。 */
let navigateToHash = () => {}

/**
 * 注入外壳能力。**在 App.vue 里调一次即可**。
 * @param {{view: import('vue').Ref, navigateToHash: Function}} deps
 */
export function initLibrary({ view: shellView, navigateToHash: shellNavigateToHash }) {
  view = shellView
  navigateToHash = shellNavigateToHash
}

// ============================================================ L1 库页

// `tasks` / `historyLoading` / `historyError` / `loadTasks` 已搬进 stores/useTasks
// （阅读区也要按 id 找那一篇，所以它单独一个小 store：两边都依赖它、它不依赖任何 store，环就断了）

/**
 * 拉列表 + 拉完对"进行中那条"补详情。
 * 后者要读阅读区的 `currentTask`，所以这两步**包在一起**留在这里（`loadTasks` 只管取数据）。
 */
export async function loadTasksAndSync() {
  await loadTasks()
  syncActiveDetail()
}

/** 有历史时上传卡默认收起，走标题行的「＋ 上传 PDF」展开（形态：库页主角是论文卡片）。 */
export const showUpload = ref(false)
export const selectedTier = ref('medium')
export const selectedLang = ref('en')
export const uploading = ref(false)
export const uploadError = ref('')
export const deleteConfirmId = ref(null)
export const taskActionBusy = ref(false)
export const taskActionError = ref('')
export const dismissedBannerId = ref(null)
export const fileInput = ref(null)
/** 首屏示例入口在"没有可读论文"时点亮上传卡用（1.6 秒后自动收回）。 */
export const dropHinting = ref(false)
let dropHintTimer = null

/**
 * 可选档位只有两个。
 *
 * **精档已从选项里拿掉（2026-09-30）**：`engine/registry.py` 里 `Tier.PRECISE` 一直映射到
 * `MediumEngine`，也就是说选了精档实际跑的是中档——界面上却写着"最准，多一道审校"，
 * 这是**不实宣称**（这个项目撤过一次同类话术）。多一道审校的版本还没做，
 * 所以在做出来之前**不提供这个选项**，也不在任何地方承诺它。
 * 后端 `Tier.PRECISE` 枚举**故意保留**：老任务数据与 `Tier()` 校验都还要用它。
 */
export const tierOptions = [
  { value: 'fast', label: '快档 · 最快', note: '最快，先看个大概' },
  { value: 'medium', label: '中档 · 平衡', note: '版式更稳，适合正式阅读' },
]
/** 对象是文献本身，不限于外文：中文文献不翻译，直接抽字进理解层。 */
export const langOptions = [
  { value: 'en', label: '外文文献' },
  { value: 'zh', label: '中文文献' },
]

/** 空库态（只有一篇都没有时才出大 hero）。 */
export const libraryEmpty = computed(() => !tasks.value.length && !historyLoading.value)

export const activeTasks = computed(() => tasks.value.filter((t) => ACTIVE_STATES.includes(t.status)))

/**
 * 进行中任务条的页数 / 剩余秒数来自任务详情（引擎自报）——列表接口不带这些，
 * 所以进 L1 时对"那一条"补一次详情并轻量轮询；拿不到就退化成不带页数的那一行，不编。
 */
const activeDetail = ref(null)
let activeTimer = null

export const queueAheadText = computed(() => {
  const waiting = tasks.value.filter((t) => t.status === 'pending').length
  return waiting ? `队列还有 ${waiting} 篇` : ''
})

export const activeBars = computed(() =>
  activeTasks.value.map((task) => {
    const detail = activeDetail.value && activeDetail.value.id === task.id ? activeDetail.value : null
    const engine = detail ? detail.engine_progress || null : null
    const elapsed = typeof task.elapsed_seconds === 'number' ? task.elapsed_seconds : null
    const percent = engine
      ? Math.round((engine.percent ?? 0) * 100)
      : Math.round((task.progress ?? 0) * 100)
    return {
      task,
      percent,
      striped: !engine || task.status === 'pending',
      line: runningLine(task, engine, elapsed),
      queue: task.status === 'pending' ? '' : queueAheadText.value,
    }
  }),
)

/** 论文卡片（跑着 / 排队的走上面的任务条，不进网格）。 */
export const taskCards = computed(() =>
  tasks.value
    .filter((task) => !ACTIVE_STATES.includes(task.status))
    .map((task) => {
      const created = relativeTime(task.created_at)
      const tier = task.native ? '中文文献 · 不翻译' : tierTextMap[task.tier] || task.tier || ''
      const duration =
        typeof task.elapsed_seconds === 'number' && task.elapsed_seconds > 0
          ? `总耗时 ${formatDuration(task.elapsed_seconds)}`
          : ''
      let meta = [tier, duration, created].filter(Boolean).join(' · ')
      if (task.status === 'failed') meta = '翻译引擎出错，重新翻译通常可解决'
      else if (task.status === 'cancelled') {
        meta = [tier, '已取消', duration, created].filter(Boolean).join(' · ')
      }
      const retryable = task.status === 'failed' || task.status === 'cancelled'
      const primary = retryable
        ? '重新翻译'
        : task.status === 'completed'
          ? task.last_read_page
            ? '继续读'
            : '开始阅读'
          : '查看进度'
      return { task, meta, primary, retryable, chip: statusChipMap[task.status] || '' }
    }),
)

/** 完成横幅：最多保留 1 条（最新完成者），10 分钟内有效，可手动关掉（关掉能撤销）。 */
export const completedBannerTask = computed(() => {
  const done = tasks.value.find((task) => task.status === 'completed' && task.finished_at)
  if (!done || done.id === dismissedBannerId.value) return null
  const finishedAt = new Date(done.finished_at).getTime()
  if (!Number.isFinite(finishedAt)) return null
  return Date.now() - finishedAt < 10 * 60 * 1000 ? done : null
})

export const bannerMeta = computed(() => {
  const task = completedBannerTask.value
  if (!task) return ''
  const tier = task.native ? '中文文献' : tierTextMap[task.tier] || task.tier || ''
  const duration =
    typeof task.elapsed_seconds === 'number' && task.elapsed_seconds > 0
      ? `用了 ${formatDuration(task.elapsed_seconds)}`
      : ''
  return [task.filename, tier, duration].filter(Boolean).join(' · ')
})

/** L1 的进行中任务条要有真实页数 / 剩余秒数 → 对"那一条"补详情并轻量轮询。 */
export async function syncActiveDetail() {
  const task = activeTasks.value[0]
  if (!task) {
    activeDetail.value = null
    if (activeTimer) {
      clearInterval(activeTimer)
      activeTimer = null
    }
    return
  }
  if (currentTask.value && currentTask.value.id === task.id) {
    activeDetail.value = currentTask.value
  } else {
    try {
      const res = await authFetch(`/api/tasks/${task.id}`)
      if (res.ok) activeDetail.value = await res.json()
    } catch {
      /* 拿不到就退化成不带页数的那一行，不编 */
    }
  }
  if (!activeTimer) activeTimer = setInterval(syncActiveDetail, 2500)
}

/** 首屏三枚标签：打开最近一篇能读的论文并切到对应副页签；一篇都没有就直说并把上传卡点亮。 */
export function openExample(tab) {
  const readable = tasks.value.find((task) => task.status === 'completed')
  if (!readable) {
    // 库里一篇都读不了（空库态才会看到这三枚标签）：**不许假装打开了示例**——
    // 我们没有内置示例论文，所以如实说，并把落点指到上传卡上（否则点了像没反应）
    showToast('还没有可读的论文——先传一篇 PDF，导读 / 术语 / 问答都在阅读工作区里')
    setNote('示例入口要有论文才打得开：先在上面传一篇 PDF，或等正在翻译的那篇跑完。')
    flashDropCard()
    return
  }
  openTask(readable, { tab })
}

/** 把上传卡展开并高亮一下（提示"下一步在这里"），1.6 秒后自动收回高亮。 */
export function flashDropCard() {
  showUpload.value = true
  dropHinting.value = true
  if (dropHintTimer) clearTimeout(dropHintTimer)
  dropHintTimer = setTimeout(() => {
    dropHinting.value = false
  }, 1600)
}

// ---- 上传 ----

export function pickFile(tier) {
  if (tier) selectedTier.value = tier
  if (fileInput.value) fileInput.value.click()
}

export function onFilePicked(event) {
  const file = event.target.files ? event.target.files[0] : null
  event.target.value = ''
  if (file) startUpload(file)
}

export function onDrop(event) {
  const file = event.dataTransfer && event.dataTransfer.files ? event.dataTransfer.files[0] : null
  if (file) startUpload(file)
}

export async function startUpload(file) {
  uploading.value = true
  uploadError.value = ''
  stopProgress()
  const form = new FormData()
  form.append('file', file)
  form.append('tier', selectedTier.value)
  form.append('source_lang', selectedLang.value)
  form.append('target_lang', 'zh')
  try {
    const res = await authFetch('/api/tasks/upload', { method: 'POST', body: form })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail || `上传失败（HTTP ${res.status}）`)
    }
    const task = await res.json()
    await loadTasksAndSync()
    await openTask(task)
  } catch (err) {
    uploadError.value = err.message || '上传失败，请重试'
  } finally {
    uploading.value = false
  }
}

// ---- 任务动作（取消 / 重试 / 删除）----

export async function cancelTask(task) {
  closeMenus()
  taskActionBusy.value = true
  try {
    const res = await authFetch(`/api/tasks/${task.id}/cancel`, { method: 'POST' })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(body.detail || `取消失败（HTTP ${res.status}）`)
    await loadTasksAndSync()
    if (currentTask.value && currentTask.value.id === task.id) await refreshWorkbench(task.id)
    showToast('已请求取消这篇的翻译')
  } catch (err) {
    taskActionError.value = err.message || '取消失败'
    setNote(`取消失败：${taskActionError.value}`)
  } finally {
    taskActionBusy.value = false
  }
}

export async function retryTask(task) {
  closeMenus()
  taskActionBusy.value = true
  try {
    const res = await authFetch(`/api/tasks/${task.id}/retry`, { method: 'POST' })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(body.detail || `重试失败（HTTP ${res.status}）`)
    await loadTasksAndSync()
    if (currentTask.value && currentTask.value.id === task.id) await openTask(body)
    else showToast('已重新排队，进度在库页的任务条上')
  } catch (err) {
    taskActionError.value = err.message || '重试失败'
    setNote(`重试失败：${taskActionError.value}`)
  } finally {
    taskActionBusy.value = false
  }
}

export async function deleteTask(task) {
  if (!task) return
  closeMenus()
  taskActionBusy.value = true
  try {
    const res = await authFetch(`/api/tasks/${task.id}`, { method: 'DELETE' })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(body.detail || `删除失败（HTTP ${res.status}）`)
    deleteConfirmId.value = null
    if (currentTask.value && currentTask.value.id === task.id) {
      stopProgress()
      currentTask.value = null
      // 同 backToLibrary：状态直接设对，地址跟着改（地址没变也不能把"回库页"吞掉）
      view.value = 'library'
      navigateToHash({ name: 'library' }, { replace: true })
    }
    await loadTasksAndSync()
    showToast(`已删除「${task.filename}」——结果文件一并清除，不能恢复`)
  } catch (err) {
    taskActionError.value = err.message || '删除失败'
    setNote(`删除失败：${taskActionError.value}`)
  } finally {
    taskActionBusy.value = false
    closePanel()
  }
}

export function dismissBanner(task) {
  dismissedBannerId.value = task.id
  showToast('已收起完成提示', {
    label: '撤销',
    run: () => {
      dismissedBannerId.value = null
    },
  })
}

// ---- 弹层面板（文档信息 / 详情 / 问题反馈 / 删除确认 / 换档位重译）----

export const panel = ref('')
export const panelTask = ref(null)
export const panelDetail = ref(null)
export const panelLoading = ref(false)

export const panelData = computed(() => panelDetail.value || panelTask.value)

export async function openPanel(kind, task) {
  closeMenus()
  const target = task || currentTask.value
  panel.value = kind
  panelTask.value = target
  panelDetail.value = target && target.blocks ? target : null
  if (kind !== 'delete' && kind !== 'retier' && target && !target.blocks) {
    panelLoading.value = true
    panelDetail.value = await fetchTaskDetail(target.id)
    panelLoading.value = false
  }
}

export function closePanel() {
  panel.value = ''
  panelTask.value = null
  panelDetail.value = null
  panelLoading.value = false
}

export const panelFactRows = computed(() => {
  const task = panelData.value
  if (!task) return []
  const blocksHere = task.blocks || []
  const pages = new Set()
  blocksHere.forEach((block) => {
    const parsed = parseBlockId(block.block_id)
    if (parsed) pages.add(parsed.page)
  })
  const rows = [
    { k: '文件名', v: task.filename || '—' },
    { k: '档位', v: task.native ? '中文文献 · 不翻译' : tierTextMap[task.tier] || task.tier || '—' },
    { k: '状态', v: statusTextMap[task.status] || task.status },
    { k: '页数', v: pages.size ? `${pages.size} 页` : '还没有分块结果' },
    { k: '上传时间', v: task.created_at ? new Date(task.created_at).toLocaleString('zh-CN') : '—' },
    {
      k: '完成用时',
      v:
        typeof task.elapsed_seconds === 'number' && task.elapsed_seconds > 0
          ? formatDuration(task.elapsed_seconds)
          : '—',
    },
  ]
  if (task.error_message) rows.push({ k: '失败原因', v: task.error_message })
  return rows
})

export const feedbackText = computed(() => {
  const task = panelData.value
  if (!task) return ''
  return [
    `任务号：${task.id}`,
    `文件名：${task.filename}`,
    `档位：${task.native ? '中文文献 · 不翻译' : tierTextMap[task.tier] || task.tier || '—'}`,
    `状态：${statusTextMap[task.status] || task.status}`,
    `上传时间：${task.created_at || '—'}`,
    `失败原因：${task.error_message || '（无）'}`,
  ].join('\n')
})

export async function copyFeedback() {
  try {
    if (navigator.clipboard) await navigator.clipboard.writeText(feedbackText.value)
    setNote('反馈信息已复制——把它发给管理员即可，里面带着任务号。')
  } catch {
    setNote('这个浏览器不让读剪贴板——手动选中复制即可')
  }
}

/** 「换档位重译…」：新建一个任务（原任务保留）。原稿不在结果产物里，所以要重选一次 PDF。 */
export function pickTierForRetranslate(tier) {
  closePanel()
  selectedLang.value = 'en'
  pickFile(tier)
  setNote(`已选「${tierTextMap[tier]}」——在弹出的选择框里挑同一份 PDF 即可新建任务，原任务保留。`)
}

// 顶部「⋯」菜单 6 项：文档信息 / 重试翻译（本档）/ 换档位重译… / 详情 / 问题反馈… / 删除…
// 规矩：永远单层级、不超过 7 项、任意两项的动作名不许共享动词。
export const canRetryCurrent = computed(() => RETRYABLE_STATES.includes(currentTask.value?.status))

export function retryCurrent() {
  if (currentTask.value) retryTask(currentTask.value)
}
export function openDeletePanel() {
  openPanel('delete', currentTask.value)
}

// ============================================================ 收尾

/**
 * 清掉本模块的定时器。**组件卸载时必须调**（App.vue 的 onUnmounted 里）——
 * 状态搬走了，定时器也跟着搬走了；卸载时再去 `clearInterval(activeTimer)` 会报
 * `activeTimer is not defined`，一条用例挂掉会连累后面几十条（上一轮真踩过）。
 */
export function disposeLibrary() {
  if (activeTimer) clearInterval(activeTimer)
  if (dropHintTimer) clearTimeout(dropHintTimer)
  activeTimer = null
  dropHintTimer = null
  // 视图级的瞬时状态跟着一起收回默认值：状态变成模块单例之后它们会跨挂载残留
  // （"上传卡展开没有"在真应用里只挂载一次所以看不出来；测试里每个用例都重挂一次就现形了）。
  // 这与 `disposeUi` 是同一个理由，上一轮的教训就是"搬走状态也要搬走它的收尾"。
  showUpload.value = false
  dropHinting.value = false
  deleteConfirmId.value = null
}
