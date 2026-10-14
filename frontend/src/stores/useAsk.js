/**
 * 问答线程：提问、回答、出处、重试、复制。
 *
 * **为什么单独一个模块**：问答是主力功能、改得最勤，以前它和"论文数据""界面零碎事"
 * 一起挤在 `App.vue` 的 1819 行脚本里。搬出来之后，改问答不用碰别的。
 *
 * ⚠️ **状态定义在模块顶层（单例）**，不在 `useAsk()` 里：定义在函数里的话，
 * 每次调用都会新建一份"问过什么"，两个地方看到的线程就不一样了。
 *
 * ⚠️ **它引用的东西由 App.vue 注入**（见 `initAsk`），不是 import 别的 store ——
 * 那样会绕成环（`useUi` 要用它的"当前问题"，它又要用 `useUi` 的提示条）。
 * 注入还有个好处：将来把 `blocks` / `loadBlocks` 搬进 `useReader` 时，只改传参、这里不用动。
 */

import { computed, ref } from 'vue'

import { authFetch } from '../auth'
import { mergeSourceRuns, sourceLabel } from '../blockLabel'
import { assistTab, isNarrow, scrollThreadToEnd, setNote, sheetState } from './useUi'

// ============================================================ 外部依赖（注入）

/** 本任务的块列表（出处标签要按它算页码 / 那一句开头）。 */
let blocksRef = ref([])
/** 当前在读的那一篇。 */
let currentTaskRef = ref(null)
/** 按需加载块列表（问题问得比块加载早时用）。 */
let loadBlocksFn = async () => {}

/**
 * 注入外部依赖。**在 App.vue 里调一次即可**（重复调只是换个引用，不影响已有线程）。
 *
 * @param {{blocks: import('vue').Ref, currentTask: import('vue').Ref, loadBlocks: Function}} deps
 */
export function initAsk({ blocks, currentTask, loadBlocks }) {
  blocksRef = blocks
  currentTaskRef = currentTask
  loadBlocksFn = loadBlocks
}

// ============================================================ 状态

export const askQuestion = ref('')
export const askLoading = ref(false)
/** 提问锚点：划词（桌面）或点段号（手机）带上的那一段。 */
export const askAnchor = ref(null)
/** 线程里的自增编号（只在本会话内唯一，用于 patchTurn 定位）。 */
let turnSeq = 0
export const askThread = ref([])

// ============================================================ 派生

/** 出处标签在渲染前就把人话坐标算好（模板里不出现函数调用）；相邻行同样先合并成一句。 */
export const askTurns = computed(() =>
  askThread.value.map((turn) => ({
    ...turn,
    sources: mergeSourceRuns(turn.sourceIds || [], blocksRef.value).map((run) => {
      const label = sourceLabel(run.id, blocksRef.value, run.text ? { text: run.text } : {})
      return { id: run.id, ids: run.ids, text: run.text, label, found: Boolean(label) }
    }),
  })),
)

/** 线程里最后问过的那个问题（顶部抽屉摘要等地方要显示它）。 */
export const lastQuestion = computed(() => {
  const turns = askThread.value
  for (let i = turns.length - 1; i >= 0; i -= 1) {
    if (turns[i].question) return turns[i].question
  }
  return ''
})

export const quickChips = [
  { label: '局限与不足', q: '这项研究有什么局限？' },
  { label: '未来工作', q: '论文提到的未来工作是什么？' },
  { label: '用了哪些数据', q: '研究用了哪些数据或样本？' },
  { label: '主要结果', q: '主要结果是什么？' },
  { label: '结论可靠吗', q: '这些结论有多可靠？' },
]

export const askChipsHint =
  '导读已覆盖的五个要点（研究问题 / 方法 / 结论 / 创新点 / 贡献）在「导读」页签里，术语解释在「术语」页签里——这里只放它们都没答的提问'

export const composerPlaceholder = '就这篇论文提问，或先划词再问…'

// ============================================================ 动作

export function patchTurn(id, patch) {
  askThread.value = askThread.value.map((turn) => (turn.id === id ? { ...turn, ...patch } : turn))
}

/** 清空线程与输入（换一篇论文、重置工作区时调）。 */
export function resetAsk() {
  askThread.value = []
  askQuestion.value = ''
  askLoading.value = false
  askAnchor.value = null
}

export async function submitAsk() {
  const question = (askQuestion.value || '').trim()
  const task = currentTaskRef.value
  if (!question || askLoading.value || !task) return
  if (!blocksRef.value.length) await loadBlocksFn(task.id)
  askQuestion.value = ''
  askLoading.value = true
  const id = ++turnSeq
  askThread.value = [
    ...askThread.value,
    {
      id,
      question,
      answer: '',
      sourceIds: [],
      mode: '',
      loading: true,
      error: '',
      errorDetail: '',
      copied: false,
    },
  ]
  scrollThreadToEnd()
  try {
    const res = await authFetch(`/api/tasks/${task.id}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        // 形态：提问锚点与出处是同一个坐标系——把划词 / 点段号选中的那段带给后端
        focus_block_ids:
          askAnchor.value && askAnchor.value.blockId ? [askAnchor.value.blockId] : [],
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

export function retryTurn(turn) {
  askThread.value = askThread.value.filter((item) => item.id !== turn.id)
  askQuestion.value = turn.question
  submitAsk()
}

export function askPreset(question) {
  askQuestion.value = question
  return submitAsk()
}

/** 导读卡「就这条追问」：带着这条要点的出处段落去问，答案同样标出处。 */
export function probePoint(point) {
  const anchorId = point.sources.length ? point.sources[0].id : ''
  askAnchor.value = anchorId ? { blockId: anchorId, text: point.text } : null
  askQuestion.value = `关于「${point.label}」这条，能再展开说一点吗？`
  assistTab.value = 'ask'
  if (isNarrow.value && sheetState.value === 'peek') sheetState.value = 'half'
  submitAsk()
}

/** 手机端：点段号那一下——设锚点并直接问。 */
export function askParagraph(row) {
  askAnchor.value = { blockId: row.block.block_id, text: row.source }
  // 收起浮出的段落条（它在 useUi 里，由 App.vue 的模板绑着）
  askQuestion.value = '就这段提问：这段在讲什么？'
  assistTab.value = 'ask'
  sheetState.value = 'half'
  submitAsk()
}

export async function copyAnswer(turn) {
  try {
    if (navigator.clipboard) await navigator.clipboard.writeText(turn.answer || '')
    patchTurn(turn.id, { copied: true })
    setTimeout(() => patchTurn(turn.id, { copied: false }), 1500)
  } catch {
    setNote('这个浏览器不让读剪贴板——手动选中复制即可')
  }
}
