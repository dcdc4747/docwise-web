/**
 * 论文列表（"我的论文"那一份数据）。
 *
 * **为什么单独一个最小的 store**：阅读区与库页都要用它 —— 库页要列出来、阅读区要按 id 找到那一篇。
 * 若把它塞进 `useLibrary`，`useReader` 就得依赖 `useLibrary`；
 * 而库页点卡片又要调 `useReader` 的「打开」→ **两边互相依赖，绕成环**。
 * 拆成这个小 store 之后：**两边都依赖它、它不依赖任何 store**，环就断了。
 *
 * ⚠️ 状态在**模块顶层**（单例）：定义在函数里的话，每次调用都会新建一份列表，
 * 库页删了一篇、阅读区还以为它在。
 */

import { ref } from 'vue'

import { authFetch } from '../auth'

/** 当前账号的论文列表（后端已按归属过滤，最多 50 条、新的在前、归档的不返回）。 */
export const tasks = ref([])
export const historyLoading = ref(false)
export const historyError = ref('')

/**
 * 筛选条件 → 查询串（契约 §2.2 的 N8）。
 *
 * ⚠️ 数组按契约写成 `tag[]=A&tag[]=B`（**键名带方括号**，方括号不转义——
 * 契约、mock、后端读的都是这个写法；转成 `%5B%5D` 虽然多数服务端也会解回来，
 * 但日志与抓包里就对不上契约了）。空值一律不进串——
 * 不发 `?reading_status=` 这种"看起来筛了其实没筛"的请求。
 * 值全部 `encodeURIComponent`：标签是用户自己起的名字，中文、`&`、空格都可能出现。
 */
function tasksQuery(params) {
  const parts = []
  for (const [key, value] of Object.entries(params || {})) {
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item !== '' && item !== null && item !== undefined) {
          parts.push(`${encodeURIComponent(key)}[]=${encodeURIComponent(item)}`)
        }
      }
    } else if (value !== '' && value !== null && value !== undefined) {
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
    }
  }
  return parts.length ? `?${parts.join('&')}` : ''
}

/**
 * 从后端把列表拉进 `tasks`。
 *
 * `params` 可选：契约 §2.2 的 N8 四个筛选参数（`reading_status` / `collection_id` /
 * `tag[]` / `smart_id`）。**不传 = 与以前逐字节同一条请求**（裸数组、50 条、归档不出），
 * 所以老调用方一行都不用改。
 *
 * ⚠️ **它只负责"取数据"**：原实现里 `finally` 还调了一次 `syncActiveDetail()`（对进行中那条补详情），
 * 那个联动要读阅读区，所以**没搬进来**——`stores/useLibrary` 在 `loadTasks()` 之后自己调，
 * 包成 `loadTasksAndSync()`。
 */
export async function loadTasks(params = null) {
  historyLoading.value = true
  historyError.value = ''
  try {
    const res = await authFetch(`/api/tasks${tasksQuery(params)}`)
    if (!res.ok) throw new Error(`历史任务加载失败（HTTP ${res.status}）`)
    tasks.value = await res.json()
  } catch (err) {
    historyError.value = err.message || '历史任务加载失败'
  } finally {
    historyLoading.value = false
  }
}

/** 按 id 找一篇（阅读区按地址回原页、与详情对齐时都要用）。 */
export function findTask(id) {
  return tasks.value.find((item) => item.id === id)
}

/** 用新的任务对象替换列表里的同 id 项（刷新详情、重试之后保持列表一致）。 */
export function patchTask(task) {
  if (!task || task.id === undefined) return
  tasks.value = tasks.value.map((item) => (item.id === task.id ? { ...item, ...task } : item))
}

/** 清空（退出登录时调）。 */
export function clearTasks() {
  tasks.value = []
  historyError.value = ''
}

// ============================================================ 任务的状态与文案
//
// 库页、阅读区、弹层三处要用**同一套**写法（形态硬约定："档位只有一个写法"）。
// 放在这个最小的叶子 store 里：谁都能直接 import，谁也不会跟谁绕成环。

export const ACTIVE_STATES = ['pending', 'in_progress']
export const RETRYABLE_STATES = ['failed', 'cancelled']
export const TERMINAL_STATES = ['completed', 'failed', 'cancelled']

export const statusTextMap = {
  pending: '排队中',
  in_progress: '翻译中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

/** 状态胶囊配色（照原型：已完成=绿、失败=红、已取消=橙、其余=灰）。 */
export const statusChipMap = { completed: 'ok', failed: 'fail', cancelled: 'warn' }

/** 档位只有一个写法（形态硬约定）：选择处、工具条、卡片一律用这一套。 */
export const tierTextMap = {
  fast: '快档 · 最快',
  medium: '中档 · 平衡',
  // 历史任务里若出现过精档，如实显示"未开放"，不写"最准"——那个能力还没做
  precise: '精档（未开放）',
}
