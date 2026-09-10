/**
 * 诚实进度文案的单测（F 批）。
 *
 * 这里只测"事实怎么变成人话"，不碰网络与组件；模板渲染另有 app.smoke.test.js 兜底。
 */

import { describe, expect, it } from 'vitest'

import {
  elapsedTextFor,
  engineText,
  etaTextFor,
  formatDuration,
  queueText,
  stageTextFor,
} from '../src/progressText'

const running = { status: 'in_progress' }

describe('阶段文字', () => {
  it('排队中：有位置就说前面还有几篇', () => {
    expect(queueText({ status: 'pending', queue_position: 2 })).toBe(
      '排队中 · 前面还有 2 篇',
    )
    expect(queueText({ status: 'pending', queue_position: 0 })).toBe('排队中')
  })

  it('翻译中但引擎还没报进度：说"还没报进度"，不编百分比', () => {
    expect(stageTextFor(running, null)).toBe('正在翻译 · 引擎还没报进度')
  })

  it('引擎报的页数一律标"引擎自报"（它可能十几秒不更新一次，不是我们的承诺）', () => {
    expect(
      engineText({ done: 2, total: 5, percent: 0.4, rate: 1.72 }),
    ).toBe('引擎自报：第 2/5 页 · 1.72 页/秒')
    expect(engineText({ done: 2, total: 5, rate: null })).toBe('引擎自报：第 2/5 页')
  })

  it('有引擎进度时阶段行只说"正在翻译"（页数单独一行，不混着说）', () => {
    expect(stageTextFor(running, { done: 2, total: 5, rate: 1.72 })).toBe('正在翻译')
  })

  it('各终态各说各的（已取消 ≠ 失败）', () => {
    expect(stageTextFor({ status: 'completed' }, null)).toBe('翻译完成')
    expect(stageTextFor({ status: 'cancelled' }, null)).toBe('已取消')
    expect(stageTextFor({ status: 'failed' }, null)).toBe('翻译失败')
    expect(stageTextFor(null, null)).toBe('')
  })

  it('引擎进度字段不完整时当作没报（不显示半截数字）', () => {
    expect(engineText({ done: 2 })).toBeNull()
    expect(engineText({ done: 2, total: 0 })).toBeNull()
    expect(engineText(null)).toBeNull()
  })
})

describe('耗时文案', () => {
  it('跑着叫"已用"，结束叫"总耗时"', () => {
    expect(elapsedTextFor(running, 12)).toBe('已用 12 秒')
    expect(elapsedTextFor({ status: 'completed' }, 9.4)).toBe('总耗时 9 秒')
  })

  it('刚点下去不显示"已用 0 秒"', () => {
    expect(elapsedTextFor(running, 0)).toBe('')
    expect(elapsedTextFor(running, 0.4)).toBe('')
    expect(elapsedTextFor(running, 1)).toBe('已用 1 秒')
  })

  it('已取消/失败的任务没耗时就不显示', () => {
    expect(elapsedTextFor({ status: 'cancelled' }, 0)).toBe('')
    expect(elapsedTextFor({ status: 'failed' }, null)).toBe('')
  })

  it('超过一分钟说成人话', () => {
    expect(formatDuration(59)).toBe('59 秒')
    expect(formatDuration(60)).toBe('1 分 0 秒')
    expect(formatDuration(125)).toBe('2 分 5 秒')
  })
})

describe('预计剩余', () => {
  it('只有跑着、且是正数才显示（且标着引擎自报）', () => {
    expect(etaTextFor(running, 25)).toBe('引擎自报还需 25 秒')
    expect(etaTextFor(running, 0)).toBe('') // tqdm 四舍五入到 0，不是"马上好"
    expect(etaTextFor(running, null)).toBe('')
    expect(etaTextFor({ status: 'completed' }, 25)).toBe('')
  })
})
