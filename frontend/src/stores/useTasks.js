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
 * 从后端把列表拉进 `tasks`。
 *
 * ⚠️ **它只负责"取数据"**：原实现里 `finally` 还调了一次 `syncActiveDetail()`（对进行中那条补详情），
 * 那是 App 级的联动、会反向依赖阅读区，所以**没搬进来**——App.vue 在 `loadTasks()` 之后自己调。
 */
export async function loadTasks() {
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
