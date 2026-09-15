/**
 * pdfText.js 的单测：PDF 文字层的"行合并 / 归一化 / 按文本找位置"。
 *
 * 这一层锁的是**对齐**——块文本 ↔ PDF 文字层。它错了界面不会崩，
 * 只会"高亮打到不相干的地方"或者"明明有却说没找到"，正是最需要单测的那种错。
 * 条目数据取自真实引擎产物的形态（pdf.js 的 getTextContent 条目 + 视口坐标换算后的结果）。
 */
import { describe, expect, it } from 'vitest'

import {
  buildLines,
  buildPageIndex,
  contextAround,
  findInPage,
  findTextInPages,
  hitLine,
  pdfNormalize,
  squash,
} from '../src/pdfText'

/** 造一条文本条目：x/y/w/h 是"视口坐标"（y 是基线）。 */
function box(text, x, y, w = text.length * 6, h = 10) {
  return { text, x, y, w, h }
}

describe('pdfText：归一化', () => {
  it('NFKC + 折叠空白 + 小写（CJK 兼容汉字必须归一化，否则静默失配）', () => {
    expect(pdfNormalize('  Hello   World \n')).toBe('hello world')
    // U+F900 兼容汉字 → NFKC 后变成 U+8C48
    expect(pdfNormalize('\uf900')).toBe('豈')
    expect(squash('第 1 页 · 第 2 段')).toBe('第1页·第2段')
  })
})

describe('pdfText：条目 → 行', () => {
  it('同一基线的条目并成一行，行内按 x 排序', () => {
    const lines = buildLines([box('world', 60, 100), box('hello ', 10, 100)])
    expect(lines.length).toBe(1)
    expect(lines[0].norm).toBe('hello world')
    // 行框 = 行内所有条目的并集：10 → 90
    expect(lines[0].rect.x).toBe(10)
    expect(lines[0].rect.w).toBe(80)
  })

  it('基线差超过半个字高就断成两行（上下行不会被粘在一起）', () => {
    const lines = buildLines([box('first line', 10, 100), box('second line', 10, 86)])
    expect(lines.map((l) => l.norm)).toEqual(['first line', 'second line'])
  })

  it('空条目直接丢掉，不留空行', () => {
    const lines = buildLines([box('   ', 10, 100), box('real', 10, 100)])
    expect(lines.length).toBe(1)
    expect(lines[0].norm).toBe('real')
  })
})

describe('pdfText：按文本找位置', () => {
  const pageOne = buildPageIndex(
    buildLines([
      box('aw firms are rapidly integrating artificial', 10, 700),
      box('intelligence (AI) into workflows, as evi-', 10, 686),
      box('denced by an article by Melissa Kock', 10, 672),
    ]),
    1,
  )
  const pageTwo = buildPageIndex(buildLines([box('Moving beyond', 10, 700)]), 2)

  it('整段能对上（忽略行断点与连字符换行造成的空格差异）', () => {
    const hit = findTextInPages(
      [pageOne, pageTwo],
      'aw firms are rapidly integrating artificial intelligence (AI) into workflows',
    )
    expect(hit).not.toBeNull()
    expect(hit.page).toBe(1)
    // 命中的是前两行
    expect(hit.from).toBe(0)
    expect(hit.to).toBe(1)
    expect(hit.rects.length).toBe(2)
    expect(hit.exact).toBe(true)
  })

  it('整段对不上时退到短前缀，但不会短到乱命中', () => {
    // 尾部和 PDF 里不一样（引擎抽出来的文本常有这种尾巴差异）
    const hit = findTextInPages([pageOne], 'Moving beyond transactions and into the field')
    expect(hit).toBeNull() // 第 2 页没有 -> 不许在第 1 页乱高亮

    const tail = findTextInPages([pageOne], 'aw firms are rapidly integrating artificial intelligence!')
    expect(tail.page).toBe(1)
    expect(tail.exact).toBe(false)
  })

  it('跨页找：第 1 页没有就去第 2 页', () => {
    const hit = findTextInPages([pageOne, pageTwo], 'Moving beyond')
    expect(hit.page).toBe(2)
  })

  it('找不到就返回 null（调用方必须如实说"没找到"，不许假高亮）', () => {
    expect(findTextInPages([pageOne], '完全不在这一页里的一句话')).toBeNull()
  })

  it('纯中文稿那种情况：块里是英文、PDF 里是中文 → 对不上', () => {
    const chinese = buildPageIndex(buildLines([box('律师事务所正迅速将人工智能（AI）引入工作流', 10, 700)]), 1)
    expect(findTextInPages([chinese], 'aw firms are rapidly integrating artificial intelligence')).toBeNull()
  })

  it('命中点上下文取前后各一行（给"这段在讲什么"当提示）', () => {
    expect(contextAround(pageOne, 1, 1)).toBe(
      'aw firms are rapidly integrating artificial intelligence (ai) into workflows, as evi- denced by an article by melissa kock',
    )
    // 命中第一行时没有"上一行"，只往下取
    expect(contextAround(pageOne, 0, 0)).toBe(
      'aw firms are rapidly integrating artificial intelligence (ai) into workflows, as evi-',
    )
  })})

describe('pdfText：点一下落在哪一行', () => {
  const lines = buildLines([box('first', 10, 100), box('second', 10, 80)])

  it('落在行框里就命中那一行', () => {
    expect(hitLine(lines, 20, 96)).toBe(0)
    expect(hitLine(lines, 20, 76)).toBe(1)
  })

  it('点在行外返回 -1（别把空白处的点击当成某一段）', () => {
    expect(hitLine(lines, 400, 96)).toBe(-1)
  })
})

describe('pdfText：单页索引', () => {
  it('owners 记录每个字符属于哪一行', () => {
    const index = buildPageIndex(buildLines([box('ab', 0, 100), box('cd', 0, 80)]), 1)
    expect(index.flat).toBe('abcd')
    expect(index.owners).toEqual([0, 0, 1, 1])
    expect(findInPage(index, 'bc')).toEqual({ from: 0, to: 1 })
  })
})
