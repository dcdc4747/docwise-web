/**
 * 素材库页的纯逻辑（E2）：**文案与判据都放这里**，模板只负责摆。
 *
 * 为什么单独一个文件：这一页最容易出的问题是**说错话**——
 * 把"筛出来是空的"说成"你还没有素材卡"（于是用户以为素材丢了）、
 * 把"源文献已删、只剩快照"当正常卡展示。这些都能单测。
 */

/**
 * 顶部那句量：`共 3 条` / `还没有素材卡`。
 *
 * ⚠️ **有筛选时必须换说法**：筛到 0 条时说"还没有素材卡"是**跟下面空态打架**——
 * 同一屏顶部说"你一张都没有"、下面说"这个筛选下没有"，用户会以为素材丢了。
 * 这条是实拍抓到的（选了一个空集合：顶部「还没有素材卡」+ 下面「这个筛选下没有…」）。
 */
export function countsText(count, { hasFilters = false } = {}) {
  const n = Number(count)
  if (!Number.isFinite(n) || n < 0) return '—'
  if (hasFilters) return `本筛选 ${n} 条`
  if (n === 0) return '还没有素材卡'
  return `共 ${n} 条`
}

/**
 * 空态文案（**分两种，别混成一句"暂无数据"**，设计规范 §7.1）：
 * - 一条都没有 → 告诉你怎么产生第一条；
 * - 只是这个筛选下没有 → 给出口（换筛选 / 清空）。
 */
export function emptyText({ hasFilters = false } = {}) {
  if (hasFilters) {
    return '这个筛选下没有素材卡 —— 换一个集合 / 标签，或者点「清空筛选」看全部。'
  }
  return '还没有素材卡。在读文献时划词、或点问答与导读里的「存为素材卡」，这里就会一条条列出来。'
}

/**
 * 当前筛选的一句话摘要（顶部显示）。
 *
 * ⚠️ **不带筛选就明说"全部素材"**，别留空——空着会让人以为筛选没生效。
 */
export function filtersText({ collectionName = '', tag = '' } = {}) {
  const parts = []
  if (collectionName) parts.push(`集合：${collectionName}`)
  if (tag) parts.push(`标签：${tag}`)
  return parts.length ? parts.join(' · ') : '全部素材'
}

/**
 * 一条素材卡能不能"点出处跳回原文"。
 *
 * ⚠️ 三种情况要分开说（与 `useWrite.jumpToMaterial` 的四条口径一致）：
 * - `task_id` 为空 → **源文献已删**，只剩快照；
 * - 有 `task_id` 但没有 `block_id` → 只打开文献、**不假装定位到句子**；
 * - 都有 → 可以定位。
 */
export function sourceState(material) {
  const taskId = Number(material?.task_id)
  const hasTask = Number.isFinite(taskId) && taskId > 0
  const blockId = String(material?.block_id ?? '').trim()
  if (!hasTask) {
    return { canLocate: false, canOpen: false, reason: '源文献已删除，只保留了这段快照' }
  }
  if (!blockId) {
    return { canLocate: false, canOpen: true, reason: '这条素材没记下段落坐标，只能打开文献' }
  }
  return { canLocate: true, canOpen: true, reason: '' }
}

/** 出处那一行的人话：`源文献名 · 第 N 页`（页号缺失就如实说"页码待定"）。 */
export function sourceLabel(material) {
  const name = String(material?.source_name ?? '').trim() || '（源文献名缺失）'
  const page = Number(material?.page)
  if (!Number.isFinite(page) || page <= 0) return `${name} · 页码待定`
  return `${name} · 第 ${page} 页`
}

/**
 * 从集合列表里找名字（给筛选摘要用）。
 *
 * ⚠️ 找不到就回空串，**不回 id 冒充名字**——界面上出现一个数字没人看得懂。
 */
export function collectionNameOf(collections, id) {
  const target = Number(id)
  if (!Number.isFinite(target) || target <= 0) return ''
  const hit = (Array.isArray(collections) ? collections : []).find(
    (item) => Number(item?.id) === target,
  )
  return hit ? String(hit.name || '') : ''
}
