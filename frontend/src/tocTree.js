/**
 * 目录变树（C3）：把**引擎侧结构**（`tasks.structure.headings`）变成可渲染的**扁平带深度**列表。
 *
 * ## 为什么用"扁平 + depth"而不是嵌套 children
 *
 * 渲染端只要多一个 `depth` 就能用 `--toc-depth` 缩进，**不必递归组件**；而且扁平列表
 * **顺序天然等于文档顺序**（引擎就是按文档顺序给的），跳转/高亮那条路一个字都不用改。
 *
 * ## 层级口径（三条，都是"不许崩、不许编"）
 *
 * 1. `level` 缺失 / 不是 1..4 的整数 → **按 1 处理**（顶层），照实降级，不猜；
 * 2. **跳级**（例如 1 → 3，中间没 2）：按"**挂在前面最近的更浅一层下面**"算，
 *    深度 = 当前打开着的更浅层数；不为了凑层级凭空造中间节点；
 * 3. **一条都产不出来**（全是空文本 / 不是数组 / 坏形状）→ 回**空数组**，
 *    调用方据此退回平铺目录（**一屏都不许空**）。
 *
 * ## `block_id` 为 null 的条目
 *
 * 引擎匹配不上块时给 null（实测化学那篇 `Abstract` / `References` 两条就是 null）。
 * 这种条目**仍然要显示**（它在作者声明的目录里确实存在），但**不可点**——
 * 点了没处去，**死链不许做成活链样式**（本仓硬规矩）。
 */

/** 结构里 `level` 的合法上限（超过的一律按 1 处理，不猜它想表达多深）。 */
export const MAX_TOC_LEVEL = 4

/** 单条标题的显示长度上限（与平铺目录那条口径一致）。 */
const TEXT_MAX = 90

/**
 * `level` 归一化：缺失 / 非整数 / 越界 → 1（顶层），照实降级。
 *
 * @param {unknown} raw 结构里的 `level`
 * @returns {number} 1..MAX_TOC_LEVEL
 */
export function normalizeLevel(raw) {
  const level = Number(raw)
  if (!Number.isInteger(level) || level < 1 || level > MAX_TOC_LEVEL) return 1
  return level
}

/**
 * 结构 headings → 扁平带深度列表。
 *
 * @param {unknown} headings `tasks.structure.headings`（可能缺失 / 坏形状）
 * @returns {{blockId: string|null, level: number, depth: number, text: string}[]}
 *   空数组表示"这条路给不出东西"，调用方应退回平铺目录。
 */
export function buildTocTree(headings) {
  if (!Array.isArray(headings)) return []
  const out = []
  /** 当前"打开着"的层级（自浅到深），长度就是下一条的 depth。 */
  const open = []
  for (const raw of headings) {
    if (!raw || typeof raw !== 'object') continue
    const text = String(raw.text ?? '')
      .replace(/\s+/g, ' ')
      .trim()
    // 没有文字就没法显示、也没法核（引擎侧也过滤过一遍，这里再挡一次）
    if (!text) continue
    const level = normalizeLevel(raw.level)
    // 比"打开着的最后一层"更深 → 当它的子节点；否则先弹到同层或更浅
    while (open.length && open[open.length - 1] >= level) open.pop()
    out.push({
      blockId: typeof raw.block_id === 'string' && raw.block_id ? raw.block_id : null,
      level,
      depth: open.length,
      text: text.slice(0, TEXT_MAX),
    })
    open.push(level)
  }
  return out
}
