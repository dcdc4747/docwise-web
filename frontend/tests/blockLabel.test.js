/**
 * 出处人话化 / 术语定位 的纯函数单测。
 *
 * 这些断言锁的是形态里的硬约定：
 * - 段号必须**按页内重算**（块编号里的 b 是全文档全局序号）；
 * - 解析不出、或块不在本任务里 → 返回空串（调用方显示"位置待定"），不许裸露块编号；
 * - 文本比较前必须 NFKC（译稿里真实存在 U+F900–FAFF 的兼容汉字）。
 */

import { describe, expect, it } from 'vitest'

import { blockLabel, findBlockByText, normalizeText, parseBlockId } from '../src/blockLabel'

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

describe('blockLabel', () => {
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
