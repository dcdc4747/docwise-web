/**
 * 阅读工作区（L2）：当前这篇的块、渲染方式、出处跳转、理解层、进度推送、阅读位置与搜索。
 *
 * **为什么单独一个模块**：它是 `App.vue` 里最大的一块——「L2 阅读工作区」+「理解层（导读 / 术语）」
 * +「术语定位」+「阅读位置记忆」+「搜索」+「数据加载（读这一篇那半边）」+「预览 / 下载」全在里面。
 * 出处那条主线 `traceTo` 被目录跳转、术语定位、搜索、问答四处复用
 * （`codegraph impact traceTo` 实测：5 个受影响符号当时全在 `App.vue` 一个文件里），
 * 挤在一个文件里时谁动一下都碰着别人。分开之后各改各的。
 *
 * ⚠️ **状态定义在模块顶层（单例），不在函数里面**：定义在函数里的话，每次调用都会新建一份
 * 「正在读哪一篇」，两个组件看到的就不一样了（表现为"A 页面改了、B 页面看不见"）。
 *
 * ⚠️ **它不 import `stores/useLibrary`**：库页点卡片要调这边的「打开」，
 * 这边刷新列表又要调那边的 `loadTasksAndSync` —— 两边互相 import 就绕成环了。
 * 所以**三样能力由 App.vue 注入**（`initReader`，与 `useAsk` 的 `initAsk` 同一个路子）：
 * 当前屏 `view`、写地址 `navigateToHash`、刷新列表 `loadTasksAndSync`。
 */

import { computed, nextTick, ref } from 'vue'

import { authFetch, urlWithTicket } from '../auth'
import {
  buildParagraphRows,
  findBlockByText,
  mergeSourceRuns,
  parseBlockId,
  sourceLabel,
} from '../blockLabel'
import { enginePageText, queueText, relativeTime, runningLine, stageTextFor } from '../progressText'
import { askAnchor, askQuestion, resetAsk, submitAsk } from './useAsk'
import { ACTIVE_STATES, TERMINAL_STATES, tierTextMap } from './useTasks'
import {
  assistTab,
  closeMenus,
  isNarrow,
  locatedHint,
  menuNote,
  pgChipFor,
  setNote,
  sheetState,
  showToast,
} from './useUi'

// ============================================================ 外壳注入（App.vue 调一次）

/**
 * 当前屏（L1 库页 / L2 阅读工作区）。**真源在 App.vue**——它是路由分发的唯一入口，
 * 这里只是拿同一个 ref 来写（同一份状态，不是副本）。
 */
let view = { value: 'library' }
/** 把地址写进 hash（`expectedHash` 防来回触发那套接线在外壳里）。 */
let navigateToHash = () => {}
/** 拉列表 + 对"进行中那条"补详情——那是库页的动作，由 App.vue 从 useLibrary 注入。 */
let loadTasksAndSync = async () => {}

/**
 * 注入外壳能力。**在 App.vue 里调一次即可**（重复调只是换个引用，不影响已有状态）。
 *
 * @param {{view: import('vue').Ref, navigateToHash: Function, loadTasksAndSync: Function}} deps
 */
export function initReader({
  view: shellView,
  navigateToHash: shellNavigateToHash,
  loadTasksAndSync: shellLoadTasksAndSync,
}) {
  view = shellView
  navigateToHash = shellNavigateToHash
  loadTasksAndSync = shellLoadTasksAndSync
}

// ============================================================ L2 阅读工作区

export const currentTask = ref(null)
/** 左栏三选一：段落精读（自己的 DOM，锚点才成立）/ 纯中文 PDF / 双语 PDF。 */
export const docMode = ref('paragraph')
// `assistTab`（右助手当前副页签）已搬进 stores/useUi —— 它属于"界面零碎事"，
// 而且问答那边（点「就这条追问」、手机点段号）也要切页签，放那边两边都能用。
export const assistTabs = [
  { key: 'ask', label: '问答' },
  { key: 'guide', label: '导读' },
  { key: 'terms', label: '术语' },
]

export const blocks = ref([])

/** 从段落精读切到 PDF 时要落在第几页（1 起；0/1 = 从头）。 */
export const pdfStartPage = ref(0)
/** 段落精读里"当前读到第几页"（滚动时更新）——切到 PDF 模式要接着读，不能每次都回第 1 页。 */
export const currentPage = ref(1)
export const fileAvailability = ref({ mono: false, dual: false })
export const taskDetailError = ref('')
export const taskDetailLoading = ref(false)

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
export function labelOf(blockId, text) {
  return sourceLabel(blockId, blocks.value, text ? { text } : {})
}

export const isNativeTask = computed(() => currentTask.value?.native === true)
export const isRunning = computed(() => currentTask.value?.status === 'in_progress')

// ---- 诚实进度（引擎自报，读不到就直说"还没报"）----
export const engineProgress = ref(null)
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

export const stageText = computed(() => stageTextFor(currentTask.value, engineProgress.value))
export const progressPercent = computed(() => {
  const task = currentTask.value
  if (!task) return 0
  if (task.status === 'in_progress' && engineProgress.value) {
    return Math.round((engineProgress.value.percent ?? 0) * 100)
  }
  return Math.round((task.progress ?? 0) * 100)
})

/** 细进度条永远在：知道多少画多少，不知道就画流动条纹（绝不编一个百分比）。 */
export const thinBar = computed(() => {
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
export const docPageCount = computed(() => {
  const pages = new Set()
  blocks.value.forEach((block) => {
    const parsed = parseBlockId(block.block_id)
    if (parsed) pages.add(parsed.page)
  })
  return pages.size
})

export const pageChipText = computed(() => {
  const task = currentTask.value
  if (!task) return ''
  if (task.status === 'pending') return queueText(task)
  if (task.status === 'in_progress') return enginePageText(engineProgress.value)
  return docPageCount.value ? `共 ${docPageCount.value} 页` : ''
})

/** .note-line：优先显示刚点过的菜单项说明，其次显示进行中的诚实进度。 */
export const noteLineText = computed(() => {
  if (menuNote.value) return menuNote.value
  const task = currentTask.value
  if (task && (task.status === 'in_progress' || task.status === 'pending')) {
    return runningLine(task, engineProgress.value, elapsedSeconds.value)
  }
  return ''
})

// ---- 左栏：段落精读 / 原版 PDF ----

/** 这批块里到底有没有译文？实测全库 task_blocks.translated 一律为空（见项目记忆）。 */
export const hasBlockTranslations = computed(() =>
  blocks.value.some((block) => (block.translated || '').trim().length > 0),
)

/**
 * 段落精读的行：块 + 跨页分隔。段号按页内重算（buildParagraphRows 负责）。
 * 主文 = 译文；没有译文时回退原文——**但绝不把同一段英文显示两遍**。
 */
export const paragraphRows = computed(() =>
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
export const docPages = computed(() => {
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
export const pdocRows = computed(() => {
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

/**
 * 目录（章节导航）：把**服务端认出来的**标题（块分级：`title` / `heading`）变成可点的跳转。
 *
 * 三条刻意的口径：
 * 1. **只跳转，不判断**——哪块是标题由后端 `blocktypes.py` 决定，前端不自己再猜一遍
 *    （两处口径必然打架，见项目记忆）；
 * 2. 文字用 `main`（有译文就是中文）——目录是给读中文的人看的；没有译文的老任务
 *    会显示原文标题，也照实显示，不假装有中文；
 * 3. **少于 3 条就不显示这条**：只有一两个标题的文献摆个"目录"是噪音；
 *    一条都没有（老任务、扫描件）就整条不渲染——**不硬造**。
 */
export const outlineItems = computed(() =>
  paragraphRows.value
    .filter(
      (row) =>
        row.kind === 'block' &&
        (row.block.type === 'title' || row.block.type === 'heading'),
    )
    .map((row) => ({
      blockId: row.block.block_id,
      type: row.block.type,
      page: row.page,
      text: (row.main || row.block.text || '').replace(/\s+/g, ' ').trim().slice(0, 90),
    }))
    .filter((item) => item.text),
)
export const showOutline = computed(() => outlineItems.value.length >= 3)
export const outlineOpen = ref(false)

/** 点目录里的一条：收起目录 → 滚到那一段并高亮（复用出处那套 traceTo，口径只有一处）。 */
export async function goOutline(item) {
  outlineOpen.value = false
  await traceTo(item.blockId)
}

export const docTitle = computed(() => (currentTask.value?.filename || '').replace(/\.pdf$/i, ''))

export const docMetaLine = computed(() => {
  const task = currentTask.value
  if (!task) return ''
  const parts = []
  if (docPageCount.value) parts.push(`${docPageCount.value} 页`)
  parts.push(task.native ? '中文文献 · 不翻译' : tierTextMap[task.tier] || task.tier)
  const created = relativeTime(task.created_at)
  if (created) parts.push(`${created}上传`)
  return parts.filter(Boolean).join(' · ')
})

export const docModeOptions = computed(() => {
  const options = [{ value: 'paragraph', label: '段落精读' }]
  if (fileAvailability.value.mono) {
    options.push({ value: 'mono', label: isNativeTask.value ? '原文 PDF' : '纯中文 PDF' })
  }
  if (fileAvailability.value.dual && !isNativeTask.value) {
    options.push({ value: 'dual', label: '双语 PDF' })
  }
  return options
})

export const docModeLabel = computed(
  () => docModeOptions.value.find((item) => item.value === docMode.value)?.label || '段落精读',
)

export const docEmptyText = computed(() => {
  const task = currentTask.value
  if (!task) return ''
  if (task.status === 'pending') return '这篇还在排队，轮到它就开始翻译。'
  if (task.status === 'in_progress') return '正在翻译这篇文献，进度看上面那条细进度条。'
  if (task.status === 'failed') {
    return task.error_message ? `这次翻译没成功：${task.error_message}` : '这次翻译没成功。'
  }
  if (task.status === 'cancelled') {
    return '这次翻译已取消；要重来的话点右上角「…」→「重试翻译（本档）」。'
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
export { noBlockTranslationNotice }

/**
 * 扫描件的诚实提示（**必须有**）：这份文献没有文字层，文字是**本地 OCR 认出来的**，
 * 可能有个别错字，出处与引用也按识别结果给。不说这一句，用户会把 OCR 的错当成原文的错。
 */
export const scannedNotice = computed(() => currentTask.value?.text_source === 'ocr')

// ---- 出处跳转（点击必闪烁；定位不到就诚实说）----

const blockEls = new Map()
function setBlockEl(blockId, el) {
  if (el) blockEls.set(blockId, el)
  else blockEls.delete(blockId)
}
export { setBlockEl }

export const flashId = ref('')
export const honestNote = ref('')
let flashTimer = null

export const docPaneEl = ref(null)
// `assistBodyEl` / `setAssistBody` 已搬进 stores/useUi（助手容器的模板 ref 由那边持有，
// 点出处与提问后的"滚到底"也在那边）。这里只用 import 进来的那两个。

const pageEls = new Map()
function setPageEl(page, el) {
  if (el && page !== null) pageEls.set(page, el)
  else if (page !== null) pageEls.delete(page)
}
export { setPageEl }

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
export async function traceTo(blockId, { silent = false, text = '' } = {}) {
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

export const selChip = ref(null)
/** 段落精读里"点中的那一段"（选中态一直留着，点别处才灭）——和 PDF 那边的选中一个道理。 */
export const pickedBlockId = ref('')

/** 点某一段的正文：**这一段当场点亮**（.sel），并在它上方浮出「就这句提问」。
 *
 * 与划词的关系：选中了文字就按划词走（句子级锚点），没选中就是"点了这一段"。
 * 两条路都会把锚点块放进 `selChip.blockId`，所以提问时带的是同一个坐标系。
 */
export function onBlockClick(row, event) {
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

export function onDocMouseUp(event, pageEl) {
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
export function askSelectedSentence() {
  const chip = selChip.value
  if (!chip) return
  askAnchor.value = { blockId: chip.blockId, text: chip.text }
  selChip.value = null
  askQuestion.value = `就这句提问：${chip.text}`
  assistTab.value = 'ask'
  submitAsk()
}
// ============================================================ 理解层（导读 / 术语）

export const understandingLoading = ref(false)
export const understandingStatus = ref('pending')
export const understandingGuide = ref(null)
export const understandingTerms = ref([])
export const understandingError = ref('')
/** 每个任务只自动试一次（失败后交给「重试」按钮，不反复烧钱）。 */
export const understandingTried = ref(false)

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
export const guidePoints = computed(() => {
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

export const termItems = computed(() =>
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

export const guideEmptyText = computed(() => {
  if (!understandable.value) return '文献还没翻译完，导读要等译文出来才能生成。'
  return '正在生成导读（读全文 → 提炼要点），请稍候…'
})
export const termsEmptyText = computed(() => {
  if (!understandable.value) return '文献还没翻译完，术语表要等译文出来才能生成。'
  return '正在生成术语表（与导读一同产出），请稍候…'
})

// ============================================================ 术语定位（命中后回填）

const termLocate = ref({})

export async function locateTerm(item) {
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

export const pdfQuickLabel = computed(() => {
  const target = pdfQuickMode.value
  if (!target) return ''
  if (target.value === 'dual') return '双语稿'
  return isNativeTask.value ? '原稿' : '纯中文稿'
})

export const mobileOriginalTitle = computed(() =>
  docMode.value === 'paragraph' ? `看 ${pdfQuickLabel.value} 的 PDF` : '回到段落视图',
)

export function toggleMobileOriginal() {
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
export const mobileLangLabel = computed(() => {
  if (docMode.value !== 'paragraph') return docModeLabel.value
  return hasBlockTranslations.value ? '中英对照' : '原文'
})

// `syncNarrow` / `isNarrow` 已搬进 stores/useUi（窄屏判断是界面零碎事）

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
export function onPaneScroll(event) {
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

export const searchOpen = ref(false)
export const searchTerm = ref('')

export function toggleSearch() {
  searchOpen.value = !searchOpen.value
  if (!searchOpen.value) searchTerm.value = ''
}

export function runSearch() {
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

// ============================================================ 数据加载（读这一篇那半边）
//
// 「拉列表 + 补进行中那条详情」属于库页，在 `stores/useLibrary`；
// 这里只管**当前这一篇**的详情、块与进度推送。

/** 取任务全量信息（块 + 文件就绪 + 导读状态）。失败返回 null，由调用方决定怎么显示。 */
export async function fetchTaskDetail(taskId) {
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

export async function refreshWorkbench(taskId) {
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

export function resetWorkbench() {
  understandReset()
  resetAsk()
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

/**
 * 个人中心（M5）的「默认读法」偏好 → 打开任务时用哪个模式。
 *
 * ⚠️ 偏好只存在本机 `localStorage.docwise_prefs`（**后端没有偏好接口**，契约的 N 清单里
 * 也没有这一项），所以这里直接读它——读不到 / 坏数据 / 值不认识一律回落"段落精读"。
 * ⚠️ `pdf`（原版）那一档在 v2 阅读区**没有对应模式**（v1 的 iframe 原版已去掉，
 * PDF 走 `mono` / `dual`），所以它回落；`docModeOptions` 那头还有一道校验：
 * 任务没有对应产物（比如没有双语稿）时同样回落，不会卡在一个打不开的模式上。
 */
function preferredDocMode() {
  const byPref = { blocks: 'paragraph', mono: 'mono', dual: 'dual' }
  try {
    const raw = JSON.parse(localStorage.getItem('docwise_prefs') || '{}')
    return byPref[raw.defaultView] || 'paragraph'
  } catch {
    return 'paragraph'
  }
}

/** 打开任意任务到阅读工作台（历史「继续读」/ 上传后 / 首屏示例入口 走同一条路径）。 */
export async function openTask(task, options = {}) {
  stopProgress()
  currentTask.value = task
  view.value = 'reader'
  assistTab.value = options.tab || 'ask'
  docMode.value = preferredDocMode()
  resetWorkbench()
  assistTab.value = options.tab || 'ask'
  // 地址跟着状态走：进了阅读工作区就把它写进 hash（刷新 / 后退才不会丢页）。
  // `replace` 由调用方决定——库页点进来是"新的一步"（可后退），
  // 而删除任务后自动跳转之类不希望用户退回去的，才用 replace。
  if (!options.skipHash) {
    navigateToHash({ name: 'read', params: { taskId: task.id } }, { replace: options.replaceHash })
  }
  await refreshWorkbench(task.id)
  if (ACTIVE_STATES.includes(task.status)) startProgress(task.id)
  if (await applyResumePosition()) showToast(`已回到第 ${task.last_read_page} 页`)
}

export function backToLibrary() {
  closeMenus()
  // 两件事分开做，**不互相依赖**：
  // ① 状态直接设对（就算地址已经是 `#/`，也保证真的回到库页）；
  // ② 地址跟着改。②里若目标与当前相同会提前返回——**所以①必须有**，
  //    否则"地址没变"就顺带把"回库页"也吞掉了（踩过：测试真红过一条）。
  view.value = 'library'
  navigateToHash({ name: 'library' })
}

// ============================================================ 进度推送（SSE + 轮询兜底）

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
    loadTasksAndSync()
    if (evt.type === 'completed') refreshWorkbench(currentTask.value.id)
  }
}

export function stopProgress() {
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
export const locateText = ref('')
/** 每次请求定位都 +1：同一个块再点一次也要重新定位。 */
export const locateKey = ref(0)
/** 正在定位的那个块编号（算"对不上时至少翻到第几页"用）。 */
export const pendingBlockId = ref('')

export const pdfFallbackPage = computed(() => {
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
export function onPdfLocate(result) {
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
export function onPdfAsk({ text, context }) {
  const block = findBlockByText(context || text, blocks.value) || findBlockByText(text, blocks.value)
  askAnchor.value = block ? { blockId: block.block_id, text } : null
  askQuestion.value = `就这段提问：${text}`
  assistTab.value = 'ask'
  if (isNarrow.value && sheetState.value === 'peek') sheetState.value = 'half'
  submitAsk()
}

export async function setDocMode(mode) {
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
export const downloadOptions = computed(() => {
  if (isNativeTask.value) return [{ key: 'mono', label: '下载原稿 PDF' }]
  return [
    { key: 'dual', label: '下载双语稿' },
    { key: 'mono', label: '下载纯中文稿' },
  ]
})

export async function runDownload(item) {
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

// ============================================================ 理解层加载

export function understandReset() {
  understandingLoading.value = false
  understandingStatus.value = 'pending'
  understandingGuide.value = null
  understandingTerms.value = []
  understandingError.value = ''
  understandingTried.value = false
}

export async function loadUnderstanding(taskId, { generate = false } = {}) {
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

export function retryUnderstanding() {
  if (!currentTask.value) return
  understandingTried.value = false
  loadUnderstanding(currentTask.value.id, { generate: true })
}

/** 切副页签：手机端从 peek 档点页签要顺手展开（否则点了像没反应）。 */
export function switchTab(key) {
  assistTab.value = key
  honestNote.value = ''
  if (isNarrow.value && sheetState.value === 'peek') sheetState.value = 'half'
  if (key !== 'guide' && key !== 'terms') return
  if (!currentTask.value || !understandable.value) return
  if (understandingLoading.value || understandingStatus.value === 'ready') return
  if (understandingTried.value) return
  loadUnderstanding(currentTask.value.id, { generate: true })
}

export async function loadBlocks(taskId) {
  try {
    const res = await authFetch(`/api/tasks/${taskId}`)
    if (!res.ok) return
    const data = await res.json()
    blocks.value = data.blocks || []
  } catch {
    /* 拿不到块就没法做术语定位，界面自己会直说 */
  }
}

// ============================================================ 收尾

/**
 * 清掉本模块的定时器。**组件卸载时必须调**（App.vue 的 onUnmounted 里）——
 * 状态搬走了，定时器也跟着搬走了；卸载时再去 `clearTimeout(flashTimer)` 会报
 * `flashTimer is not defined`，一条用例挂掉会连累后面几十条（上一轮真踩过）。
 */
export function disposeReader() {
  if (flashTimer) clearTimeout(flashTimer)
  if (elapsedTimer) clearInterval(elapsedTimer)
  flashTimer = null
  elapsedTimer = null
}
