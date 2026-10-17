/**
 * C3：目录从平铺变树（`src/tocTree.js` + `useReader.tocItems` + `ReadView.vue` 的两种渲染分支）。
 *
 * 三层判据，缺一层都不算验过：
 * 1. **纯函数**（`buildTocTree`）：分层 / 跳级 / 缺 level / 坏形状 —— 不挂组件也能钉死；
 * 2. **store**（`tocItems`）：有结构用结构、没有就**退回平铺**（不是空屏）、文字与页码仍取自块；
 * 3. **模板源码**：`block_id` 为 null 的那一条**不是 button、没有 @click**（死链不许做成活链样式）。
 *
 * ⚠️ store 是模块级单例：每个用例自己摆好 `currentTask` / `blocks`，跑完复位（vitest 默认
 * 每个测试文件一份模块注册表，但同文件内仍要自己清）。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

import { buildTocTree, normalizeLevel } from '../src/tocTree.js'
import * as reader from '../src/stores/useReader.js'

// ⚠️ 用 `resolve(process.cwd(), …)` 而不是 `new URL(rel, import.meta.url)`：
// happy-dom 里 `import.meta.url` 不是 `file:` URL，会抛（坑见 `app.smoke.test.js` / `block-edit.test.js`）。
const readSrc = (rel) => readFileSync(resolve(process.cwd(), rel), 'utf8')

/** 一条块（`buildParagraphRows` 按 `p<页>_b<序>` 推页号，所以 id 必须是这个形状）。 */
const blockOf = (blockId, type, text, translated) => ({
  block_id: blockId,
  type,
  text,
  translated,
  status: 'success',
  error: null,
})

/** 平铺目录那条路要用的块：两个标题 + 一个正文。 */
const flatBlocks = [
  blockOf('p0_b0', 'title', 'Solving Linear Systems', '求解线性方程组'),
  blockOf('p0_b1', 'heading', '1 Introduction', '1 引言'),
  blockOf('p0_b2', 'body', 'We give an algorithm.', '我们给出一个算法。'),
  blockOf('p1_b0', 'heading', '2 Methods', '2 方法'),
]

afterEach(() => {
  reader.currentTask.value = null
  reader.blocks.value = []
})

describe('C3 纯函数：结构 → 扁平带深度', () => {
  it('正常四级：depth 逐级递增（1→2→3→4 得 0,1,2,3）', () => {
    const tree = buildTocTree([
      { block_id: 'p0_b0', level: 1, text: '一、引言' },
      { block_id: 'p0_b1', level: 2, text: '1.1 背景' },
      { block_id: 'p0_b2', level: 3, text: '1.1.1 细节' },
      { block_id: 'p0_b3', level: 4, text: '1.1.1.1 更细' },
    ])
    expect(tree.map((item) => item.depth)).toEqual([0, 1, 2, 3])
    expect(tree.map((item) => item.level)).toEqual([1, 2, 3, 4])
  })

  it('⭐ 跳级（1→3，中间没有 2）：挂在前面最近的更浅一层下面，不凭空造中间节点', () => {
    const tree = buildTocTree([
      { block_id: 'p0_b0', level: 1, text: '一、总论' },
      { block_id: 'p0_b1', level: 3, text: '1.1.1 跳级来的' },
      { block_id: 'p0_b2', level: 1, text: '二、方法' },
    ])
    expect(tree.map((item) => item.depth)).toEqual([0, 1, 0])
    // 三条就是三条——没有为了"补齐 2 级"多出任何节点
    expect(tree).toHaveLength(3)
  })

  it('回退层级（1→2→1→2）：第二次的 depth 回到 1，不继续往深里走', () => {
    const tree = buildTocTree([
      { level: 1, text: 'A' },
      { level: 2, text: 'A-1' },
      { level: 1, text: 'B' },
      { level: 2, text: 'B-1' },
    ])
    expect(tree.map((item) => item.depth)).toEqual([0, 1, 0, 1])
  })

  it('level 缺失 / 越界 / 非整数 → 一律按 1（顶层）照实降级，不崩', () => {
    expect([null, undefined, 0, -1, 9, 2.5, 'x', ''].map(normalizeLevel)).toEqual([
      1, 1, 1, 1, 1, 1, 1, 1,
    ])
    const tree = buildTocTree([
      { text: '没有 level' },
      { level: 9, text: '超过上限' },
      { level: 2.5, text: '不是整数' },
      { level: '2', text: '字符串数字（合法，按 2 算）' },
    ])
    expect(tree.map((item) => item.depth)).toEqual([0, 0, 0, 1])
  })

  it('block_id 缺失 / 不是字符串 → blockId 为 null（照实显示、不可点，由模板负责）', () => {
    const tree = buildTocTree([
      { level: 1, text: '有块号', block_id: 'p0_b1' },
      { level: 1, text: '没块号' },
      { level: 1, text: '块号是空串', block_id: '' },
      { level: 1, text: '块号不是字符串', block_id: 7 },
    ])
    expect(tree.map((item) => item.blockId)).toEqual(['p0_b1', null, null, null])
  })

  it('坏形状一律回空数组（调用方据此退回平铺）：非数组 / 空文本 / 全是垃圾', () => {
    expect(buildTocTree(null)).toEqual([])
    expect(buildTocTree('headings')).toEqual([])
    expect(buildTocTree({})).toEqual([])
    expect(buildTocTree([null, 7, 'x', {}])).toEqual([])
    expect(buildTocTree([{ level: 1, text: '   ' }])).toEqual([])
  })
})

describe('C3 store：有结构用结构，没有就退回平铺（不是空屏）', () => {
  it('⭐ 有结构：层级来自结构，**文字与页码仍取自块**（中文译名 + 第几页）', () => {
    reader.blocks.value = flatBlocks
    reader.currentTask.value = {
      structure: {
        headings: [
          { block_id: 'p1_b0', level: 1, text: '2 Methods' },
          { block_id: 'p0_b1', level: 2, text: '1 Introduction' },
          { block_id: 'p1_b1', level: 1, text: 'References' }, // 对不上任何块
        ],
      },
    }
    const items = reader.tocItems.value
    expect(items.map((item) => item.depth)).toEqual([0, 1, 0])
    // 顺序跟着**结构**走（raw 的第一个是 p1_b0，不是平铺那条按页排的）
    expect(items[0].blockId).toBe('p1_b0')
    expect(items[0].text).toBe('2 方法') // 中文译名，取自块
    expect(items[0].page).toBe(1) // p1_b0 → 第 2 页（模板里 +1）
    expect(items[1].text).toBe('1 引言')
    expect(items[1].page).toBe(0) // p0_b1 → 第 1 页
    // 对不上的那条：照实显示结构自己的文字，但**页码留空**（不编）
    expect(items[2].blockId).toBe('p1_b1')
    expect(items[2].text).toBe('References')
    expect(items[2].page).toBe(null)
  })

  it('没有 structure（老任务 / 扫描件）→ 退回平铺目录，depth 全 0，一条都不少', () => {
    reader.blocks.value = flatBlocks
    reader.currentTask.value = {}
    const items = reader.tocItems.value
    expect(items.map((item) => item.text)).toEqual(['求解线性方程组', '1 引言', '2 方法'])
    expect(items.every((item) => item.depth === 0)).toBe(true)
    expect(items.every((item) => typeof item.blockId === 'string')).toBe(true)
  })

  it('structure 坏形状 / 一条都产不出来 → 也是退回平铺（绝不空屏）', () => {
    reader.blocks.value = flatBlocks
    for (const bad of [
      { structure: 'nope' },
      { structure: { headings: 'nope' } },
      { structure: { headings: [] } },
      { structure: { headings: [{ level: 1, text: '   ' }] } },
    ]) {
      reader.currentTask.value = bad
      expect(reader.tocItems.value.map((item) => item.text)).toEqual([
        '求解线性方程组',
        '1 引言',
        '2 方法',
      ])
    }
  })

  it('少于 3 条仍然整条不渲染（那条既有口径对两条路都成立）', () => {
    reader.blocks.value = [flatBlocks[0]]
    reader.currentTask.value = {}
    expect(reader.tocItems.value).toHaveLength(1)
    expect(reader.showOutline.value).toBe(false)

    reader.currentTask.value = {
      structure: { headings: [{ level: 1, text: '只有一条' }] },
    }
    expect(reader.tocItems.value).toHaveLength(1)
    expect(reader.showOutline.value).toBe(false)
  })
})

describe('C3 模板源码：不可点的条目不许做成活链样式', () => {
  const view = readSrc('src/views/ReadView.vue')
  const css = readSrc('src/style.css')

  it('两个目录渲染点都绑了 --toc-depth（层级靠缩进表达）', () => {
    const binds = view.match(/--toc-depth/g) || []
    expect(binds.length).toBe(2)
  })

  it('⭐ block_id 为 null 的那一支是 span 而不是 button，且没有 @click', () => {
    const at = view.indexOf('toc-item-static')
    expect(at).toBeGreaterThan(-1)
    // 该条目的**开始标签**：从它前面最近的一个 `<span` 到它的 `>`
    const tagStart = view.lastIndexOf('<span', at)
    const tag = view.slice(tagStart, view.indexOf('>', at) + 1)
    expect(tag).toContain('toc-item-static')
    expect(tag).not.toContain('@click')
    expect(tag).not.toContain('<button')
    // 它必须是 v-else 那一支（前面紧邻的是 v-else，而不是 v-if）
    const before = view.slice(Math.max(0, at - 160), at)
    expect(before).toContain('v-else')
    // 可点那一支仍然必须是 button（别把两条路都做成 span）
    expect(view).toMatch(/<button\s+v-if="item\.blockId"/)
  })

  it('样式里给了 [C3] 段，并显式复位不可点条目的 hover 强调', () => {
    expect(css).toContain('[C3] 目录变树')
    expect(css).toMatch(/\.dw \.toc-item-static\s*\{[^}]*cursor:\s*default/)
    expect(css).toMatch(/\.dw \.toc-item-static:hover\s*\{[^}]*background:\s*none/)
    expect(css).toMatch(/\.dw \.toc-list > li\s*\{[^}]*var\(--toc-depth/)
  })

  it('⭐ 缩进必须与变量绑在**同一个元素**上（否则数据是树、看着还是平铺）', () => {
    // 变量绑在 <li> 上（模板），缩进就必须写在 `li` 上。
    // 实测教训：有人会去量**子元素** `.toc-item` 的 padding-left —— 那是它自己的行内留白
    // （`.dw .toc-item { padding: 5px 12px }`），**不是**层级缩进；缩进在父 `li` 的 padding 上，
    // 表现为子元素的**水平偏移**。搞混这两者就会得出"缩进没生效"的错误结论。
    const at = view.indexOf('v-for="(item, index) in tocItems"')
    expect(at).toBeGreaterThan(-1)
    const liStart = view.lastIndexOf('<li', at)
    const liTag = view.slice(liStart, view.indexOf('>', at) + 1)
    expect(liTag).toContain('--toc-depth')

    // 缩进规则落在 `li` 上……
    expect(css).toMatch(/\.dw \.toc-list > li\s*\{[^}]*padding-left:\s*calc\(var\(--toc-depth/)
    // ……而且**不许**落到子元素 `.toc-item` 上（那就是把行内留白当层级用）
    expect(css).not.toMatch(/\.dw \.toc-item\s*\{[^}]*var\(--toc-depth/)
  })

  it('⭐ 桌面档缩进规则必须在**顶层**（上一轮真踩过：少一个 } 把整段吞进手机档媒体查询）', () => {
    // happy-dom 不会真的应用外部样式表，所以"断言计算后的 padding"是假的；
    // 能做的最强源码级守卫是：**在桌面档那条规则的位置上，花括号深度必须是 0**
    // —— 深度为 1 就说明它落在某个没闭合的 `@media` 里（桌面档下一条都不生效，且 vitest/build 都不报）。
    const at = css.indexOf('.dw .toc-list > li { padding-left: calc(var(--toc-depth, 0) * 14px)')
    expect(at).toBeGreaterThan(-1)
    const before = css.slice(0, at).replace(/\/\*[\s\S]*?\*\//g, '')
    let depth = 0
    for (const ch of before) {
      if (ch === '{') depth += 1
      else if (ch === '}') depth -= 1
    }
    expect(depth).toBe(0)
  })
})
