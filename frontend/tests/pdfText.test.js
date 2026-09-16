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
  buildParagraphs,
  contextAround,
  findInPage,
  findTextInPages,
  overlapsVertically,
  paragraphOf,
  pdfNormalize,
  sameColumn,
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

  it('同一基线上横向离很远的条目**不**并成一行（双栏不会粘成一行）', () => {
    // 左栏和右栏恰好落在同一条基线上：距 170，行高 10 → 远超 2 倍行高
    const lines = buildLines([box('左栏的一段话', 10, 100, 60), box('右栏的另一段', 300, 100, 72)])
    expect(lines.length).toBe(2)
    expect(lines[0].norm).toBe('左栏的一段话')
    expect(lines[1].norm).toBe('右栏的另一段')
  })

  it('同一行内挨着的条目照旧并成一行（阈值不会误伤正常行）', () => {
    const lines = buildLines([box('hello ', 10, 100, 36), box('world', 50, 100, 30)])
    expect(lines.length).toBe(1)
    expect(lines[0].norm).toBe('hello world')
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

  it('整段能对上（忽略行断点与连字符换行造成的空格差异），高亮**对上的那几行**', () => {
    const hit = findTextInPages(
      [pageOne, pageTwo],
      'aw firms are rapidly integrating artificial intelligence (AI) into workflows',
    )
    expect(hit).not.toBeNull()
    expect(hit.page).toBe(1)
    // 对上的就是前两行，合成一块（**不扩成整段**：扩了的话按行切的块会全都亮同一个框）
    expect(hit.from).toBe(0)
    expect(hit.to).toBe(1)
    expect(hit.rects.length).toBe(1)
    expect(hit.text).toContain('intelligence (ai) into workflows')
    expect(hit.text).not.toContain('denced by an article')
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

describe('pdfText：行 → 段', () => {
  it('段内的行并成一段（行距 14.7 / 行高 10.5，取真实产物的数）', () => {
    const paragraphs = buildParagraphs([
      { rect: { x: 10, y: 100, w: 200, h: 10 }, norm: 'first line', squash: 'firstline' },
      { rect: { x: 10, y: 114.7, w: 200, h: 10 }, norm: 'second line', squash: 'secondline' },
    ])
    expect(paragraphs.length).toBe(1)
    expect(paragraphs[0].text).toBe('first line second line')
  })

  it('段间的行**不**并（真实产物段间距 ≥25.3，是段内的 1.7 倍）', () => {
    const paragraphs = buildParagraphs([
      { rect: { x: 10, y: 100, w: 200, h: 10 }, norm: 'tail of paragraph one', squash: 'tailofparagraphone' },
      { rect: { x: 10, y: 125.3, w: 200, h: 10 }, norm: 'head of paragraph two', squash: 'headofparagraphtwo' },
    ])
    expect(paragraphs.length).toBe(2)
  })

  it('双栏里同一高度、不同栏的两行**不**并成一段（横向不重叠）', () => {
    const paragraphs = buildParagraphs([
      { rect: { x: 10, y: 100, w: 200, h: 10 }, norm: 'left column line', squash: 'leftcolumnline' },
      { rect: { x: 260, y: 100, w: 200, h: 10 }, norm: 'right column line', squash: 'rightcolumnline' },
    ])
    expect(paragraphs.length).toBe(2)
  })

  it('段的框 = 段内所有行的并集；段按阅读顺序（先上后下、再左后右）排', () => {
    const paragraphs = buildParagraphs([
      { rect: { x: 260, y: 100, w: 100, h: 10 }, norm: 'right', squash: 'right' },
      { rect: { x: 10, y: 100, w: 100, h: 10 }, norm: 'left', squash: 'left' },
      { rect: { x: 10, y: 114.7, w: 100, h: 10 }, norm: 'left2', squash: 'left2' },
    ])
    expect(paragraphs.map((p) => p.text)).toEqual(['left left2', 'right'])
    const box = paragraphs[0].rect
    expect(box.x).toBe(10)
    expect(box.w).toBe(100)
    expect(Math.round(box.h)).toBe(25)
  })

  it('按行切的块：三个块各亮各自那一行，不再全都扩成同一段', () => {
    // 中文文献的真实形态：取字是按行切块的（第 3 页 29 个块，每块一行）
    const lines = buildLines([
      box('研究分别从农产品营销、广告营销等垂直场景切入，分析了AIGC 赋能特定行业的模式与挑战。此', 10, 300, 500),
      box('外，相关研究关注AI 生成内容的负面效应，指出算法操纵、数据安全与内容真实性等伦理风险。', 10, 285.3, 500),
      box('[6]。然而，上述研究多聚焦于特定场景或单一问题维度，尚缺乏系统性理论分析。', 10, 270.6, 500),
    ])
    const index = buildPageIndex(lines, 3)
    const a = findTextInPages([index], '研究分别从农产品营销、广告营销等垂直场景切入')
    const b = findTextInPages([index], '外，相关研究关注AI 生成内容的负面效应')
    const c = findTextInPages([index], '[6]。然而，上述研究多聚焦于特定场景')
    expect(a.from).toBe(0)
    expect(b.from).toBe(1)
    expect(c.from).toBe(2)
    // 各自只亮一行，且三行的框不一样（以前会全扩到同一段，三个框完全一样）
    expect(a.rects.length).toBe(1)
    expect(b.rects.length).toBe(1)
    expect(c.rects.length).toBe(1)
    expect(a.rects[0].y).not.toBe(b.rects[0].y)
    expect(b.rects[0].y).not.toBe(c.rects[0].y)
  })

  it('跨行命中要合并成一块（不是一排带缝的条）', () => {
    const lines = buildLines([
      box('第一行的文字到这', 10, 300, 100),
      box('里还没说完，继续往下走', 10, 285.3, 130),
    ])
    const hit = findTextInPages([buildPageIndex(lines, 1)], '第一行的文字到这里还没说完')
    expect(hit.rects.length).toBe(1)
    expect(hit.rects[0].h).toBeGreaterThan(20)
  })
})

describe('pdfText：同栏判断（只按上下位置会框到另一栏去）', () => {
  const right = { x: 319, y: 546, w: 270, h: 212 }

  it('右栏段落 vs 同高度的左栏段落：不同栏', () => {
    const left = { x: 141, y: 546, w: 153, h: 90 }
    expect(overlapsVertically(right, left)).toBe(true) // 上下确实重叠——所以只看 y 就会误框
    expect(sameColumn(right, left)).toBe(false)
  })

  it('同一栏、高度也重叠：同一栏', () => {
    const same = { x: 319, y: 560, w: 274, h: 180 }
    expect(sameColumn(right, same)).toBe(true)
  })

  it('真实数据的两个数：右栏 x 比 1.00、左栏 0.00（阈值 0.3 卡得开）', () => {
    expect(sameColumn({ x: 319, y: 546, w: 270, h: 212 }, { x: 319, y: 560, w: 274, h: 200 })).toBe(true)
    expect(sameColumn({ x: 319, y: 546, w: 270, h: 212 }, { x: 144, y: 700, w: 137, h: 20 })).toBe(false)
  })
})

describe('pdfText：单页索引', () => {
  it('owners 记录每个字符属于哪一行', () => {
    const index = buildPageIndex(buildLines([box('ab', 0, 100), box('cd', 0, 80)]), 1)
    expect(index.flat).toBe('abcd')
    expect(index.owners).toEqual([0, 0, 1, 1])
    expect(findInPage(index, 'bc')).toMatchObject({ from: 0, to: 1 })
  })
})
