/**
 * 窄屏（390）溢出守卫 —— 三条修复各自的源码级守卫。
 *
 * 为什么只能守源码、守不了渲染：happy-dom **不会真的应用外部样式表**，
 * 所以在单测里断言"计算后的宽度"是假的（详见 `toc-tree.test.js` 里那条教训）。
 *
 * 但这三条 bug 有一个共同点：**错了不会报红**——
 * `.dw-layout` 是 `overflow: hidden`，弹性链被内容顶宽之后整块**被默默裁掉**，
 * `document.scrollingElement.scrollWidth` 仍是 390，vitest / build 一声不吭。
 * 所以每条都写成"**这条规则必须在它该在的位置上**"：
 *   · 顶层档的规则 → 花括号深度必须是 0（少一个 `}` 就会掉进上一个 `@media`，桌面档静默失效）；
 *   · 手机档的规则 → 必须**恰好**在 `@media (max-width: 719px)` 那一块里（不是 859、也不是顶层）。
 *
 * 三条数字都来自 2026-10-16 在真实页面上（cdp，390×844，真产物 + 真数据）的量测：
 *   ① `.mobile-reader` **904.9px** → 补 `min-width: 0` → **332px**（目录 876.9 → 304）
 *   ② 库页 `.grid3` 轨道被文件名顶到 **573.3px**（可用 284px）→ 补 `overflow-wrap: anywhere` → **284px**
 *   ③ `.proc-field` **464px** / `.proc-select` **443.5px**（视口 390，右边界 534）
 *      → 三条一起补（label 的 max-width + 下拉的 max-width/flex/min-width）→ 299.3 / 275.8
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const readSrc = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8')
const css = readSrc('../src/style.css')

/** 去掉注释（注释里的花括号会把深度算歪）。与 `css` 同一套下标（注释被换成等长空格）。 */
const blanked = css.replace(/\/\*[\s\S]*?\*\//g, (m) => ' '.repeat(m.length))

/** 某个下标处累计的 `{` / `}` 深度（0 = 顶层）。 */
function braceDepthAt(source, index) {
  let depth = 0
  for (let i = 0; i < index; i += 1) {
    if (source[i] === '{') depth += 1
    else if (source[i] === '}') depth -= 1
  }
  return depth
}

/** 所有注释的 [起, 止) 区间——注释里也会出现选择器名（本文件就写了），必须跳过。 */
function commentRanges(source) {
  const ranges = []
  const re = /\/\*[\s\S]*?\*\//g
  let m
  while ((m = re.exec(source)) !== null) ranges.push([m.index, m.index + m[0].length])
  return ranges
}
const COMMENTS = commentRanges(css)
const inComment = (i) => COMMENTS.some(([a, b]) => i >= a && i < b)

/** 找出含指定文本的第一条规则块，返回它的下标与体内文字。 */
function ruleAt(needle) {
  let at = -1
  for (let i = 0; i < blanked.length; i += 1) {
    const found = blanked.indexOf(needle, i)
    if (found < 0) break
    if (!inComment(found)) { at = found; break }
    i = found
  }
  expect(at, `源码里找不到这条规则：${needle}`).toBeGreaterThan(-1)
  const open = blanked.indexOf('{', at)
  const close = blanked.indexOf('}', open)
  expect(open, `规则没有正体的块：${needle}`).toBeGreaterThan(-1)
  return { at, open, close, body: css.slice(open + 1, close) }
}

/** `@media (max-width: 719px)` 那一块的 [开始, 结束) 下标。 */
function mediaBlock(maxWidth) {
  const needle = `@media (max-width: ${maxWidth}px)`
  let at = -1
  for (let i = 0; i < blanked.length; i += 1) {
    const found = blanked.indexOf(needle, i)
    if (found < 0) break
    if (!inComment(found)) { at = found; break }
    i = found
  }
  expect(at, `源码里找不到 ${needle}`).toBeGreaterThan(-1)
  const open = blanked.indexOf('{', at)
  let depth = 0
  for (let i = open; i < blanked.length; i += 1) {
    if (blanked[i] === '{') depth += 1
    else if (blanked[i] === '}') {
      depth -= 1
      if (depth === 0) return { start: open, end: i, at }
    }
  }
  throw new Error(`${needle} 没有闭合`)
}

/** `@media (max-width: 719px)` 里**所有** `规则选择器` 的规则体（跳过注释里的同名文字）。 */
function bodiesInMedia(maxWidth, selector) {
  const { start, end } = mediaBlock(maxWidth)
  const bodies = []
  let from = start
  for (;;) {
    const rel = blanked.indexOf(selector, from)
    if (rel < 0 || rel >= end) break
    if (inComment(rel)) { from = rel + selector.length; continue }
    const open = blanked.indexOf('{', rel)
    const close = blanked.indexOf('}', open)
    if (open < 0 || close < 0 || open >= end) break
    bodies.push(css.slice(open + 1, close))
    from = close + 1
  }
  return bodies
}

describe('窄屏溢出守卫 ①：阅读页弹性链必须能缩（`min-width: 0`）', () => {
  it('⭐ `.dw .mobile-reader` 带 `min-width: 0`，且规则在**顶层**', () => {
    const { at, body } = ruleAt('.dw .mobile-reader')
    expect(body).toMatch(/min-width:\s*0/)
    // 顶层：掉进任何 `@media` 都会让桌面/窄屏两档行为不一致（上一轮真踩过少一个 `}`）
    expect(braceDepthAt(blanked, at)).toBe(0)
  })

  it('它仍然是个 `flex: 1` 的纵向列（`min-width` 不许把既有布局改掉）', () => {
    const { body } = ruleAt('.dw .mobile-reader')
    expect(body).toMatch(/flex:\s*1/)
    expect(body).toMatch(/flex-direction:\s*column/)
    expect(body).toMatch(/min-height:\s*0/)
  })

  it('`.pdoc` 仍是这条链上可滚的那一环（缩下去之后还得能滚）', () => {
    const { body } = ruleAt('.dw .pdoc {')
    expect(body).toMatch(/overflow:\s*auto/)
  })
})

describe('窄屏溢出守卫 ②：库页卡片文件名必须能断行', () => {
  it('⭐ `.dw .paper-card .fname` 带 `overflow-wrap: anywhere`，且规则在**顶层**', () => {
    const { at, body } = ruleAt('.dw .paper-card .fname')
    expect(body).toMatch(/overflow-wrap:\s*anywhere/)
    expect(braceDepthAt(blanked, at)).toBe(0)
  })

  it('守卫要能区分"能断"与"只能裁"：`min-width: 0` / `overflow: hidden` **不算修好**', () => {
    // 实测：卡片被顶宽的病根是**最小内容宽度**（不可断的存储前缀），
    // `min-width: 0` 只解除"不许缩"，管不了 min-content —— 格子仍是 573px。
    const { body } = ruleAt('.dw .paper-card .fname')
    expect(body).not.toMatch(/overflow:\s*hidden/)
    expect(body).toMatch(/overflow-wrap/)
  })

  it('字号/字重那两条既有口径没被顺手改掉', () => {
    const { body } = ruleAt('.dw .paper-card .fname')
    expect(body).toMatch(/font-weight:\s*600/)
  })
})

describe('窄屏溢出守卫 ③：处理过程的筛选器必须收在手机档里', () => {
  it('⭐ 手机档里 `label.proc-field` 与 `select.proc-select` **两个都**要收，且下拉还要能参与收缩', () => {
    const fieldBodies = bodiesInMedia(719, '.dw .proc-field')
    const selectBodies = bodiesInMedia(719, '.dw .proc-select')
    expect(fieldBodies.length, '手机档里没有 .dw .proc-field 规则').toBeGreaterThan(0)
    expect(selectBodies.length, '手机档里没有 .dw .proc-select 规则').toBeGreaterThan(0)
    expect(fieldBodies.some((b) => /max-width:\s*100%/.test(b))).toBe(true)
    expect(selectBodies.some((b) => /max-width:\s*100%/.test(b))).toBe(true)
    // 只写 max-width 会差 8.5px（`max-width:100%` 按 label 的内容盒算，还要加 gap 与「文献」两字）
    expect(selectBodies.some((b) => /flex:\s*1 1 auto/.test(b))).toBe(true)
    expect(selectBodies.some((b) => /min-width:\s*0/.test(b))).toBe(true)
  })

  it('给 `label` 加的那条是本条 bug 的**关键**：只收下拉时 field 仍是 464px', () => {
    // 实测记录：只在下拉上写 max-width:100% → field 依旧 464px、右边界 534px（被裁 144px）。
    // 所以这条守卫专门盯"**外层也有边界**"，别以后被人当成冗余删掉。
    const fieldBodies = bodiesInMedia(719, '.dw .proc-field')
    expect(fieldBodies.some((b) => /max-width/.test(b))).toBe(true)
  })

  it('基础档的 `max-width: 220px` 不许被删（宽屏上的既有口径）', () => {
    const { body } = ruleAt('.dw .proc-select {')
    expect(body).toMatch(/max-width:\s*220px/)
  })

  it('手机档的那两条必须在 **719px** 这一块里（不是 859、也不是顶层）', () => {
    // 719 是形态 §3.4 的四级断点里"手机档"那一档；写错档位＝窄屏上根本没生效。
    const { start, end } = mediaBlock(719)
    const at = blanked.indexOf('.dw .proc-field { max-width: 100%; }')
    expect(at).toBeGreaterThan(start)
    expect(at).toBeLessThan(end)
  })
})
