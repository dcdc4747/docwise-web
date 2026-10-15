/**
 * 素材卡的**写入路径**（M2 / 契约 §2.4 的 N12–N14）。
 *
 * 三条口径（都有理由，别简化掉）：
 *
 * ① ⭐ **三处创建入口共用这一条路径**（阅读区的划词浮标 / 问答出处 / 导读要点）——
 *    各写一套必然漂移：形状、错误文案、去重各走各的。
 * ② ⭐ **撤销窗口在客户端、5 秒**：契约里**没有"恢复"端点**（N14 只有软删），
 *    所以"删错了再撤回来"只能发生在**发出 `DELETE` 之前**。于是 `removeMaterial`
 *    先本地标记"待删除"并给 5 秒，**5 秒后才真发 `DELETE`**；这 5 秒内卡片只是被
 *    藏起来（数据还在），点「撤销」就什么都不发。
 *    ⚠️ **推论（如实记）**：`MaterialCard.vue` 的**软删态**（`deleted_at` 非空 +
 *    「撤销删除」按钮）在**生产路径上不可达** —— 它只在自跑演示（`:demo="true"`
 *    或 URL 带 `demo=mock`）里出现。所以本 store **不实现 `restore`**、
 *    `WriteView` 也**不挂 `@restore`**：那种状态下界面不该给一个点了没用的"撤销"键。
 * ③ 失败一律给人话（`materialsError` / `saveState.message`），**不抛未捕获异常**：
 *    存不上不该把阅读页打崩；删不掉要把卡片**放回列表**（本地只是藏起来，天然回得来）。
 *
 * ⚠️ 状态定义在模块顶层（单例），与 `useWrite` / `useReader` / `useUi` 一致。
 */

import { ref } from 'vue'

import { apiJson } from '../auth'

/** 客户端撤销窗口（毫秒）。契约没有恢复端点，窗口只能开在 `DELETE` 之前。 */
export const UNDO_MS = 5000

export const materials = ref([])
export const materialsLoading = ref(false)
export const materialsError = ref('')

/** 保存状态：按 `blockId` 区分，供三处入口各自**就地反馈**。
 *  `status ∈ {idle, saving, saved, error}`，`message` 是给人看的那句话。 */
export const saveState = ref({ blockId: '', status: 'idle', message: '' })

/** 待删除（撤销窗口内）：`{ id, material, timer }`；同一时刻只允许一条。 */
export const pendingDelete = ref(null)

function _clearTimer(pending) {
  if (pending && pending.timer) clearTimeout(pending.timer)
}

function _messageOf(err, fallback) {
  const text = err && err.message ? String(err.message) : ''
  return text || fallback
}

/** `GET /api/materials`（N13）。素材栏挂了不影响写稿——只记错误，不抛。 */
export async function loadMaterials() {
  materialsLoading.value = true
  materialsError.value = ''
  try {
    const data = await apiJson('/api/materials')
    materials.value = Array.isArray(data?.items) ? data.items : []
    return materials.value
  } catch (err) {
    materialsError.value = _messageOf(err, '素材加载失败')
    return []
  } finally {
    materialsLoading.value = false
  }
}

/**
 * `POST /api/materials`（N12）—— 三处入口都走这一条。
 *
 * ⚠️ 契约的入参只有 `{task_id, block_id, note?}`：**原文与出处由服务端按块深拷贝**，
 * 所以划词存下来的是**那一段**（不是选中那一句）——按钮文案别说成"存这一句"。
 */
export async function saveMaterial({ taskId, blockId, note = null } = {}) {
  const tid = Number(taskId)
  const bid = String(blockId || '').trim()
  if (!tid || !bid) {
    saveState.value = {
      blockId: bid,
      status: 'error',
      message: '这一段没有可用的块坐标，存不了素材。',
    }
    return null
  }
  saveState.value = { blockId: bid, status: 'saving', message: '' }
  const body = { task_id: tid, block_id: bid }
  if (note) body.note = String(note).slice(0, 500)
  try {
    const created = await apiJson('/api/materials', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    // 新的在前；同 id 去重（后端重复存同块会各给一条，这里只保证不出现两条一样 id）
    materials.value = [created, ...materials.value.filter((item) => item.id !== created.id)]
    saveState.value = { blockId: bid, status: 'saved', message: '' }
    return created
  } catch (err) {
    saveState.value = {
      blockId: bid,
      status: 'error',
      message: _messageOf(err, '这条素材没存上，稍后再试。'),
    }
    return null
  }
}

async function _commitDelete(id) {
  try {
    await apiJson(`/api/materials/${id}`, { method: 'DELETE' })
    materials.value = materials.value.filter((item) => item.id !== id)
  } catch (err) {
    // 卡片本地只是被藏起来，没删掉它就自然回到列表里；这里只把话说清楚
    materialsError.value = _messageOf(err, '这条素材没删掉，已经放回列表。')
  }
}

/**
 * `DELETE /api/materials/{id}`（N14）—— **但先给 5 秒撤销**。
 * 5 秒内卡片不出现在列表里（本地标记），**一个请求都不发**。
 */
export function removeMaterial(id) {
  const target = materials.value.find((item) => item.id === id)
  if (!target) return
  if (pendingDelete.value) {
    // 同一时刻只留一条待删：前一条立刻提交（用户已经转去删别的了）
    flushPendingDelete()
  }
  pendingDelete.value = {
    id,
    material: target,
    timer: setTimeout(() => {
      const pending = pendingDelete.value
      if (!pending || pending.id !== id) return
      pendingDelete.value = null
      _commitDelete(id)
    }, UNDO_MS),
  }
}

/** 撤销：清掉定时器，**什么都不发**，卡片回到列表。 */
export function cancelPendingDelete() {
  const pending = pendingDelete.value
  if (!pending) return
  _clearTimer(pending)
  pendingDelete.value = null
}

/** 立刻提交待删（切换待删对象、或调用方要收尾时用）。 */
export function flushPendingDelete() {
  const pending = pendingDelete.value
  if (!pending) return Promise.resolve()
  _clearTimer(pending)
  pendingDelete.value = null
  return _commitDelete(pending.id)
}

/** 测试用：清空列表与一切待删定时器（别让定时器漏到下一个用例）。 */
export function resetMaterials() {
  cancelPendingDelete()
  materials.value = []
  materialsLoading.value = false
  materialsError.value = ''
  saveState.value = { blockId: '', status: 'idle', message: '' }
}
