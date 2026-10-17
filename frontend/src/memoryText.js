/**
 * 记忆页的纯逻辑（M7）：**文案与判据都放这里**，模板只负责摆。
 *
 * 为什么单独一个文件：这一页最容易出的问题是**说错话**——
 * 把"用过 0 次"说成"常用"、把"还没有记录"说成"暂无数据"、
 * 把"删除"做成没有退路。这些都能单测，不该靠眼睛发现。
 */

/** 两类记忆的标题（与后端 `kind` 一一对应，别在这里发明第三种）。 */
export const KIND_LABELS = {
  term: '术语习惯',
  cite: '引用习惯',
}

/** 引用格式的候选（`value` 与后端 `target` 同一个词；`label` 给人看）。 */
export const CITE_OPTIONS = [
  { value: 'author-year', label: '作者-年份（Smith, 2020）' },
  { value: 'numeric', label: '数字编号（[1] [2]）' },
  { value: 'footnote', label: '脚注编号' },
]

/**
 * 引用格式的人话。
 *
 * ⚠️ 没登记的标识**原样显示**，不许编一个人话出来（编了就是替用户认定了他的格式）。
 */
export function citeLabel(value) {
  if (!value) return ''
  const hit = CITE_OPTIONS.find((item) => item.value === value)
  return hit ? hit.label : String(value)
}

/**
 * "这条被真用上过几次"。
 *
 * ⚠️ 三种说法必须分开，不许合并：
 * - 0 次 → **"还没用过"**（不是"常用"，也不是"已启用"）；
 * - 1 次 → "用过 1 次"；
 * - 坏数据（负数 / 非数字）→ "—"（**不许编数字**）。
 */
export function hitsText(hits) {
  const n = Number(hits)
  if (!Number.isFinite(n) || n < 0) return '—'
  if (n === 0) return '还没用过'
  return `用过 ${n} 次`
}

/**
 * 空态文案（**分三种，别混成一句"暂无数据"**）。
 *
 * 设计规范 §7.1：真空给动作；筛空了给出口。
 */
export function emptyTextFor(kind) {
  if (kind === 'term') {
    return '还没有术语习惯。在下面填一对「原文里怎么写 → 你习惯叫什么」，下次问答和导读就会沿用你的说法。'
  }
  if (kind === 'cite') {
    return '还没有设引用格式。选一个，之后插引文就用它。'
  }
  return '还没有记忆。'
}

/**
 * "改过的句子"那一栏的说明（**这一期就是空的，如实说明为什么**）。
 *
 * ⚠️ 这一句是**产品纪律的展示**，不是借口：形态 §5 写死了
 * `观测期 ≥14 天 且 曝光块数 ≥500` 之前一律"继续观测"，所以现在不该建。
 * 写成"暂无数据"就变成敷衍；写成"正在学习"就是骗人。**说清门槛与现状**才对。
 */
export const EDITED_EMPTY_TEXT =
  '这一栏现在没有内容。它靠"改译文"那个动作积累，而按形态 §5 的规矩，' +
  '要攒够两周、看过的段落超过 500 段才有资格判断要不要建——现在还没到，所以不预先造一个空壳。'

/** 校验一对术语：两边都不能空（返回 `ok` 与给人看的那句话）。 */
export function validateTerm(source, target) {
  const src = String(source ?? '').trim()
  const dst = String(target ?? '').trim()
  if (!src) return { ok: false, source: '', target: dst, error: '「原文里怎么写」不能为空' }
  if (!dst) return { ok: false, source: src, target: '', error: '「你习惯叫什么」不能为空' }
  if (src.length > 255) {
    return { ok: false, source: src, target: dst, error: '原文词太长了（最多 255 字）' }
  }
  return { ok: true, source: src, target: dst, error: '' }
}

/** 顶部那句概况：`术语 3 条 · 引用 1 条`（没有就 `还没有任何记忆`）。 */
export function countsText(counts) {
  const term = Number(counts?.term) || 0
  const cite = Number(counts?.cite) || 0
  if (!term && !cite) return '还没有任何记忆'
  const parts = []
  if (term) parts.push(`术语 ${term} 条`)
  if (cite) parts.push(`引用 ${cite} 条`)
  return parts.join(' · ')
}

/** 这条记忆是不是"停用"状态（模板据此给一个可读的标注）。 */
export function isPaused(item) {
  return Boolean(item) && item.enabled === false
}
