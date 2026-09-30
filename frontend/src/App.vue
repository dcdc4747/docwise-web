<script setup>
/**
 * docwise 前端主组件：L1「我的论文」库页 / L2 阅读工作区 两级结构。
 *
 * 形态与样式**全部照** `frontend/prototype/product-form.html`（设计权威）搬过来：
 * - 结构：模板里的层级与类名与原型一一对应（topbar / lib-wrap / hero / upload-card /
 *   grid3 / reader-top / thin-bar / note-line / doc-pane / assist / tabs / chips /
 *   thread / guide-card / termlist / composer / sheet / toast …）；
 * - 交互：原型末尾那段命令式 JS 在这里**重写成响应式状态**（openMenu / assistTab /
 *   flashId / sheetState / selChip / toast …），不再用 querySelector 查改 DOM；
 *   只有"把某一段滚进视野"本来就必须命令式，用 Vue 的模板 ref 做，不用 getElementById。
 *
 * 三条不能违反的硬约束（都写在 docs/产品形态说明.md 第四节）：
 * ① 出处永远说人话（2026-09-17 口径修订后是「第 X 页 ·「这一句的开头…」」——**不再说第几段**，
 *   段号靠 PDF 版面切分算、在没见过的期刊上只有五六成准，不准的段号比没有更糟；块编号只进 title / 详情）；
 * ② 死链不许做成活链样式（无出处的要点置灰不可点，并说明为什么没有）；
 * ③ 坐标只在有出处时才显示（术语表没有出处字段 → 命中后才回填）。
 */
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
import PdfPane from './components/PdfPane.vue'
import {
  enginePageText,
  etaTextFor,
  formatDuration,
  queueText,
  relativeTime,
  runningLine,
  stageTextFor,
} from './progressText'
import {
  buildParagraphRows,
  findBlockByText,
  mergeSourceRuns,
  parseBlockId,
  sourceLabel,
} from './blockLabel'
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

// ============================================================ 菜单 / 提示 / toast

/** 当前展开的下拉菜单（单层级、互斥展开、点外关闭）——对应原型里的 .menu.open。 */
const openMenu = ref('')
const menuNote = ref('')
let noteTimer = null

function toggleMenu(name) {
  openMenu.value = openMenu.value === name ? '' : name
}
function closeMenus() {
  openMenu.value = ''
}
/** 菜单项 / 动作的一句话说明（原型用同一机制把 data-note 显示在 .note-line 上）。 */
function setNote(text, holdMs = 6000) {
  menuNote.value = text || ''
  if (noteTimer) clearTimeout(noteTimer)
  if (!text) return
  noteTimer = setTimeout(() => {
    menuNote.value = ''
  }, holdMs)
}

const toast = ref({ show: false, text: '', undoLabel: '' })
let toastTimer = null
let toastUndo = null

function showToast(text, undo = null, holdMs = 3000) {
  toast.value = { show: true, text, undoLabel: undo ? undo.label : '' }
  toastUndo = undo || null
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toast.value = { show: false, text: '', undoLabel: '' }
    toastUndo = null
  }, holdMs)
}
function runToastUndo() {
  const action = toastUndo
  toast.value = { show: false, text: '', undoLabel: '' }
  toastUndo = null
  if (toastTimer) clearTimeout(toastTimer)
  if (action && action.run) action.run()
}

// ============================================================ L1 库页

const tasks = ref([])
const historyLoading = ref(false)
const historyError = ref('')
/** 有历史时上传卡默认收起，走标题行的「＋ 上传 PDF」展开（形态：库页主角是论文卡片）。 */
const showUpload = ref(false)
const selectedTier = ref('medium')
const selectedLang = ref('en')
const uploading = ref(false)
const uploadError = ref('')
const deleteConfirmId = ref(null)
const taskActionBusy = ref(false)
const taskActionError = ref('')
const dismissedBannerId = ref(null)
const fileInput = ref(null)
/** 首屏示例入口在"没有可读论文"时点亮上传卡用（1.6 秒后自动收回）。 */
const dropHinting = ref(false)
let dropHintTimer = null

/** 档位只有一个写法（形态硬约定）：选择处、工具条、卡片一律用这一套。 */
const tierTextMap = {
  fast: '快档 · 最快',
  medium: '中档 · 平衡',
  // 历史任务里若出现过精档，如实显示"未开放"，不写"最准"——那个能力还没做
  precise: '精档（未开放）',
}
/**
 * 可选档位只有两个。
 *
 * **精档已从选项里拿掉（2026-09-30）**：`engine/registry.py` 里 `Tier.PRECISE` 一直映射到
 * `MediumEngine`，也就是说选了精档实际跑的是中档——界面上却写着"最准，多一道审校"，
 * 这是**不实宣称**（这个项目撤过一次同类话术）。多一道审校的版本还没做，
 * 所以在做出来之前**不提供这个选项**，也不在任何地方承诺它。
 * 后端 `Tier.PRECISE` 枚举**故意保留**：老任务数据与 `Tier()` 校验都还要用它。
 */
const tierOptions = [
  { value: 'fast', label: '快档 · 最快', note: '最快，先看个大概' },
  { value: 'medium', label: '中档 · 平衡', note: '版式更稳，适合正式阅读' },
]
/** 对象是文献本身，不限于外文：中文文献不翻译，直接抽字进理解层。 */
const langOptions = [
  { value: 'en', label: '外文文献' },
  { value: 'zh', label: '中文文献' },
]

const ACTIVE_STATES = ['pending', 'in_progress']
const RETRYABLE_STATES = ['failed', 'cancelled']
const TERMINAL_STATES = ['completed', 'failed', 'cancelled']

const statusTextMap = {
  pending: '排队中',
  in_progress: '翻译中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}
/** 状态胶囊配色（照原型：已完成=绿、失败=红、已取消=橙、其余=灰）。 */
const statusChipMap = { completed: 'ok', failed: 'fail', cancelled: 'warn' }

const isAdmin = computed(() => authUser.value?.role === 'admin')
const accountLabel = computed(() => {
  const user = authUser.value
  if (!user) return ''
  return `${user.username}（${user.role === 'admin' ? '管理员' : '普通用户'}）`
})

/** 空库态（只有一篇都没有时才出大 hero）。 */
const libraryEmpty = computed(() => !tasks.value.length && !historyLoading.value)

const activeTasks = computed(() => tasks.value.filter((t) => ACTIVE_STATES.includes(t.status)))

/**
 * 进行中任务条的页数 / 剩余秒数来自任务详情（引擎自报）——列表接口不带这些，
 * 所以进 L1 时对"那一条"补一次详情并轻量轮询；拿不到就退化成不带页数的那一行，不编。
 */
const activeDetail = ref(null)
let activeTimer = null

const queueAheadText = computed(() => {
  const waiting = tasks.value.filter((t) => t.status === 'pending').length
  return waiting ? `队列还有 ${waiting} 篇` : ''
})

const activeBars = computed(() =>
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
const taskCards = computed(() =>
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
const completedBannerTask = computed(() => {
  const done = tasks.value.find((task) => task.status === 'completed' && task.finished_at)
  if (!done || done.id === dismissedBannerId.value) return null
  const finishedAt = new Date(done.finished_at).getTime()
  if (!Number.isFinite(finishedAt)) return null
  return Date.now() - finishedAt < 10 * 60 * 1000 ? done : null
})

const bannerMeta = computed(() => {
  const task = completedBannerTask.value
  if (!task) return ''
  const tier = task.native ? '中文文献' : tierTextMap[task.tier] || task.tier || ''
  const duration =
    typeof task.elapsed_seconds === 'number' && task.elapsed_seconds > 0
      ? `用了 ${formatDuration(task.elapsed_seconds)}`
      : ''
  return [task.filename, tier, duration].filter(Boolean).join(' · ')
})

// ============================================================ L2 阅读工作区

const currentTask = ref(null)
/** 左栏三选一：段落精读（自己的 DOM，锚点才成立）/ 纯中文 PDF / 双语 PDF。 */
const docMode = ref('paragraph')
/** 右助手三个副页签：问答 ｜ 导读 ｜ 术语（页签数不再增加）。 */
const assistTab = ref('ask')
const assistTabs = [
  { key: 'ask', label: '问答' },
  { key: 'guide', label: '导读' },
  { key: 'terms', label: '术语' },
]

const blocks = ref([])
/** 从段落精读切到 PDF 时要落在第几页（1 起；0/1 = 从头）。 */
const pdfStartPage = ref(0)
/** 段落精读里"当前读到第几页"（滚动时更新）——切到 PDF 模式要接着读，不能每次都回第 1 页。 */
const currentPage = ref(1)
const fileAvailability = ref({ mono: false, dual: false })
const taskDetailError = ref('')
const taskDetailLoading = ref(false)

/**
 * 内部用：块编号 → 出处的**人话标签**（「第 X 页 ·「这一句的开头…」」）。
 *
 * **只说页码、不说第几段**（2026-09-17 口径）：段号靠版面切分算，实测在没见过的期刊上
 * 只有五六成准；而不准的段号比没有更糟——用户会拿它去数，数不上就不信整条出处了。
 * 让人信的是"点下去那几句被高亮"（按文字匹配算的，不依赖分段）+ 标签上就写着是哪一句。
 * 解析不出返回空串，由调用方写「位置待定」。
 *
 * @param {string} blockId 决定页码的那一块
 * @param {string} [text] 合并后的整句（见 mergeSourceRuns）；不传就用这一块自己的文字
 */
function labelOf(blockId, text) {
  return sourceLabel(blockId, blocks.value, text ? { text } : {})
}

const isNativeTask = computed(() => currentTask.value?.native === true)
const isRunning = computed(() => currentTask.value?.status === 'in_progress')

// ---- 诚实进度（引擎自报，读不到就直说"还没报"）----
const engineProgress = ref(null)
let elapsedBase = { seconds: null, at: Date.now() }
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

const elapsedSeconds = computed(() => {
  const task = currentTask.value
  if (!task || typeof elapsedBase.seconds !== 'number') return null
  const drift = task.status === 'in_progress' ? Math.max(0, (elapsedTick.value - elapsedBase.at) / 1000) : 0
  return elapsedBase.seconds + drift
})

const stageText = computed(() => stageTextFor(currentTask.value, engineProgress.value))
const progressPercent = computed(() => {
  const task = currentTask.value
  if (!task) return 0
  if (task.status === 'in_progress' && engineProgress.value) {
    return Math.round((engineProgress.value.percent ?? 0) * 100)
  }
  return Math.round((task.progress ?? 0) * 100)
})

/** 细进度条永远在：知道多少画多少，不知道就画流动条纹（绝不编一个百分比）。 */
const thinBar = computed(() => {
  const task = currentTask.value
  if (!task) return { width: '0%', striped: false }
  if (task.status === 'in_progress') {
    if (engineProgress.value) return { width: `${progressPercent.value}%`, striped: false }
    return { width: '100%', striped: true }
  }
  if (task.status === 'pending') return { width: '100%', striped: true }
  if (task.status === 'completed') return { width: '100%', striped: false }
  return { width: `${progressPercent.value}%`, striped: false }
})

/** 工具条上的页数胶囊：跑着用引擎自报，跑完说总页数，都没有就不显示（不编）。 */
const docPageCount = computed(() => {
  const pages = new Set()
  blocks.value.forEach((block) => {
    const parsed = parseBlockId(block.block_id)
    if (parsed) pages.add(parsed.page)
  })
  return pages.size
})

const pageChipText = computed(() => {
  const task = currentTask.value
  if (!task) return ''
  if (task.status === 'pending') return queueText(task)
  if (task.status === 'in_progress') return enginePageText(engineProgress.value)
  return docPageCount.value ? `共 ${docPageCount.value} 页` : ''
})

/** .note-line：优先显示刚点过的菜单项说明，其次显示进行中的诚实进度。 */
const noteLineText = computed(() => {
  if (menuNote.value) return menuNote.value
  const task = currentTask.value
  if (task && (task.status === 'in_progress' || task.status === 'pending')) {
    return runningLine(task, engineProgress.value, elapsedSeconds.value)
  }
  return ''
})

// ---- 左栏：段落精读 / 原版 PDF ----

/** 这批块里到底有没有译文？实测全库 task_blocks.translated 一律为空（见项目记忆）。 */
const hasBlockTranslations = computed(() =>
  blocks.value.some((block) => (block.translated || '').trim().length > 0),
)

/**
 * 段落精读的行：块 + 跨页分隔。段号按页内重算（buildParagraphRows 负责）。
 * 主文 = 译文；没有译文时回退原文——**但绝不把同一段英文显示两遍**。
 */
const paragraphRows = computed(() =>
  buildParagraphRows(blocks.value).map((row) =>
    row.kind === 'block'
      ? {
          ...row,
          main: (row.block.translated || '').trim() || row.block.text || '',
          source: row.block.text || '',
        }
      : row,
  ),
)

/** 桌面：按页包成 .page（原型里每页一张"纸"），页内两栏。 */
const docPages = computed(() => {
  const pages = []
  paragraphRows.value.forEach((row) => {
    if (row.kind === 'page') {
      pages.push({ key: `p${row.page}`, page: row.page, label: `（${row.label}）`, rows: [] })
      return
    }
    if (!pages.length) pages.push({ key: 'p-unknown', page: null, label: '', rows: [] })
    pages[pages.length - 1].rows.push(row)
  })
  return pages
})

/**
 * 手机段落视图的行：**首页不插页分隔条**（正文从「段 1」直接开始），
 * 只在跨页处插一条「第 N 页」——原型就是这么排的。
 */
const pdocRows = computed(() => {
  let seenFirstPage = false
  return paragraphRows.value.filter((row) => {
    if (row.kind !== 'page') return true
    if (!seenFirstPage) {
      seenFirstPage = true
      return false
    }
    return true
  })
})

const docTitle = computed(() => (currentTask.value?.filename || '').replace(/\.pdf$/i, ''))

const docMetaLine = computed(() => {
  const task = currentTask.value
  if (!task) return ''
  const parts = []
  if (docPageCount.value) parts.push(`${docPageCount.value} 页`)
  parts.push(task.native ? '中文文献 · 不翻译' : tierTextMap[task.tier] || task.tier)
  const created = relativeTime(task.created_at)
  if (created) parts.push(`${created}上传`)
  return parts.filter(Boolean).join(' · ')
})

const docModeOptions = computed(() => {
  const options = [{ value: 'paragraph', label: '段落精读' }]
  if (fileAvailability.value.mono) {
    options.push({ value: 'mono', label: isNativeTask.value ? '原文 PDF' : '纯中文 PDF' })
  }
  if (fileAvailability.value.dual && !isNativeTask.value) {
    options.push({ value: 'dual', label: '双语 PDF' })
  }
  return options
})

const docModeLabel = computed(
  () => docModeOptions.value.find((item) => item.value === docMode.value)?.label || '段落精读',
)

const docEmptyText = computed(() => {
  const task = currentTask.value
  if (!task) return ''
  if (task.status === 'pending') return '这篇还在排队，轮到它就开始翻译。'
  if (task.status === 'in_progress') return '正在翻译这篇文献，进度看上面那条细进度条。'
  if (task.status === 'failed') {
    return task.error_message ? `这次翻译没成功：${task.error_message}` : '这次翻译没成功。'
  }
  if (task.status === 'cancelled') {
    return '这次翻译已取消；要重来的话点右上角「⋯」→「重试翻译（本档）」。'
  }
  return '这篇文献还没有可读的段落块。'
})

/**
 * 没有块级译文时的诚实提示（**必须保留**：库里的译文只存在于 PDF 产物里，
 * 段落视图拿不到，所以下面显示的是原文——不许拿术语拼、不许现场翻译充数）。
 */
const noBlockTranslationNotice = computed(
  () =>
    !isNativeTask.value &&
    currentTask.value?.status === 'completed' &&
    !hasBlockTranslations.value &&
    blocks.value.length > 0,
)

/**
 * 扫描件的诚实提示（**必须有**）：这份文献没有文字层，文字是**本地 OCR 认出来的**，
 * 可能有个别错字，出处与引用也按识别结果给。不说这一句，用户会把 OCR 的错当成原文的错。
 */
const scannedNotice = computed(() => currentTask.value?.text_source === 'ocr')

// ---- 出处跳转（点击必闪烁；定位不到就诚实说）----

const blockEls = new Map()
function setBlockEl(blockId, el) {
  if (el) blockEls.set(blockId, el)
  else blockEls.delete(blockId)
}

const flashId = ref('')
const honestNote = ref('')
let flashTimer = null

const docPaneEl = ref(null)
const assistBodyEl = ref(null)
function setAssistBody(el) {
  assistBodyEl.value = el
}

const pageEls = new Map()
function setPageEl(page, el) {
  if (el && page !== null) pageEls.set(page, el)
  else if (page !== null) pageEls.delete(page)
}

/** 滚到某个元素：容器是左栏那个滚动区，别把整个窗口带跑。 */
function scrollWithinPane(el) {
  const pane = docPaneEl.value
  if (!pane || !el || !pane.scrollTo) return
  const top = el.getBoundingClientRect().top - pane.getBoundingClientRect().top + pane.scrollTop
  pane.scrollTo({ top: Math.max(0, top - 24), behavior: 'smooth' })
}

/**
 * 点出处 → 定位到原文那一段。
 *
 * 两条路（段落精读与 PDF 是两套渲染，但**都要真的落到那一段上**）：
 * ① **段落精读**：我们自己的 DOM → 滚入视口中部 + 高亮脉冲一次（形态硬约束④）。
 * ② **原版 / 纯中文 / 双语 PDF**：交给 `<PdfPane>`（pdf.js 渲染 + 文字层索引）——
 *    按块文本在文字层里找，找到就滚过去 + 画高亮框，还会在文字层里如实回报"对没对上"。
 *    对不上时它只翻到那一页、**一个高亮框都不画**，由 `onPdfLocate` 把话说清楚
 *    （纯中文稿里是中文译文、块里存的是原文，本来就对不上——宁可不给，也不假高亮）。
 */
async function traceTo(blockId, { silent = false, text = '' } = {}) {
  if (!blockId) return false
  const parsed = parseBlockId(blockId)
  const page = parsed ? parsed.page + 1 : 0

  if (docMode.value !== 'paragraph') {
    if (!page) {
      if (!silent) {
        honestNote.value = '这段没能定位到页码（编号里没有可用的页序）——宁可不给，也不假跳转。'
      }
      return false
    }
    honestNote.value = ''
    await locateBlockInPdf(blockId, text)
    return true
  }

  await nextTick()
  const el = blockEls.get(blockId)
  if (!el) {
    if (!silent) {
      honestNote.value = '这段没能定位到原文块（原文里没有对应段落）——宁可不给，也不假高亮。'
    }
    return false
  }
  honestNote.value = ''
  if (isNarrow.value) {
    sheetState.value = 'peek'
    locatedHint.value = `已定位到 ${labelOf(blockId) || '该段落'}`
  }
  if (el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  flashId.value = ''
  await nextTick()
  flashId.value = blockId
  if (flashTimer) clearTimeout(flashTimer)
  flashTimer = setTimeout(() => {
    flashId.value = ''
  }, 2400)
  return true
}

/** 划词浮标 / 点段落选中（桌面才是句子级；手机热区收窄到段号，不与系统手势抢） */

const selChip = ref(null)
/** 段落精读里"点中的那一段"（选中态一直留着，点别处才灭）——和 PDF 那边的选中一个道理。 */
const pickedBlockId = ref('')

/** 点某一段的正文：**这一段当场点亮**（.sel），并在它上方浮出「就这句提问」。
 *
 * 与划词的关系：选中了文字就按划词走（句子级锚点），没选中就是"点了这一段"。
 * 两条路都会把锚点块放进 `selChip.blockId`，所以提问时带的是同一个坐标系。
 */
function onBlockClick(row, event) {
  const selection = typeof window !== 'undefined' && window.getSelection ? window.getSelection() : null
  const selected = (selection && selection.toString ? selection.toString() : '').trim()
  if (selected) return // 划词优先，交给 onDocMouseUp 处理
  const el = event && event.currentTarget
  const pageEl = el && el.closest ? el.closest('.page') : null
  if (!el || !pageEl) return
  // 同一段再点一次 = 取消选中
  if (pickedBlockId.value === row.block.block_id) {
    pickedBlockId.value = ''
    selChip.value = null
    return
  }
  const rect = el.getBoundingClientRect()
  const pageRect = pageEl.getBoundingClientRect()
  const text = (row.source || row.main || '').trim()
  pickedBlockId.value = row.block.block_id
  selChip.value = {
    pageKey: pageEl.dataset.pageKey || '',
    blockId: row.block.block_id,
    text: text.slice(0, 200),
    left: Math.max(0, rect.left - pageRect.left),
    top: Math.max(0, rect.top - pageRect.top - 30),
  }
}

function onDocMouseUp(event, pageEl) {
  const selection = typeof window !== 'undefined' && window.getSelection ? window.getSelection() : null
  const text = (selection && selection.toString ? selection.toString() : '').trim()
  if (!text || !pageEl) {
    selChip.value = null
    return
  }
  let range = null
  try {
    range = selection.rangeCount ? selection.getRangeAt(0) : null
  } catch {
    range = null
  }
  if (!range || !range.getBoundingClientRect) {
    selChip.value = null
    return
  }
  const rect = range.getBoundingClientRect()
  if (!rect || !rect.width) {
    selChip.value = null
    return
  }
  // 锚点：选区落在哪一段 → 那个块的编号（提问锚点与出处是同一个坐标系）
  let node = selection.anchorNode
  while (node && node.nodeType !== 1) node = node.parentNode
  const holder = node && node.closest ? node.closest('[data-block-id]') : null
  const pageRect = pageEl.getBoundingClientRect()
  // 浮标默认放选区**上方**（放下方会盖住正要读的下一行）；贴顶时退回下方
  let top = rect.top - pageRect.top - 30
  if (top < 4) top = rect.bottom - pageRect.top + 10
  pickedBlockId.value = '' // 划词是句子级，跟"点中的那一段"不是一回事
  selChip.value = {
    pageKey: pageEl.dataset.pageKey || '',
    blockId: holder && holder.dataset ? holder.dataset.blockId || '' : '',
    text: text.slice(0, 200),
    left: rect.left - pageRect.left,
    top,
  }
}

/** 划词提问：提问内容里就带着选中的那句话，锚点一起带给后端。 */
function askSelectedSentence() {
  const chip = selChip.value
  if (!chip) return
  askAnchor.value = { blockId: chip.blockId, text: chip.text }
  selChip.value = null
  askQuestion.value = `就这句提问：${chip.text}`
  assistTab.value = 'ask'
  submitAsk()
}
// ============================================================ 理解层（导读 / 术语）

const understandingLoading = ref(false)
const understandingStatus = ref('pending')
const understandingGuide = ref(null)
const understandingTerms = ref([])
const understandingError = ref('')
/** 每个任务只自动试一次（失败后交给「重试」按钮，不反复烧钱）。 */
const understandingTried = ref(false)

const guideFieldLabel = {
  research_question: '研究问题',
  method: '方法',
  conclusion: '结论',
  innovation: '创新点',
  contribution: '核心贡献',
}
const guideFieldOrder = ['research_question', 'method', 'conclusion', 'innovation', 'contribution']

/**
 * 导读要点（带出处）。坐标来自后端返回的真数据 source_block_ids，所以**可以点前就显示**；
 * 没有出处的要点降级成置灰不可点（死链不许做成活链样式）。
 *
 * **出处先按"同一句被换行切断"合并**（`mergeSourceRuns`）：中文文献的块是按行切的，
 * 模型会把"上一行 + 下一行"当两个块报回来；不合并的话界面上就成了"同一句话两个出处"，
 * 各自还只高亮半句。合并后一个出处 = 一整句，点下去一次高亮完。
 */
const guidePoints = computed(() => {
  const guide = understandingGuide.value || {}
  return guideFieldOrder
    .map((key) => {
      const field = guide[key] || {}
      const ids = Array.isArray(field.source_block_ids) ? field.source_block_ids : []
      return {
        key,
        label: guideFieldLabel[key],
        text: field.text || '',
        sources: mergeSourceRuns(ids, blocks.value).map((run) => {
          const label = labelOf(run.id, run.text)
          return { id: run.id, ids: run.ids, text: run.text, label, found: Boolean(label) }
        }),
      }
    })
    .filter((point) => point.text)
})

const termItems = computed(() =>
  understandingTerms.value.map((term, index) => ({
    key: `${term.term || 'term'}-${index}`,
    term: term.term || '',
    cn: term.cn || '',
    definition: term.definition || '',
    // 术语表没有出处字段 → 按钮先只写「在原文中定位」，命中后才回填坐标（不许预填）
    locate: termLocate.value[term.term] || '在原文中定位',
  })),
)

const understandable = computed(() => currentTask.value?.status === 'completed')

const guideEmptyText = computed(() => {
  if (!understandable.value) return '文献还没翻译完，导读要等译文出来才能生成。'
  return '正在生成导读（读全文 → 提炼要点），请稍候…'
})
const termsEmptyText = computed(() => {
  if (!understandable.value) return '文献还没翻译完，术语表要等译文出来才能生成。'
  return '正在生成术语表（与导读一同产出），请稍候…'
})

// ============================================================ 问答线程

const askQuestion = ref('')
const askLoading = ref(false)
/** 提问锚点：划词（桌面）或点段号（手机）带上的那一段。 */
const askAnchor = ref(null)
let turnSeq = 0
const askThread = ref([])

/** 出处标签在渲染前就把人话坐标算好（模板里不出现函数调用）；相邻行同样先合并成一句。 */
const askTurns = computed(() =>
  askThread.value.map((turn) => ({
    ...turn,
    sources: mergeSourceRuns(turn.sourceIds || [], blocks.value).map((run) => {
      const label = labelOf(run.id, run.text)
      return { id: run.id, ids: run.ids, text: run.text, label, found: Boolean(label) }
    }),
  })),
)

const quickChips = [
  { label: '局限与不足', q: '这项研究有什么局限？' },
  { label: '未来工作', q: '论文提到的未来工作是什么？' },
  { label: '用了哪些数据', q: '研究用了哪些数据或样本？' },
  { label: '主要结果', q: '主要结果是什么？' },
  { label: '结论可靠吗', q: '这些结论有多可靠？' },
]
const askChipsHint =
  '导读已覆盖的五个要点（研究问题 / 方法 / 结论 / 创新点 / 贡献）在「导读」页签里，术语解释在「术语」页签里——这里只放它们都没答的提问'

const lastQuestion = computed(() => {
  const turns = askThread.value
  for (let i = turns.length - 1; i >= 0; i -= 1) {
    if (turns[i].question) return turns[i].question
  }
  return ''
})

const composerPlaceholder = '就这篇论文提问，或先划词再问…'

function patchTurn(id, patch) {
  askThread.value = askThread.value.map((turn) => (turn.id === id ? { ...turn, ...patch } : turn))
}

function scrollThreadToEnd() {
  nextTick(() => {
    const body = assistBodyEl.value
    if (body) body.scrollTop = body.scrollHeight
  })
}

async function submitAsk() {
  const question = (askQuestion.value || '').trim()
  if (!question || askLoading.value || !currentTask.value) return
  if (!blocks.value.length) await loadBlocks(currentTask.value.id)
  askQuestion.value = ''
  askLoading.value = true
  const id = ++turnSeq
  askThread.value = [
    ...askThread.value,
    { id, question, answer: '', sourceIds: [], mode: '', loading: true, error: '', errorDetail: '', copied: false },
  ]
  scrollThreadToEnd()
  try {
    const res = await authFetch(`/api/tasks/${currentTask.value.id}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        // 形态：提问锚点与出处是同一个坐标系——把划词 / 点段号选中的那段带给后端
        focus_block_ids: askAnchor.value && askAnchor.value.blockId ? [askAnchor.value.blockId] : [],
      }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      // 后端说清了原因就用它的原话（例：「该任务没有可提问的文本」）——
      // 别拿"网络或服务繁忙"盖上去，那是把我们自己的问题说成用户的网不好。
      const why = String(body.detail || '').trim()
      patchTurn(id, {
        loading: false,
        error: why || '没答出来，服务没有给出原因。',
        errorDetail: why ? '' : `HTTP ${res.status}`,
      })
      return
    }
    const data = await res.json()
    patchTurn(id, {
      loading: false,
      answer: data.answer || '',
      sourceIds: Array.isArray(data.source_block_ids) ? data.source_block_ids : [],
      mode: data.mode || '',
    })
  } catch (err) {
    patchTurn(id, {
      loading: false,
      // 走到这里才是真的没发出去 / 服务没响应，这时说"网络"才是对的
      error: '没答出来：请求没发出去，或服务没响应。',
      errorDetail: err.message || '',
    })
  } finally {
    askLoading.value = false
    askAnchor.value = null
    scrollThreadToEnd()
  }
}

function retryTurn(turn) {
  askThread.value = askThread.value.filter((item) => item.id !== turn.id)
  askQuestion.value = turn.question
  submitAsk()
}

function askPreset(question) {
  askQuestion.value = question
  return submitAsk()
}

/** 导读卡「就这条追问」：带着这条要点的出处段落去问，答案同样标出处。 */
function probePoint(point) {
  const anchorId = point.sources.length ? point.sources[0].id : ''
  askAnchor.value = anchorId ? { blockId: anchorId, text: point.text } : null
  askQuestion.value = `关于「${point.label}」这条，能再展开说一点吗？`
  assistTab.value = 'ask'
  if (isNarrow.value && sheetState.value === 'peek') sheetState.value = 'half'
  submitAsk()
}

async function copyAnswer(turn) {
  try {
    if (navigator.clipboard) await navigator.clipboard.writeText(turn.answer || '')
    patchTurn(turn.id, { copied: true })
    setTimeout(() => patchTurn(turn.id, { copied: false }), 1500)
  } catch {
    setNote('这个浏览器不让读剪贴板——手动选中复制即可')
  }
}

// ============================================================ 术语定位（命中后回填）

const termLocate = ref({})

async function locateTerm(item) {
  if (!currentTask.value) return
  if (!blocks.value.length) await loadBlocks(currentTask.value.id)
  const hit = findBlockByText(item.term, blocks.value) || findBlockByText(item.cn, blocks.value)
  if (!hit) {
    termLocate.value = { ...termLocate.value, [item.term]: '没找到，可能在图/表里' }
    setNote(`术语「${item.term}」没在正文段落里找到——它可能只出现在图或表里。`)
    return
  }
  const label = labelOf(hit.block_id)
  termLocate.value = {
    ...termLocate.value,
    [item.term]: label ? `已定位 · ${label}` : '已定位（位置待定）',
  }
  traceTo(hit.block_id)
}

// ============================================================ 手机端：段落视图 + 抽屉三档

const isNarrow = ref(false)
const sheetState = ref('peek')
const locatedHint = ref('')
const pdocScale = ref(1)
/** 手机上点段号浮出的「就这段提问」挂在哪一段（热区只有段号本身）。 */
const pgChipFor = ref('')

const sheetGripText = computed(() => {
  if (sheetState.value === 'peek') return '上拖展开（半屏 → 近全屏）'
  if (sheetState.value === 'full') return '下拖回到半屏'
  return '上拖到近全屏'
})

const peekSummary = computed(() =>
  lastQuestion.value
    ? `当前问题：${lastQuestion.value}`
    : '读到有问题的地方，点段落浮出「就这段提问」',
)

const assistClass = computed(() => {
  if (!isNarrow.value) return ['assist']
  return [
    'sheet',
    sheetState.value === 'peek' ? 'peek' : '',
    sheetState.value === 'full' ? 'full' : '',
  ]
})

const assistBodyClass = computed(() => (isNarrow.value ? 'sbody' : 'tabbody'))

const pdocStyle = computed(() => ({ '--pdoc-scale': String(pdocScale.value) }))

function cycleSheet() {
  const order = ['peek', 'half', 'full']
  sheetState.value = order[(order.indexOf(sheetState.value) + 1) % order.length]
}

/** 手机端点段号：浮出 / 收起「就这段提问」。段落本身就是锚点，不用划词、不用文本匹配。 */
function togglePgChip(row) {
  if (row.index === null) return
  const id = row.block.block_id
  pgChipFor.value = pgChipFor.value === id ? '' : id
}

function askParagraph(row) {
  askAnchor.value = { blockId: row.block.block_id, text: row.source }
  pgChipFor.value = ''
  askQuestion.value = '就这段提问：这段在讲什么？'
  assistTab.value = 'ask'
  sheetState.value = 'half'
  submitAsk()
}

function stepFont(delta) {
  const next = Math.round((pdocScale.value + delta * 0.1) * 10) / 10
  pdocScale.value = Math.min(1.4, Math.max(0.85, next))
}

/**
 * 手机顶栏那颗「原版 / 段落」：在段落视图与**某一份 PDF** 之间来回切。
 *
 * 按钮上写的必须是它真打开的那一份——外文文献的产物是纯中文稿 / 双语稿，
 * 写「原版」会让人以为看到的是英文原稿（我们并不存那一份），所以按实际产物命名；
 * 默认挑双语稿（原页 + 译页都在），中文文献则挑原稿。
 */
const pdfQuickMode = computed(() => {
  const rest = docModeOptions.value.filter((item) => item.value !== 'paragraph')
  if (!rest.length) return null
  if (isNativeTask.value) return rest[0]
  return rest.find((item) => item.value === 'dual') || rest[0]
})

const pdfQuickLabel = computed(() => {
  const target = pdfQuickMode.value
  if (!target) return ''
  if (target.value === 'dual') return '双语稿'
  return isNativeTask.value ? '原稿' : '纯中文稿'
})

const mobileOriginalTitle = computed(() =>
  docMode.value === 'paragraph' ? `看 ${pdfQuickLabel.value} 的 PDF` : '回到段落视图',
)

function toggleMobileOriginal() {
  if (docMode.value === 'paragraph') {
    const target = pdfQuickMode.value
    if (!target) {
      setNote(isNativeTask.value ? '这篇没有可预览的原稿 PDF。' : '这份产物还没就绪——翻译完成后才有可预览的 PDF。')
      return
    }
    setDocMode(target.value)
    return
  }
  setDocMode('paragraph')
}

/**
 * 手机上那个「▾」按钮的写法（原型写的是「中英对照 ▾」）。
 * 没有块级译文时**不许写「中英对照」**——那时候段落里只有英文原文，
 * 写对照等于假装有中文（硬约束⑦），所以退成「原文」。
 */
const mobileLangLabel = computed(() => {
  if (docMode.value !== 'paragraph') return docModeLabel.value
  return hasBlockTranslations.value ? '中英对照' : '原文'
})

function syncNarrow() {
  if (typeof window === 'undefined') return
  isNarrow.value = window.innerWidth < 1024
}

// ============================================================ 阅读位置记忆

let positionSent = { page: 0, at: 0 }

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

/** 滚动时把"当前页"记下来：取最后一个已经滚过顶部的页。 */
function onPaneScroll(event) {
  const pane = event.target
  let current = 1
  pageEls.forEach((el, page) => {
    const offset = el.getBoundingClientRect().top - pane.getBoundingClientRect().top
    if (offset <= 16) current = Math.max(current, page + 1)
  })
  currentPage.value = current
  saveReadingPosition(current)
}

/** 点「继续读」→ 回到上次位置 + toast（R-15）；没记录就不假装记得。 */
async function applyResumePosition() {
  const page = currentTask.value?.last_read_page
  if (!page || page <= 1) return false
  await nextTick()
  const el = pageEls.get(page - 1)
  if (!el) return false
  currentPage.value = page
  scrollWithinPane(el)
  return true
}

// ============================================================ 搜索（在读的这一篇里找）

const searchOpen = ref(false)
const searchTerm = ref('')

function toggleSearch() {
  searchOpen.value = !searchOpen.value
  if (!searchOpen.value) searchTerm.value = ''
}

function runSearch() {
  const needle = searchTerm.value.trim()
  if (!needle) return
  const hit = findBlockByText(needle, blocks.value)
  if (!hit) {
    setNote(`没找到含「${needle}」的段落——换个词，或换「原版 PDF」模式看图表里的字。`)
    return
  }
  setNote(`已跳到含「${needle}」的那一段：${labelOf(hit.block_id) || '位置待定'}`)
  traceTo(hit.block_id)
}

// ============================================================ 数据加载

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

async function loadTasks() {
  historyLoading.value = true
  historyError.value = ''
  try {
    const res = await authFetch('/api/tasks')
    if (!res.ok) throw new Error(`历史任务加载失败（HTTP ${res.status}）`)
    tasks.value = await res.json()
  } catch (err) {
    historyError.value = err.message || '历史任务加载失败'
  } finally {
    historyLoading.value = false
    syncActiveDetail()
  }
}

/** L1 的进行中任务条要有真实页数 / 剩余秒数 → 对"那一条"补详情并轻量轮询。 */
async function syncActiveDetail() {
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

/** 取任务全量信息（块 + 文件就绪 + 导读状态）。失败返回 null，由调用方决定怎么显示。 */
async function fetchTaskDetail(taskId) {
  taskDetailLoading.value = true
  taskDetailError.value = ''
  try {
    const res = await authFetch(`/api/tasks/${taskId}`)
    if (!res.ok) throw new Error(`任务详情加载失败（HTTP ${res.status}）`)
    return await res.json()
  } catch (err) {
    taskDetailError.value = err.message || '任务详情加载失败'
    return null
  } finally {
    taskDetailLoading.value = false
  }
}

function rememberElapsed(task) {
  elapsedBase = {
    seconds: typeof task?.elapsed_seconds === 'number' ? task.elapsed_seconds : null,
    at: Date.now(),
  }
  elapsedTick.value = Date.now()
}

async function refreshWorkbench(taskId) {
  const data = await fetchTaskDetail(taskId)
  if (!data) return null
  currentTask.value = { ...(currentTask.value || {}), ...data }
  engineProgress.value = data.engine_progress || null
  rememberElapsed(data)
  if (data.status === 'in_progress') startElapsedTimer()
  else stopElapsedTimer()
  blocks.value = data.blocks || []
  fileAvailability.value = data.files_ready || { mono: false, dual: false }
  if (!docModeOptions.value.some((item) => item.value === docMode.value)) {
    docMode.value = 'paragraph'
  }
  if (data.understanding_status === 'ready') loadUnderstanding(taskId)
  return data
}

function resetWorkbench() {
  understandReset()
  askThread.value = []
  askQuestion.value = ''
  askLoading.value = false
  askAnchor.value = null
  selChip.value = null
  pickedBlockId.value = ''
  blocks.value = []
  engineProgress.value = null
  flashId.value = ''
  honestNote.value = ''
  locatedHint.value = ''
  pgChipFor.value = ''
  termLocate.value = {}
  searchOpen.value = false
  searchTerm.value = ''
  menuNote.value = ''
  pdfStartPage.value = 0
  locateText.value = ''
  pendingBlockId.value = ''
  currentPage.value = 1
  fileAvailability.value = { mono: false, dual: false }
  sheetState.value = 'peek'
}

/** 打开任意任务到阅读工作台（历史「继续读」/ 上传后 / 首屏示例入口 走同一条路径）。 */
async function openTask(task, options = {}) {
  stopProgress()
  currentTask.value = task
  view.value = 'reader'
  assistTab.value = options.tab || 'ask'
  docMode.value = 'paragraph'
  resetWorkbench()
  assistTab.value = options.tab || 'ask'
  await refreshWorkbench(task.id)
  if (ACTIVE_STATES.includes(task.status)) startProgress(task.id)
  if (await applyResumePosition()) showToast(`已回到第 ${task.last_read_page} 页`)
}

function backToLibrary() {
  view.value = 'library'
  closeMenus()
}

/** 首屏三枚标签：打开最近一篇能读的论文并切到对应副页签；一篇都没有就直说并把上传卡点亮。 */
function openExample(tab) {
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
function flashDropCard() {
  showUpload.value = true
  dropHinting.value = true
  if (dropHintTimer) clearTimeout(dropHintTimer)
  dropHintTimer = setTimeout(() => {
    dropHinting.value = false
  }, 1600)
}

// ---- 上传 ----

function pickFile(tier) {
  if (tier) selectedTier.value = tier
  if (fileInput.value) fileInput.value.click()
}

function onFilePicked(event) {
  const file = event.target.files ? event.target.files[0] : null
  event.target.value = ''
  if (file) startUpload(file)
}

function onDrop(event) {
  const file = event.dataTransfer && event.dataTransfer.files ? event.dataTransfer.files[0] : null
  if (file) startUpload(file)
}

async function startUpload(file) {
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
    await loadTasks()
    await openTask(task)
  } catch (err) {
    uploadError.value = err.message || '上传失败，请重试'
  } finally {
    uploading.value = false
  }
}

// ---- 进度推送（SSE + 轮询兜底）----

let eventSource = null
let pollTimer = null

async function startProgress(taskId) {
  stopProgress()
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
      /* 后端暂不可达，等下一轮 */
    }
  }, 2000)
}

function applyEvent(evt) {
  if (!currentTask.value) return
  currentTask.value.status = evt.status || currentTask.value.status
  if (typeof evt.progress === 'number') currentTask.value.progress = evt.progress
  if (evt.error) currentTask.value.error_message = evt.error
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
    engineProgress.value = null
    stopElapsedTimer()
    currentTask.value.stage = null
    currentTask.value.eta_seconds = null
    loadTasks()
    if (evt.type === 'completed') refreshWorkbench(currentTask.value.id)
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

// ---- 预览 / 下载 ----
//
// 左栏三个 PDF 模式（原版 / 纯中文 / 双语）都由 `<PdfPane>` 用 pdf.js 渲染，
// **不再是 iframe**：iframe 里是浏览器自带的阅读器，拿不到文字位置，
// "点出处跳到那一段"和"点 PDF 里的段落提问"就做不到。
// 这里只负责把"要定位哪一段"传下去、把结果说成人话。

/** 要 PDF 去定位的原文（块里的 text）。 */
const locateText = ref('')
/** 每次请求定位都 +1：同一个块再点一次也要重新定位。 */
const locateKey = ref(0)
/** 正在定位的那个块编号（算"对不上时至少翻到第几页"用）。 */
const pendingBlockId = ref('')

const pdfFallbackPage = computed(() => {
  const parsed = parseBlockId(pendingBlockId.value)
  return parsed ? parsed.page + 1 : 0
})

/** 点出处时把块文本交出去定位。块还没加载就先加载（术语定位也是这个套路）。
 *  `text` 是"合并后的一整句"（相邻行合成），传了就按它高亮——一次高亮完整句。 */
async function locateBlockInPdf(blockId, text) {
  if (!currentTask.value) return
  if (!blocks.value.length) await loadBlocks(currentTask.value.id)
  const block = blocks.value.find((item) => item.block_id === blockId)
  pendingBlockId.value = blockId
  locateText.value = text || (block ? block.text || '' : '')
  locateKey.value += 1
}

/** PdfPane 的定位结果：找得到就说找到了，找不到**如实说**（宁可不给，也不假高亮）。 */
function onPdfLocate(result) {
  const label = labelOf(pendingBlockId.value) || '这一段'
  if (result.found) {
    honestNote.value = ''
    setNote(
      result.translated
        ? `已在 PDF 里高亮这段的中文译文——出处 ${label}（纯中文稿只有中文，位置是拿双语稿的原页对齐出来的）。`
        : `已在 PDF 里高亮这一段——出处 ${label}。`,
    )
    return
  }
  honestNote.value =
    '这段没能在这份 PDF 的文字层里对上——只翻到了它所在的页，没有假高亮。' +
    '（图、表、扫描页里的字没有文字层，对不上；要看那一段被高亮，切「段落精读」。）'
  setNote(result.page ? `只翻到了第 ${result.page} 页——那一段在这份 PDF 里没对上。` : '那一段没能定位到。')
}

/** PdfPane 里点了一段 → 带着这一段去提问（能对上块就用块编号当锚点）。 */
function onPdfAsk({ text, context }) {
  const block = findBlockByText(context || text, blocks.value) || findBlockByText(text, blocks.value)
  askAnchor.value = block ? { blockId: block.block_id, text } : null
  askQuestion.value = `就这段提问：${text}`
  assistTab.value = 'ask'
  if (isNarrow.value && sheetState.value === 'peek') sheetState.value = 'half'
  submitAsk()
}

async function setDocMode(mode) {
  closeMenus()
  // 渲染方式只是"看哪一份"，不改任务；产物没就绪就直说，不假装切过去了
  if (!docModeOptions.value.some((item) => item.value === mode)) {
    setNote('这份产物还没就绪——翻译完成后才有可预览的 PDF。')
    return
  }
  docMode.value = mode
  if (mode !== 'paragraph') {
    // 段落精读 → PDF：**接着读**（把当前页带过去），别每次都回到第 1 页
    pendingBlockId.value = firstBlockIdOnPage(currentPage.value)
    locateText.value = ''
    pdfStartPage.value = Math.max(1, currentPage.value)
  }
}

/** 第 N 页（人从 1 数）的第一个块编号——用它把"第几页"翻译成 PdfPane 认得的东西。 */
function firstBlockIdOnPage(page) {
  if (!page) return ''
  const hit = blocks.value.find((block) => {
    const parsed = parseBlockId(block.block_id)
    return parsed && parsed.page + 1 === page
  })
  return hit ? hit.block_id : ''
}


/** 下载入口只有一个名字（「下载译稿 ▾」），具体下哪份在里面选。 */
const downloadOptions = computed(() => {
  if (isNativeTask.value) return [{ key: 'mono', label: '下载原稿 PDF' }]
  return [
    { key: 'dual', label: '下载双语稿' },
    { key: 'mono', label: '下载纯中文稿' },
  ]
})

async function runDownload(item) {
  closeMenus()
  const task = currentTask.value
  if (!task) return
  try {
    const url = await urlWithTicket(
      `/api/tasks/${task.id}/files/${item.key}?download=1`,
      task.id,
      'files',
    )
    window.location.assign(url)
  } catch (err) {
    setNote(err.message || '下载失败，请重试')
  }
}

// ---- 任务动作（取消 / 重试 / 删除）----

async function cancelTask(task) {
  closeMenus()
  taskActionBusy.value = true
  try {
    const res = await authFetch(`/api/tasks/${task.id}/cancel`, { method: 'POST' })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(body.detail || `取消失败（HTTP ${res.status}）`)
    await loadTasks()
    if (currentTask.value && currentTask.value.id === task.id) await refreshWorkbench(task.id)
    showToast('已请求取消这篇的翻译')
  } catch (err) {
    taskActionError.value = err.message || '取消失败'
    setNote(`取消失败：${taskActionError.value}`)
  } finally {
    taskActionBusy.value = false
  }
}

async function retryTask(task) {
  closeMenus()
  taskActionBusy.value = true
  try {
    const res = await authFetch(`/api/tasks/${task.id}/retry`, { method: 'POST' })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(body.detail || `重试失败（HTTP ${res.status}）`)
    await loadTasks()
    if (currentTask.value && currentTask.value.id === task.id) await openTask(body)
    else showToast('已重新排队，进度在库页的任务条上')
  } catch (err) {
    taskActionError.value = err.message || '重试失败'
    setNote(`重试失败：${taskActionError.value}`)
  } finally {
    taskActionBusy.value = false
  }
}

async function deleteTask(task) {
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
      view.value = 'library'
    }
    await loadTasks()
    showToast(`已删除「${task.filename}」——结果文件一并清除，不能恢复`)
  } catch (err) {
    taskActionError.value = err.message || '删除失败'
    setNote(`删除失败：${taskActionError.value}`)
  } finally {
    taskActionBusy.value = false
    closePanel()
  }
}

function dismissBanner(task) {
  dismissedBannerId.value = task.id
  showToast('已收起完成提示', {
    label: '撤销',
    run: () => {
      dismissedBannerId.value = null
    },
  })
}

// ---- 弹层面板（文档信息 / 详情 / 问题反馈 / 删除确认 / 换档位重译）----

const panel = ref('')
const panelTask = ref(null)
const panelDetail = ref(null)
const panelLoading = ref(false)

const panelData = computed(() => panelDetail.value || panelTask.value)

async function openPanel(kind, task) {
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

function closePanel() {
  panel.value = ''
  panelTask.value = null
  panelDetail.value = null
  panelLoading.value = false
}

const panelFactRows = computed(() => {
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

const feedbackText = computed(() => {
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

async function copyFeedback() {
  try {
    if (navigator.clipboard) await navigator.clipboard.writeText(feedbackText.value)
    setNote('反馈信息已复制——把它发给管理员即可，里面带着任务号。')
  } catch {
    setNote('这个浏览器不让读剪贴板——手动选中复制即可')
  }
}

/** 「换档位重译…」：新建一个任务（原任务保留）。原稿不在结果产物里，所以要重选一次 PDF。 */
function pickTierForRetranslate(tier) {
  closePanel()
  selectedLang.value = 'en'
  pickFile(tier)
  setNote(`已选「${tierTextMap[tier]}」——在弹出的选择框里挑同一份 PDF 即可新建任务，原任务保留。`)
}

// ============================================================ 账号与会话

onMounted(async () => {
  syncNarrow()
  window.addEventListener('resize', syncNarrow)
  window.addEventListener('keydown', onGlobalKeydown)
  setUnauthorizedHandler(handleUnauthorized)
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
  stopProgress()
  if (activeTimer) clearInterval(activeTimer)
  if (noteTimer) clearTimeout(noteTimer)
  if (toastTimer) clearTimeout(toastTimer)
  if (flashTimer) clearTimeout(flashTimer)
  if (dropHintTimer) clearTimeout(dropHintTimer)
})

watch(view, () => {
  if (view.value === 'library') syncActiveDetail()
})

async function restoreSession() {
  authChecking.value = true
  try {
    if (getToken()) {
      authUser.value = await fetchMe()
      await loadTasks()
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
  await loadTasks()
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
  tasks.value = []
  showAdmin.value = false
  stopProgress()
}

function handleUnauthorized() {
  authUser.value = null
  showAdmin.value = false
  stopProgress()
  authNotice.value = '登录已过期，请重新登录'
}

// ============================================================ 理解层加载

function understandReset() {
  understandingLoading.value = false
  understandingStatus.value = 'pending'
  understandingGuide.value = null
  understandingTerms.value = []
  understandingError.value = ''
  understandingTried.value = false
}

async function loadUnderstanding(taskId, { generate = false } = {}) {
  if (!taskId) return
  understandingLoading.value = true
  try {
    let res = await authFetch(`/api/tasks/${taskId}/understanding`)
    if (!res.ok) throw new Error(`加载失败（HTTP ${res.status}）`)
    let data = await res.json()
    if (generate && data.status !== 'ready') {
      understandingTried.value = true
      const post = await authFetch(`/api/tasks/${taskId}/understanding`, { method: 'POST' })
      if (post.ok) data = await post.json()
    }
    understandingStatus.value = data.status || 'pending'
    understandingGuide.value = data.guide || null
    understandingTerms.value = data.terms || []
    understandingError.value = data.error || ''
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

/** 切副页签：手机端从 peek 档点页签要顺手展开（否则点了像没反应）。 */
function switchTab(key) {
  assistTab.value = key
  honestNote.value = ''
  if (isNarrow.value && sheetState.value === 'peek') sheetState.value = 'half'
  if (key !== 'guide' && key !== 'terms') return
  if (!currentTask.value || !understandable.value) return
  if (understandingLoading.value || understandingStatus.value === 'ready') return
  if (understandingTried.value) return
  loadUnderstanding(currentTask.value.id, { generate: true })
}

async function loadBlocks(taskId) {
  try {
    const res = await authFetch(`/api/tasks/${taskId}`)
    if (!res.ok) return
    const data = await res.json()
    blocks.value = data.blocks || []
  } catch {
    /* 拿不到块就没法做术语定位，界面自己会直说 */
  }
}

// 顶部「⋯」菜单 6 项：文档信息 / 重试翻译（本档）/ 换档位重译… / 详情 / 问题反馈… / 删除…
// 规矩：永远单层级、不超过 7 项、任意两项的动作名不许共享动词。
const canRetryCurrent = computed(() => RETRYABLE_STATES.includes(currentTask.value?.status))

function retryCurrent() {
  if (currentTask.value) retryTask(currentTask.value)
}
function openDeletePanel() {
  openPanel('delete', currentTask.value)
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
            <button v-if="libraryEmpty" class="btn ghost sm" @click="loadTasks">我的论文</button>
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

          <div class="lib-wrap">
            <!-- 空库态才出大 hero；三枚标签是**可点的描边按钮**（点了进对应副页签） -->
            <div v-if="libraryEmpty" class="hero">
              <h1>把文献读懂</h1>
              <p class="tagline">翻译只是起点，理解才是价值</p>
              <p>
                上传文献 PDF，得到双语对照稿、结构化导读与统一术语表；
                还能就文献提问，每条答案都标明来自哪一段原文。
              </p>
              <div class="pills">
                <button class="pill" @click="openExample('guide')">看示例论文的结构化导读</button>
                <button class="pill" @click="openExample('terms')">看示例论文的术语表</button>
                <button class="pill" @click="openExample('ask')">看示例论文的带出处问答</button>
              </div>
            </div>

            <div v-else class="title-row">
              <h2>我的论文（{{ tasks.length }} 篇）</h2>
              <span class="spacer" />
              <button class="btn primary" @click="showUpload = !showUpload">
                {{ showUpload ? '收起上传' : '＋ 上传 PDF' }}
              </button>
            </div>

            <!-- 上传卡：空库时就在 hero 下面；有历史时由「＋ 上传 PDF」按需展开 -->
            <div v-if="libraryEmpty || showUpload" class="card upload-card">
              <div class="drop" :class="{ 'drop-over': uploading || dropHinting }" @click="pickFile()" @dragover.prevent @drop.prevent="onDrop">
                <div class="big">点击或拖拽 PDF 到此处</div>
                <div class="tiny">
                  {{
                    selectedLang === 'zh'
                      ? '上传后自动抽取文字并生成导读；完成后可读原文、导读与术语表'
                      : '上传后自动开始翻译；完成后可读双语稿、导读与术语表'
                  }}
                </div>
                <div class="drop-hint">支持电子版 PDF 与扫描件（扫描件走本地 OCR，文字可能有错字）；耗时取决于页数与档位</div>
                <div v-if="uploading" class="drop-hint">正在上传…</div>
                <div v-if="uploadError" class="drop-hint" style="color: var(--danger)">{{ uploadError }}</div>
              </div>

              <div>
                <div class="tier-label">文献语言</div>
                <div class="seg">
                  <span
                    v-for="lang in langOptions"
                    :key="lang.value"
                    :class="{ on: selectedLang === lang.value }"
                    @click="selectedLang = lang.value"
                  >
                    {{ lang.label }}
                  </span>
                </div>

                <template v-if="selectedLang !== 'zh'">
                  <div class="tier-label" style="margin-top: 16px">翻译档位</div>
                  <div class="seg">
                    <span
                      v-for="tier in tierOptions"
                      :key="tier.value"
                      :class="{ on: selectedTier === tier.value }"
                      @click="selectedTier = tier.value"
                    >
                      {{ tier.label }}
                    </span>
                  </div>
                  <div class="tier-note">
                    档位影响速度与质量，请在上传前选择<br />
                    快：最快，先看个大概<br />
                    中：版式更稳，适合正式阅读<br />
                    精档（多一道审校的那一档）还没做，做出来再放出来<br />
                    耗时取决于页数与档位（不承诺秒数）
                  </div>
                </template>
                <div v-else class="tier-note">
                  中文文献不翻译：直接抽文字层进理解层（导读 / 术语 / 带出处的问答）。<br />
                  耗时取决于页数（不承诺秒数）
                </div>
              </div>
            </div>

            <template v-if="!libraryEmpty">
              <!-- 进行中任务条：只留 3 段信息 + 队列数 -->
              <div v-for="bar in activeBars" :key="bar.task.id" class="card running">
                <!-- 文件名本身是进阅读工作区的入口（原型这里只有取消 / 详情，但"看翻译中的进度"
                     总得有个门；做成文件名可点，不新增控件、不动信息密度） -->
                <span class="name name-link" title="打开阅读工作区" @click="openTask(bar.task)">
                  {{ bar.task.filename }}
                </span>
                <div class="bar" :class="{ striped: bar.striped }"><i :style="{ width: bar.percent + '%' }" /></div>
                <span class="tiny muted">{{ bar.line }}</span>
                <span v-if="bar.queue" class="queue">{{ bar.queue }}</span>
                <button class="btn sm" :disabled="taskActionBusy" @click="cancelTask(bar.task)">取消</button>
                <button class="btn ghost sm" @click="openPanel('blocks', bar.task)">详情</button>
              </div>

              <!-- 翻译完成后任务条不静默消失：变绿给下一步动作，可手动关掉 -->
              <div v-if="completedBannerTask" class="card taskbar-ok">
                <span class="ok-text">翻译完成</span>
                <span class="tiny muted">{{ bannerMeta }}</span>
                <span class="spacer" />
                <button class="btn primary sm" @click="openTask(completedBannerTask)">开始阅读</button>
                <button class="btn ghost sm" @click="dismissBanner(completedBannerTask)">关闭</button>
              </div>

              <div v-if="historyError" class="card" style="margin-bottom: 14px; color: var(--danger)">
                历史任务加载失败：{{ historyError }}
                <button class="btn sm" style="margin-left: 10px" @click="loadTasks">重试</button>
              </div>

              <div v-else-if="!taskCards.length" class="card muted">
                还没有可读的论文——上面点「＋ 上传 PDF」传一篇，译文出来后会出现在这里。
              </div>

              <div v-else class="grid3">
                <div v-for="card in taskCards" :key="card.task.id" class="card paper-card">
                  <div class="row">
                    <span class="fname">{{ card.task.filename }}</span>
                    <span class="chip" :class="card.chip">{{ statusTextMap[card.task.status] || card.task.status }}</span>
                    <span v-if="card.task.native" class="chip">中文文献</span>
                  </div>
                  <div class="meta">{{ card.meta }}</div>
                  <div v-if="card.task.last_read_page" class="lastpos">
                    上次读到第 {{ card.task.last_read_page }} 页
                  </div>
                  <div class="actions">
                    <button
                      v-if="card.retryable"
                      class="btn primary sm"
                      :disabled="taskActionBusy"
                      @click="retryTask(card.task)"
                    >
                      {{ card.primary }}
                    </button>
                    <button v-else class="btn primary sm" @click="openTask(card.task)">
                      {{ card.primary }}
                    </button>
                    <button class="btn ghost sm" @click="openPanel('blocks', card.task)">详情</button>
                    <template v-if="deleteConfirmId === card.task.id">
                      <button class="btn danger sm" :disabled="taskActionBusy" @click="deleteTask(card.task)">
                        确认删除
                      </button>
                      <button class="btn ghost sm" @click="deleteConfirmId = null">再想想</button>
                    </template>
                    <button v-else class="btn ghost sm" @click="deleteConfirmId = card.task.id">删除</button>
                  </div>
                </div>
              </div>

              <div class="footline">
                <span v-if="taskActionError" style="color: var(--danger)">{{ taskActionError }}</span>
                <span class="spacer" />
                <span>docwise · 学术文献理解智能体</span>
              </div>
            </template>
          </div>
        </section>

        <!-- ==================== L2 阅读工作区 ==================== -->
        <section v-else-if="currentTask" class="screen-reader">
          <!-- 桌面工具条：< 1024px 整条不渲染（手机端的顶栏是 .ptop，原型就是这么分开的）；
               手机要用的下载 / ⋯ 跟着搬到 .ptop 上，功能一个不少 -->
          <div v-if="!isNarrow" class="reader-top">
            <button class="btn ghost sm" @click="backToLibrary">← 我的论文</button>
            <span class="fname">{{ currentTask.filename }}</span>
            <!-- 档位只读；想换档请在 ⋯ 里以其他档位重新翻译（会新建任务） -->
            <span class="chip" title="上传时选定；想换档请在 ⋯ 里以其他档位重新翻译（会新建任务）">
              {{ currentTask.native ? '中文文献 · 不翻译' : tierTextMap[currentTask.tier] || currentTask.tier }}
            </span>
            <div class="menu-wrap">
              <span class="chip" role="button" tabindex="0" @click.stop="toggleMenu('mode')">
                {{ docModeLabel }} ▾
              </span>
              <div class="menu" :class="{ open: openMenu === 'mode' }">
                <button v-for="item in docModeOptions" :key="item.value" @click="setDocMode(item.value)">
                  {{ item.label }}
                </button>
              </div>
            </div>
            <span class="spacer" />
            <button class="btn ghost sm" @click="toggleSearch">🔍 搜索</button>
            <span v-if="pageChipText" class="chip">{{ pageChipText }}</span>
            <!-- 下载入口只有一个，命名统一为「下载译稿」，两项在里面选 -->
            <div class="menu-wrap">
              <button class="btn ghost sm" @click.stop="toggleMenu('dl')">⤓ 下载译稿 ▾</button>
              <div class="menu" :class="{ open: openMenu === 'dl' }">
                <button v-for="item in downloadOptions" :key="item.key" @click="runDownload(item)">
                  {{ item.label }}
                </button>
              </div>
            </div>
            <!-- 单层级、6 项、任意两项不共享动词 -->
            <div class="menu-wrap">
              <button class="btn ghost sm" @click.stop="toggleMenu('more')">⋯</button>
              <div class="menu" :class="{ open: openMenu === 'more' }">
                <button @click="openPanel('info', currentTask)">文档信息</button>
                <button :disabled="!canRetryCurrent" @click="retryCurrent">重试翻译（本档）</button>
                <button @click="openPanel('retier', currentTask)">换档位重译…</button>
                <button @click="openPanel('blocks', currentTask)">详情</button>
                <button @click="openPanel('feedback', currentTask)">问题反馈…</button>
                <div class="sep" />
                <button class="danger" @click="openDeletePanel">删除…</button>
              </div>
            </div>
          </div>

          <!-- 极细进度条：永远在；不确定时画流动条纹（桌面；手机端用它自己的 .progress-line） -->
          <div v-if="!isNarrow" class="thin-bar" :class="{ striped: thinBar.striped }">
            <i :style="{ width: thinBar.width }" />
          </div>

          <!-- 空的时候必须真的是空的：原型靠 .note-line:not(:empty) 决定要不要那条分隔线 -->
          <div v-if="!isNarrow" class="note-line">
            <div v-if="searchOpen" class="search-row">
              <input
                v-model="searchTerm"
                class="search-input"
                placeholder="在这篇文献的正文里找…"
                @keydown.enter="runSearch"
              />
              <button class="btn sm" @click="runSearch">查找</button>
              <button class="btn ghost sm" @click="toggleSearch">关闭</button>
            </div>
            <template v-else-if="noteLineText">{{ noteLineText }}</template>
          </div>

          <div class="reader-body">
            <!-- 左栏 · 段落精读（自己的 DOM，出处锚点才成立） -->
            <div
              v-if="!isNarrow && docMode === 'paragraph'"
              ref="docPaneEl"
              class="doc-pane"
              @scroll="onPaneScroll"
            >
              <div v-if="scannedNotice" class="card doc-note">
                这份文献是扫描件：文字由本地 OCR 识别，可能有个别错字；出处与引用都按识别结果给出。
              </div>
              <div v-if="noBlockTranslationNotice" class="card doc-note">
                这篇文献暂无「块级」译文（译文在 PDF 产物里，段落视图拿不到），下面显示的是原文；
                问答与检索同样基于原文。
              </div>
              <div v-if="!docPages.length" class="card doc-note">{{ docEmptyText }}</div>
              <template v-else>
                <div
                  v-for="(page, pageIndex) in docPages"
                  :key="page.key"
                  :ref="(el) => setPageEl(page.page, el)"
                  class="page"
                  :data-page-key="page.key"
                  @mouseup="onDocMouseUp($event, $event.currentTarget)"
                >
                  <h3>{{ pageIndex === 0 ? docTitle : page.label }}</h3>
                  <div v-if="pageIndex === 0" class="authors">{{ docMetaLine }}</div>
                  <div class="cols">
                    <p
                      v-for="row in page.rows"
                      :key="row.block.block_id"
                      :id="row.block.block_id"
                      :ref="(el) => setBlockEl(row.block.block_id, el)"
                      :data-block-id="row.block.block_id"
                      :title="'原文块 ' + row.block.block_id"
                      :class="{
                        anchor: flashId === row.block.block_id,
                        flash: flashId === row.block.block_id,
                        sel: pickedBlockId === row.block.block_id,
                        ['pg-' + (row.block.type || 'body')]: true,
                      }"
                      @click="onBlockClick(row, $event)"
                    >
                      <span v-if="hasBlockTranslations" class="en">{{ row.source }}</span>
                      {{ row.main }}
                    </p>
                  </div>
                  <button
                    v-if="selChip && selChip.pageKey === page.key"
                    class="selchip"
                    :style="{ left: selChip.left + 'px', top: selChip.top + 'px' }"
                    @mousedown.prevent
                    @mouseup.stop
                    @click="askSelectedSentence"
                  >
                    就这句提问
                  </button>
                </div>
              </template>
            </div>

            <!-- 左栏 · 原版 / 纯中文 / 双语 PDF：pdf.js 渲染（有文字层，所以能定位、能点段落提问） -->
            <div v-else-if="!isNarrow" class="doc-pane pdf-mode">
              <PdfPane
                :task-id="currentTask.id"
                :variant="docMode"
                :doc-page-count="docPageCount"
                :start-page="pdfStartPage"
                :locate-text="locateText"
                :locate-key="locateKey"
                :fallback-page="pdfFallbackPage"
                :has-dual="fileAvailability.dual"
                @locate="onPdfLocate"
                @ask="onPdfAsk"
                @page-change="(n) => (currentPage = n)"
              />
            </div>

            <!-- 手机 · 顶栏是 .ptop（原型手机屏就是这么一根），不是桌面那条 reader-top -->
            <div v-else class="mobile-reader">
              <div class="ptop">
                <button class="btn ghost sm ptop-icon" @click="backToLibrary">←</button>
                <span class="spacer" />
                <span class="fname">{{ currentTask.filename }}</span>
                <span class="spacer" />
                <button class="btn ghost sm ptop-icon" :title="mobileOriginalTitle" @click="toggleMobileOriginal">
                  {{ docMode === 'paragraph' ? pdfQuickLabel : '段落' }}
                </button>
                <!-- 下载入口只有一个名字（「下载译稿 ▾」），手机上不例外 -->
                <div class="menu-wrap">
                  <button class="btn ghost sm ptop-icon" title="下载译稿" @click.stop="toggleMenu('dl')">⤓</button>
                  <div class="menu" :class="{ open: openMenu === 'dl' }">
                    <button v-for="item in downloadOptions" :key="item.key" @click="runDownload(item)">
                      {{ item.label }}
                    </button>
                  </div>
                </div>
                <div class="menu-wrap">
                  <button class="btn ghost sm ptop-icon" title="更多" @click.stop="toggleMenu('more')">⋯</button>
                  <div class="menu" :class="{ open: openMenu === 'more' }">
                    <button @click="openPanel('info', currentTask)">文档信息</button>
                    <button :disabled="!canRetryCurrent" @click="retryCurrent">重试翻译（本档）</button>
                    <button @click="openPanel('retier', currentTask)">换档位重译…</button>
                    <button @click="openPanel('blocks', currentTask)">详情</button>
                    <button @click="openPanel('feedback', currentTask)">问题反馈…</button>
                    <div class="sep" />
                    <button class="danger" @click="openDeletePanel">删除…</button>
                  </div>
                </div>
              </div>
              <div class="progress-line">
                <span>{{ pageChipText || stageText }}</span>
                <div class="pl-bar" :class="{ striped: thinBar.striped }"><i :style="{ width: thinBar.width }" /></div>
                <span>{{ statusTextMap[currentTask.status] }}</span>
              </div>
              <!-- 菜单说明这类一次性提示，手机上没有 note-line 可挂，就挂在进度行下面（有内容才占位） -->
              <div v-if="noteLineText" class="note-line">{{ noteLineText }}</div>
              <div class="reader-ctrls">
                <span>
                  字号
                  <button class="rc-btn" @click="stepFont(-1)">A-</button>
                  <button class="rc-btn" @click="stepFont(1)">A+</button>
                </span>
                <span class="spacer" />
                <span v-if="isNativeTask" class="on">原文中文</span>
                <div v-else class="menu-wrap">
                  <button class="rc-btn on" @click.stop="toggleMenu('dual')">{{ mobileLangLabel }} ▾</button>
                  <div class="menu" :class="{ open: openMenu === 'dual' }">
                    <button
                      v-for="item in docModeOptions"
                      :key="item.value"
                      :disabled="item.value === docMode"
                      @click="setDocMode(item.value)"
                    >
                      {{ item.label }}
                    </button>
                  </div>
                </div>
              </div>
              <div v-if="docMode === 'paragraph'" class="pdoc" :style="pdocStyle">
                <div v-if="scannedNotice" class="honest pdoc-note">
                  这份文献是扫描件：文字由本地 OCR 识别，可能有个别错字。
                </div>
                <div v-if="noBlockTranslationNotice" class="honest pdoc-note">
                  这篇文献暂无「块级」译文（译文在 PDF 产物里）——下面显示的是原文。
                </div>
                <div v-if="!paragraphRows.length" class="card doc-note">{{ docEmptyText }}</div>
                <template
                  v-for="row in pdocRows"
                  :key="row.kind === 'page' ? 'sep-' + row.page : row.block.block_id"
                >
                  <div v-if="row.kind === 'page'" class="pg-sep">{{ row.label }}</div>
                  <template v-else>
                    <div
                      :id="'m_' + row.block.block_id"
                      :ref="(el) => setBlockEl(row.block.block_id, el)"
                      :data-block-id="row.block.block_id"
                      class="pg"
                      :class="[
                        'pg-' + (row.block.type || 'body'),
                        { flash: flashId === row.block.block_id },
                      ]"
                    >
                      <!-- 触发热区收窄到「段 N」标签本身（不与系统选词 / 滚动抢手势） -->
                      <span
                        class="seg-no"
                        :class="{ 'seg-btn': row.index !== null }"
                        :title="row.index !== null ? '点段号提问' : ''"
                        @click="togglePgChip(row)"
                      >
                        {{ row.index !== null ? row.label : '—' }}
                      </span>
                      <div>
                        <div v-if="hasBlockTranslations" class="en">{{ row.source }}</div>
                        <div class="zh">{{ row.main }}</div>
                      </div>
                    </div>
                    <button v-if="pgChipFor === row.block.block_id" class="pg-chip" @click="askParagraph(row)">
                      就这段提问
                    </button>
                  </template>
                </template>
              </div>
              <!-- 手机上的「原版」：同一套 pdf.js 视图，换的是容器 -->
              <div v-else class="pdoc-pdf">
                <PdfPane
                  :task-id="currentTask.id"
                  :variant="docMode"
                  :doc-page-count="docPageCount"
                  :start-page="pdfStartPage"
                  :locate-text="locateText"
                  :locate-key="locateKey"
                  :fallback-page="pdfFallbackPage"
                :has-dual="fileAvailability.dual"
                  @locate="onPdfLocate"
                  @ask="onPdfAsk"
                  @page-change="(n) => (currentPage = n)"
                />
              </div>
            </div>

            <!-- 助手区：桌面 = 右栏；手机 = 底部抽屉三档。**同一份 DOM**，只有容器类名不同 -->
            <div :class="assistClass">
              <template v-if="isNarrow">
                <div class="grip" @click="cycleSheet">
                  <i /><span>{{ sheetGripText }}</span>
                </div>
                <div class="peek-summary">{{ peekSummary }}</div>
                <div v-if="locatedHint" class="peek-line">
                  {{ locatedHint }} · 正文已滚到该段 ·
                  <button class="sample-link" @click="sheetState = 'half'">点我回来</button>
                </div>
              </template>

              <div class="tabs">
                <button
                  v-for="tab in assistTabs"
                  :key="tab.key"
                  :class="{ on: assistTab === tab.key }"
                  @click="switchTab(tab.key)"
                >
                  {{ tab.label }}
                </button>
              </div>

              <div :class="assistBodyClass" :ref="setAssistBody">
                <div v-if="honestNote" class="honest">{{ honestNote }}</div>

                <!-- ============ 问答 ============ -->
                <div class="tabpane" :class="{ on: assistTab === 'ask' }">
                  <div class="chips">
                    <button
                      v-for="chip in quickChips"
                      :key="chip.label"
                      :disabled="askLoading"
                      @click="askPreset(chip.q)"
                    >
                      {{ chip.label }}
                    </button>
                  </div>
                  <div class="chips-hint">{{ askChipsHint }}</div>

                  <div v-for="turn in askTurns" :key="turn.id" class="turn">
                    <div class="bubble-q">{{ turn.question }}</div>
                    <div v-if="turn.loading" class="bubble-a muted">正在读原文并作答…</div>
                    <div v-else-if="turn.error" class="fail-card">
                      {{ turn.error }}
                      <div v-if="turn.errorDetail" class="q-kept">{{ turn.errorDetail }}</div>
                      <div class="q-kept">你的问题已保留：「{{ turn.question }}」</div>
                      <button class="btn primary sm" style="margin-top: 8px" @click="retryTurn(turn)">重试</button>
                    </div>
                    <template v-else>
                      <div class="bubble-a">
                        {{ turn.answer }}
                        <div class="srcs">
                          <span class="lbl">出处：</span>
                          <template v-if="turn.sources.length">
                            <button
                              v-for="src in turn.sources"
                              :key="src.id"
                              class="src-tag"
                              :class="{ unknown: !src.found }"
                              :title="'原文块 ' + src.ids.join(' + ')"
                              @click="traceTo(src.id, { text: src.text })"
                            >
                              {{ src.label || '出处未能定位' }} ▸
                            </button>
                          </template>
                          <span v-else class="lbl">（回答未给出处）</span>
                        </div>
                      </div>
                      <div class="a-tools">
                        <span v-if="turn.mode === 'fts'" class="muted">长文 · 检索模式</span>
                        <button @click="copyAnswer(turn)">{{ turn.copied ? '已复制' : '复制答案' }}</button>
                        <button v-if="turn.sources.length" @click="traceTo(turn.sources[0].id, { text: turn.sources[0].text })">展开原文</button>
                      </div>
                    </template>
                  </div>

                  <div v-if="!askTurns.length" class="chips-hint">
                    问点什么吧——答案会标出处，点出处能跳回原文那一段并高亮一次。
                  </div>
                </div>

                <!-- ============ 导读 ============ -->
                <div class="tabpane" :class="{ on: assistTab === 'guide' }">
                  <div v-if="understandingLoading" class="chips-hint">{{ guideEmptyText }}</div>
                  <div v-else-if="understandingStatus === 'failed'" class="fail-card">
                    {{ understandingError || '导读生成失败' }}
                    <button class="btn primary sm" style="margin-top: 8px" @click="retryUnderstanding">重试</button>
                  </div>
                  <div v-else-if="!guidePoints.length" class="chips-hint">{{ guideEmptyText }}</div>
                  <template v-else>
                    <div v-for="point in guidePoints" :key="point.key" class="guide-card">
                      <div class="k">{{ point.label }}</div>
                      <div class="v">{{ point.text }}</div>
                      <div class="ops">
                        <template v-if="point.sources.length">
                          <button
                            v-for="src in point.sources"
                            :key="src.id"
                            :title="'原文块 ' + src.ids.join(' + ')"
                            @click="traceTo(src.id, { text: src.text })"
                          >
                            看原文（{{ src.label || '位置待定' }}）▸
                          </button>
                        </template>
                        <!-- 没有单一段落出处 → 降级态置灰、不可点、不给箭头 -->
                        <button v-else class="dead" disabled>无单一段落出处</button>
                        <button @click="probePoint(point)">就这条追问</button>
                      </div>
                      <div v-if="!point.sources.length" class="dead-note">
                        该要点由全文综合而成，没有哪一段能单独代表它——所以这里不给「看原文」。
                      </div>
                    </div>
                  </template>
                </div>

                <!-- ============ 术语 ============ -->
                <div class="tabpane" :class="{ on: assistTab === 'terms' }">
                  <div v-if="understandingLoading" class="chips-hint">{{ termsEmptyText }}</div>
                  <div v-else-if="understandingStatus === 'failed'" class="fail-card">
                    {{ understandingError || '术语表生成失败' }}
                    <button class="btn primary sm" style="margin-top: 8px" @click="retryUnderstanding">重试</button>
                  </div>
                  <div v-else-if="!termItems.length" class="chips-hint">{{ termsEmptyText }}</div>
                  <template v-else>
                    <div class="termlist">
                      <div v-for="item in termItems" :key="item.key" class="term">
                        <b>{{ item.term }}</b><span class="cn">{{ item.cn }}</span>
                        <div class="def">{{ item.definition }}</div>
                        <div class="ops">
                          <button @click="locateTerm(item)">{{ item.locate }}</button>
                        </div>
                      </div>
                    </div>
                    <div class="chips-hint">
                      术语表当前没有出处字段：按钮只在「命中之后」才回填坐标，未命中会直说「没找到」——不预填假坐标。
                    </div>
                  </template>
                </div>
              </div>

              <!-- 问答输入框吸底 -->
              <div class="composer">
                <textarea
                  v-model="askQuestion"
                  rows="1"
                  :placeholder="composerPlaceholder"
                  :disabled="askLoading"
                  @keydown.enter.exact.prevent="submitAsk"
                />
                <button class="btn primary" :disabled="askLoading || !askQuestion.trim()" @click="submitAsk">
                  ↑
                </button>
              </div>
            </div>
          </div>
        </section>
      </template>

      <!-- 隐藏的文件选择器（上传 / 换档位重译都用它） -->
      <input ref="fileInput" type="file" accept="application/pdf" class="hidden-file" @change="onFilePicked" />

      <!-- ============ 弹层：文档信息 / 详情 / 问题反馈 / 删除确认 / 换档位重译 ============ -->
      <div v-if="panel" class="confirm-mask" @click.self="closePanel">
        <div class="card confirm-card" :class="{ wide: panel === 'blocks' }">
          <template v-if="panel === 'delete'">
            <h3>删除这篇论文？</h3>
            <p>
              「{{ panelTask && panelTask.filename }}」的结果文件与磁盘产物会一起清掉，不能恢复。
              只是想重来一遍的话，选「重试翻译（本档）」更稳。
            </p>
            <div class="confirm-ops">
              <button class="btn ghost" @click="closePanel">再想想</button>
              <button class="btn danger" :disabled="taskActionBusy" @click="deleteTask(panelTask)">确认删除</button>
            </div>
          </template>

          <template v-else-if="panel === 'retier'">
            <h3>换档位重译</h3>
            <p>
              会新建一个任务（原任务保留）。原稿不在结果产物里，所以需要你重新选一次这份 PDF。
            </p>
            <div class="confirm-list">
              <button
                v-for="tier in tierOptions"
                :key="tier.value"
                class="btn"
                @click="pickTierForRetranslate(tier.value)"
              >
                以「{{ tier.label }}」重译 —— {{ tier.note }}
              </button>
            </div>
            <div class="confirm-ops">
              <button class="btn ghost" @click="closePanel">取消</button>
            </div>
          </template>

          <template v-else-if="panel === 'feedback'">
            <h3>问题反馈</h3>
            <p>把下面这段复制给管理员即可——里面带着任务号，排查时能直接定位到这篇。</p>
            <div class="feedback-pre">{{ feedbackText }}</div>
            <div class="confirm-ops">
              <button class="btn ghost" @click="closePanel">关闭</button>
              <button class="btn primary" @click="copyFeedback">复制反馈信息</button>
            </div>
          </template>

          <template v-else-if="panel === 'info'">
            <h3>文档信息</h3>
            <div v-if="panelLoading" class="muted">正在读取…</div>
            <div v-else class="detail-meta">
              <div v-for="row in panelFactRows" :key="row.k"><b>{{ row.k }}</b>：{{ row.v }}</div>
            </div>
            <div class="confirm-ops">
              <button class="btn ghost" @click="closePanel">关闭</button>
            </div>
          </template>

          <template v-else>
            <h3>详情</h3>
            <div v-if="panelLoading" class="muted">正在读取…</div>
            <div v-else-if="taskDetailError" style="color: var(--danger)">{{ taskDetailError }}</div>
            <template v-else>
              <div class="detail-meta">
                <div v-for="row in panelFactRows" :key="row.k"><b>{{ row.k }}</b>：{{ row.v }}</div>
              </div>
              <div class="block-section-title">
                <b>分块处理状态</b>
                <span class="block-count muted">
                  共 {{ panelData && panelData.blocks ? panelData.blocks.length : 0 }} 块（排查用；阅读请点「继续读」）
                </span>
              </div>
              <div
                v-if="!panelData || !panelData.blocks || !panelData.blocks.length"
                class="muted"
                style="padding: 24px 0; text-align: center"
              >
                该任务暂无分块结果（任务尚未处理完成）
              </div>
              <div v-else class="block-list">
                <div v-for="block in panelData.blocks" :key="block.block_id" class="block-card">
                  <div class="block-card-head">
                    <span class="muted">{{ block.block_id }}</span>
                    <span
                      class="chip"
                      :class="block.status === 'success' ? 'ok' : block.status === 'failed' ? 'fail' : 'warn'"
                    >
                      {{ block.status }}
                    </span>
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
                  <div v-if="block.error" class="block-error" style="color: var(--danger)">{{ block.error }}</div>
                </div>
              </div>
            </template>
            <div class="confirm-ops">
              <button class="btn ghost" @click="closePanel">关闭</button>
            </div>
          </template>
        </div>
      </div>

      <!-- toast：阅读位置提示 / 可撤销的动作 -->
      <div class="toast" :class="{ show: toast.show }">
        <span>{{ toast.text }}</span>
        <button v-if="toast.undoLabel" @click="runToastUndo">{{ toast.undoLabel }}</button>
      </div>
    </div>
  </n-config-provider>
</template>
