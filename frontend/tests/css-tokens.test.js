/**
 * CSS token 体检：**用了但从没定义过的 `var(--x)` 一律不许存在**。
 *
 * 为什么值得单独一条用例：这类 bug **特别隐蔽**——
 * - 浏览器不报错（CSS 本来就是容错的）；
 * - 控制台没有警告；
 * - DOM 上只是"那个属性没生效"，看起来像别的问题。
 *
 * 真踩过一次：`.dw .proc { padding: var(--sp-5) var(--sp-5) var(--sp-8) }`，
 * 而设计规范 §4.1 把间距定死 **7 级**（`--sp-1..7`）——`--sp-8` 根本不存在。
 * 于是**整条 `padding` 在计算时变无效**，退回 0，页面内容贴边、截图里看着像"左边被切了"；
 * 而高度/宽度、溢出探针全都正常，靠肉眼截图才发现。
 *
 * 口径：只查**没有 fallback** 的 `var(--x)`；写了 `var(--x, 12px)` 的即使没定义也能用，不算问题。
 */

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const SRC = resolve(process.cwd(), 'src')

function walk(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    const st = statSync(full)
    if (st.isDirectory()) out.push(...walk(full))
    else if (/\.(css|vue|js)$/.test(name)) out.push(full)
  }
  return out
}

const DEFINED = /(--[a-zA-Z0-9_-]+)\s*:/g
const USED = /var\(\s*(--[a-zA-Z0-9_-]+)\s*([^)]*)\)/g

/**
 * 把注释剥掉再扫。
 *
 * ⚠️ 这条是写这案子时踩出来的：第一版没跳注释，于是**注释里提到** `var(--sp-8)`
 * 也被算成"用了没定义的 token"→ 误报；反过来，注释里藏着的真用法也会被漏掉。
 * 剥法只处理两种情况，够用且不会误伤：`/* … *​/` 块注释、行首的 `//`（跳过 `http://`）。
 */
function stripComments(text) {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')
}

/** `{ token: [{file, line}] }`，只算没有 fallback 的用法。 */
function usedWithoutFallback(files) {
  const hits = new Map()
  for (const file of files) {
    const text = stripComments(readFileSync(file, 'utf8'))
    text.split('\n').forEach((line, index) => {
      for (const m of line.matchAll(USED)) {
        const [, token, rest] = m
        if (rest.includes(',')) continue // 有 fallback，没定义也能用
        if (!hits.has(token)) hits.set(token, [])
        hits.get(token).push(`${file.replace(SRC, 'src')}:${index + 1}`)
      }
    })
  }
  return hits
}

function definedTokens(files) {
  const set = new Set()
  for (const file of files) {
    const text = stripComments(readFileSync(file, 'utf8'))
    for (const m of text.matchAll(DEFINED)) set.add(m[1])
  }
  return set
}

describe('CSS token 体检', () => {
  it('⭐ 没有"用了但没定义"的 token（会让整条声明静默失效）', () => {
    const files = walk(SRC)
    const defined = definedTokens(files)
    const used = usedWithoutFallback(files)

    const undefinedOnes = [...used.keys()].filter((token) => !defined.has(token))
    const report = undefinedOnes
      .map((token) => `  ${token} ← ${used.get(token).slice(0, 4).join('、')}`)
      .join('\n')

    expect(
      undefinedOnes,
      `以下 token 被使用但从未定义（整条声明会静默失效）：\n${report}`,
    ).toEqual([])
  })

  it('间距 token 就是设计规范 §4.1 的 7 级（别偷偷加第 8 级）', () => {
    // 这条把"间距只有 7 级"钉住：想加第 8 级，得先改规范，而不是顺手写个 --sp-8
    const css = readFileSync(resolve(SRC, 'style.css'), 'utf8')
    const defined = new Set([...css.matchAll(DEFINED)].map((m) => m[1]))
    for (let level = 1; level <= 7; level += 1) {
      expect(defined.has(`--sp-${level}`), `缺 --sp-${level}`).toBe(true)
    }
    expect(defined.has('--sp-8'), '规范是 7 级，不该出现 --sp-8').toBe(false)
  })
})
