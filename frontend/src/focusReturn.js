/**
 * 弹层关掉之后，把焦点还给"打开它的那个元素"（全端检查 G3，2026-11-17）。
 *
 * 为什么要单独一个模块：浏览器在触发元素被藏起来 / 卸载时，会把焦点**丢回 `body`**。
 * 键盘用户按 `Esc` 关掉一层弹窗后，再按 `Tab` 会从整页开头重新数起 ——
 * 走查里 G3「焦点不丢」没通过，说的就是这一条。
 *
 * 用法（三步，别省第一步）：
 *
 *   const opener = rememberFocus()   // 打开的那一刻就记（此时焦点还在触发元素上）
 *   ...
 *   returnFocus(opener)              // 关掉之后还回去
 *
 * 两个函数都自己判空：`document.activeElement` 是 `body` / `documentElement` 时返回 `null`
 * （没有任何地方可以还），元素已经在关闭过程中被卸载（`isConnected === false`）时**什么都不做**。
 * ⚠️ 不要在这里做 `querySelector` 兜底找"大概是谁"：猜错等于把焦点扔到不相干的地方，
 * 比留在 `body` 更糟。
 */

/**
 * 记住当前焦点落在哪个元素上。
 *
 * @param {Document | null} doc 可注入，便于单测；默认取全局 `document`
 * @returns {Element | null} 没得记时返回 `null`
 */
export function rememberFocus(doc = typeof document === 'undefined' ? null : document) {
  if (!doc) return null
  const el = doc.activeElement
  if (!el || el === doc.body || el === doc.documentElement) return null
  return el
}

/**
 * 把焦点还回去。
 *
 * @param {Element | null} el `rememberFocus()` 记下的元素
 * @returns {boolean} 真的调了 `focus()` 才算 `true`
 */
export function returnFocus(el) {
  if (!el || typeof el.focus !== 'function') return false
  // 已经被卸载的元素上 focus() 是空操作（在某些浏览器里还会抛），直接判掉
  if (el.isConnected === false) return false
  el.focus()
  return true
}
