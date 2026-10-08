/**
 * 诚实进度文案的单测（F 批）。
 *
 * 这里只测"事实怎么变成人话"，不碰网络与组件；模板渲染另有 app.smoke.test.js 兜底。
 *
 * 文案写法以形态原型为准（`frontend/prototype/product-form.html`）：
 * `正在翻译 · 第 3/10 页 · 已用 12 秒 · 引擎自报还需约 25 秒`。
 */

import { describe, expect, it } from 'vitest'

import {
  elapsedTextFor,
  enginePageText,
  etaTextFor,
  factLine,
  formatDuration,
  queueText,
  relativeTime,
  runningLine,
  stageTextFor,
} from '../src/progressText'

const running = { status: 'in_progress' }

describe('阶段文字', () => {
  it('排队中：有位置就说前面还有几篇', () => {
    expect(queueText({ status: 'pending', queue_position: 2 })).toBe('排队中 · 前面还有 2 篇')
    expect(queueText({ status: 'pending', queue_position: 0 })).toBe('排队中')
  })

  it('翻译中但引擎还没报进度：说"还没报进度"，不编百分比', () => {
    expect(stageTextFor(running, null)).toBe('正在翻译 · 引擎还没报进度')
  })

  it('引擎报的页数照原型写「第 X/Y 页」；没报就是空串（绝不编）', () => {
    expect(enginePageText({ done: 2, total: 5, percent: 0.4, rate: 1.72 })).toBe('第 2/5 页')
    expect(enginePageText({ done: 2, total: 5, rate: null })).toBe('第 2/5 页')
    expect(enginePageText({ done: 2 })).toBe('')
    expect(enginePageText({ done: 2, total: 0 })).toBe('')
    expect(enginePageText(null)).toBe('')
  })

  it('引擎进度字段不完整时当作没报（不显示半截数字）', () => {
    expect(stageTextFor(running, { done: 2 })).toBe('正在翻译 · 引擎还没报进度')
  })

  it('有引擎进度时阶段行只说"正在翻译"（页数单独一段，不混着说）', () => {
    expect(stageTextFor(running, { done: 2, total: 5, rate: 1.72 })).toBe('正在翻译')
  })

  it('各终态各说各的（已取消 ≠ 失败）', () => {
    expect(stageTextFor({ status: 'completed' }, null)).toBe('翻译完成')
    expect(stageTextFor({ status: 'cancelled' }, null)).toBe('已取消')
    expect(stageTextFor({ status: 'failed' }, null)).toBe('翻译失败')
    expect(stageTextFor(null, null)).toBe('')
  })
})

describe('L1 进行中任务条那一行（原型的四段式）', () => {
  it('四段都齐时，与原型逐字一致', () => {
    const task = { status: 'in_progress', elapsed_seconds: 12, eta_seconds: 25 }
    const engine = { done: 3, total: 10, percent: 0.3, eta_seconds: 25 }
    expect(runningLine(task, engine, 12)).toBe(
      '正在翻译 · 第 3/10 页 · 已用 12 秒 · 引擎自报还需约 25 秒',
    )
  })

  it('引擎没报进度时不留占位数字，只留真有的那几段', () => {
    const task = { status: 'in_progress', elapsed_seconds: 12, eta_seconds: null }
    expect(runningLine(task, null, 12)).toBe('正在翻译 · 引擎还没报进度 · 已用 12 秒')
  })

  it('排队中的任务条不说"正在翻译"', () => {
    expect(runningLine({ status: 'pending', queue_position: 2 }, null, null)).toBe(
      '排队中 · 前面还有 2 篇',
    )
  })

  it('factLine 丢掉空段，不留孤零零的分隔符', () => {
    expect(factLine(['a', '', null, undefined, 'b'])).toBe('a · b')
    expect(factLine([])).toBe('')
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
  it('只有跑着、且是正数才显示（**必须带"引擎自报"与"约"**，它只是引擎的估计）', () => {
    expect(etaTextFor(running, 25)).toBe('引擎自报还需约 25 秒')
    expect(etaTextFor(running, 0)).toBe('') // tqdm 四舍五入到 0，不是"马上好"
    expect(etaTextFor(running, null)).toBe('')
    expect(etaTextFor({ status: 'completed' }, 25)).toBe('')
  })
})

describe('相对时间（卡片上的"2 天前 / 昨天"）', () => {
  const now = new Date('2026-09-15T12:00:00').getTime()
  const at = (iso) => relativeTime(iso, now)

  it('按人话分档', () => {
    expect(at('2026-09-15T11:59:30')).toBe('刚刚')
    expect(at('2026-09-15T11:30:00')).toBe('30 分钟前')
    expect(at('2026-09-15T08:00:00')).toBe('4 小时前')
    expect(at('2026-09-14T12:00:00')).toBe('昨天')
    expect(at('2026-09-13T12:00:00')).toBe('2 天前')
    expect(at('2026-09-06T12:00:00')).toBe('上周')
    expect(at('2026-08-01T12:00:00')).toBe('2026-08-01')
  })

  it('解析不了就返回空串——不猜', () => {
    expect(relativeTime(null, now)).toBe('')
    expect(relativeTime('', now)).toBe('')
    expect(relativeTime('不是时间', now)).toBe('')
  })

  it('带时区的时间串按绝对时刻算（后端 2026-10-01 起一律输出 +00:00）', () => {
    // 不这么做的话：库里是 UTC（`func.now()`），串上不带时区，`new Date()` 按**本地**
    // 解析 → 卡片上的"上传时间"整体差一个时区（实测刚上传 20 分钟的文献显示「8 小时前」）。
    // 这条锁的是"串上带时区就按绝对时刻算"这个契约。**两端都用 Z 串**，所以结论与
    // 跑测机器的时区无关（CI 多半在 UTC 上跑）。
    const now = Date.parse('2026-09-15T12:00:00Z')
    expect(relativeTime('2026-09-15T12:00:00Z', now)).toBe('刚刚')
    expect(relativeTime('2026-09-15T04:00:00Z', now)).toBe('8 小时前')
    expect(relativeTime('2026-09-15T04:00:00+00:00', now)).toBe('8 小时前')
  })
})
