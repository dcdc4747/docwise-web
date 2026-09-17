/**
 * 出处人话化 / 术语定位 的纯函数单测。
 *
 * 这些断言锁的是形态里的硬约定：
 * - **出处只说「第 X 页 ·「这一句的开头…」」，不说第几段**（段号实测不准，见
 *   `temp/seg-audit/审查结论_汇总.md`；不准的段号比没有更糟，用户会拿它去数）；
 * - 块**必须真的在本任务的块列表里** → 否则返回空串（调用方显示"位置待定"），
 *   模型编出来的块编号绝不许给页码；不许裸露块编号；
 * - 文本比较前必须 NFKC（译稿里真实存在 U+F900–FAFF 的兼容汉字）；
 * - `blockLabel`（带段号那个）留着不删：它锁住了"b 是全文档全局序号、段号必须按页内重算"
 *   这条真教训，将来段落切分做到可信了再接回来。
 */

import { describe, expect, it } from 'vitest'

import {
  blockLabel,
  buildParagraphRows,
  findBlockByText,
  normalizeText,
  pageLabel,
  parseBlockId,
  sourceLabel,
} from '../src/blockLabel'

describe('parseBlockId', () => {
  it('解析 p<页>_b<全局块序>', () => {
    expect(parseBlockId('p0_b0')).toEqual({ page: 0, index: 0 })
    expect(parseBlockId('p2_b91')).toEqual({ page: 2, index: 91 })
  })

  it('不是这个格式就返回 null（别硬猜）', () => {
    expect(parseBlockId('b1')).toBeNull()
    expect(parseBlockId('')).toBeNull()
    expect(parseBlockId(null)).toBeNull()
  })
})

describe('sourceLabel / pageLabel（出处只说页码 + 那一句的开头）', () => {
  const blocks = [
    { block_id: 'p0_b0', text: '第一段的第一句话，后面还有很多字用来验证截断。' },
    { block_id: 'p0_b1', text: '第二段的开头。' },
    { block_id: 'p1_b2', text: 'another sentence here' },
  ]

  it('页码从 1 数起', () => {
    expect(pageLabel('p0_b0')).toBe('第 1 页')
    expect(pageLabel('p1_b2')).toBe('第 2 页')
  })

  it('标签 = 页码 + 那一句的开头（超过 12 字截断加省略号）', () => {
    expect(sourceLabel('p0_b1', blocks)).toBe('第 1 页 ·「第二段的开头。」')
    expect(sourceLabel('p0_b0', blocks)).toBe('第 1 页 ·「第一段的第一句话，后面还…」')
    expect(sourceLabel('p1_b2', blocks)).toBe('第 2 页 ·「another sent…」')
  })

  it('**块不在本任务里 → 空串**：模型编出来的块编号绝不许给页码', () => {
    expect(sourceLabel('p9_b99', blocks)).toBe('')
    expect(sourceLabel('p0_b7', blocks)).toBe('')
  })

  it('块列表还没加载 → 也当推导不出（等加载完自然会填上）', () => {
    expect(sourceLabel('p0_b0', [])).toBe('')
  })

  it('编号格式不对 → 空串，不裸露编号', () => {
    expect(sourceLabel('b1', blocks)).toBe('')
    expect(sourceLabel(undefined, blocks)).toBe('')
  })

  it('同一页的两个出处，标签不一样（靠开头那句区分）', () => {
    expect(sourceLabel('p0_b0', blocks)).not.toBe(sourceLabel('p0_b1', blocks))
  })
})

describe('blockLabel（带段号的旧口径，界面上已不用，留着锁住那条教训）', () => {
  const order = ['p0_b0', 'p0_b1', 'p0_b2', 'p1_b3', 'p1_b4', 'p2_b91']

  it('页号从 1 数起，段号按页内重算', () => {
    expect(blockLabel('p0_b0', order)).toBe('第 1 页 · 第 1 段')
    expect(blockLabel('p0_b2', order)).toBe('第 1 页 · 第 3 段')
    // 关键：p1_b3 的全局块序是 3，但它是第 2 页的第 1 段
    expect(blockLabel('p1_b3', order)).toBe('第 2 页 · 第 1 段')
    // 实测里真出现过 p2_b91 这种"全局第 92 块"，绝不能显示成"第 92 段"
    expect(blockLabel('p2_b91', order)).toBe('第 3 页 · 第 1 段')
  })

  it('不在本任务块列表里 → 空串（调用方显示"位置待定"）', () => {
    expect(blockLabel('p9_b9', order)).toBe('')
  })

  it('格式不对 → 空串，不裸露编号', () => {
    expect(blockLabel('b1', order)).toBe('')
    expect(blockLabel(undefined, order)).toBe('')
  })

  it('块列表缺失时不炸', () => {
    expect(blockLabel('p0_b0', undefined)).toBe('')
    expect(blockLabel('p0_b0', [])).toBe('')
  })
})

describe('normalizeText / findBlockByText', () => {
  // 真实场景：译稿 PDF 的文字层里是**兼容汉字**（U+F9D8 长得跟"律"一模一样），
  // 而用户输入 / 术语表里是普通汉字 —— 不做 NFKC 就是静默失配（实测 search_for 命中 1 → 0）。
  const COMPAT_LU = '\uF9D8'
  const blocks = [
    { block_id: 'p0_b0', text: `L ${COMPAT_LU}师事务所正迅速将人工智能融入工作流程`, translated: null },
    { block_id: 'p0_b1', text: 'Retrieval-Augmented Translation for Academic Reading', translated: null },
  ]

  it('NFKC 归一化：兼容汉字与正常汉字归一后可比', () => {
    expect(COMPAT_LU).not.toBe('律') // 先证明它俩确实不是一个字符
    expect(normalizeText(`${COMPAT_LU}师`)).toBe(normalizeText('律师'))
  })

  it('按译名/原文找块（大小写与兼容字都不影响）', () => {
    expect(findBlockByText('retrieval-augmented', blocks)?.block_id).toBe('p0_b1')
    // 用普通码位的"律师"去命中含兼容汉字的块（这就是 NFKC 存在的理由）
    expect(findBlockByText('律师事务所', blocks)?.block_id).toBe('p0_b0')
  })

  it('找不到就返回 null（由调用方直说"没找到"，不预填假坐标）', () => {
    expect(findBlockByText('实地研究', blocks)).toBeNull()
    expect(findBlockByText('', blocks)).toBeNull()
    expect(findBlockByText('随便什么', undefined)).toBeNull()
  })
})

describe('buildParagraphRows（段落精读的行）', () => {
  const blocks = [
    { block_id: 'p0_b0', text: 'a', translated: '甲' },
    { block_id: 'p0_b1', text: 'b', translated: '乙' },
    { block_id: 'p1_b2', text: 'c', translated: '丙' },
    { block_id: 'p1_b3', text: 'd', translated: '丁' },
    { block_id: 'p2_b91', text: 'e', translated: '戊' },
  ]

  it('每翻一页插一条页分隔，段号页内从 1 数起', () => {
    const rows = buildParagraphRows(blocks)
    expect(rows.map((row) => row.kind)).toEqual([
      'page', 'block', 'block', 'page', 'block', 'block', 'page', 'block',
    ])
    const pageLabels = rows.filter((r) => r.kind === 'page').map((r) => r.label)
    expect(pageLabels).toEqual(['第 1 页', '第 2 页', '第 3 页'])
    const blockLabels = rows.filter((r) => r.kind === 'block').map((r) => r.label)
    // 关键：p1_b2 是"第 2 页第 1 段"，p2_b91 是"第 3 页第 1 段"——都不是全局序号
    expect(blockLabels).toEqual(['段 1', '段 2', '段 1', '段 2', '段 1'])
  })

  it('块编号不合格式时不炸，也不瞎标段号', () => {
    const rows = buildParagraphRows([{ block_id: 'weird', text: 'x', translated: null }])
    expect(rows).toHaveLength(1)
    expect(rows[0].kind).toBe('block')
    expect(rows[0].label).toBe('')
    expect(rows[0].page).toBeNull()
  })

  it('空列表 → 空行', () => {
    expect(buildParagraphRows([])).toEqual([])
    expect(buildParagraphRows(undefined)).toEqual([])
  })
})
