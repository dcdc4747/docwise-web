/**
 * 块曝光埋点（N34）的前端用例 —— 形态 §5 假设 1 的**分母**。
 *
 * 为什么单开一份：这一路**只在真浏览器里才动**（IntersectionObserver + 真滚动），
 * 而它要保证的恰恰是几件**看不出来但很要命**的事：
 *
 * 1. ⭐ **协议对**：N34 的请求体是**单个对象**，不是批量数组——写错了后端会 422/400，
 *    而界面上**什么都看不出来**（曝光是旁支数据，失败了也不影响阅读）；
 * 2. ⭐ **幂等**：同一会话同一块**只报一次进入**（用户反复滚来滚去不该刷请求）；
 * 3. ⭐ **并发闸**：183 块同时进视口时**不能一次打 183 个请求**；
 * 4. ⭐ **失败不打断**：一遍失败不影响后面的块继续上报；
 * 5. ⭐ **离开也记**：`left_at` 要往后推（"看了多久"的来源，也是 §5 那条
 *    "两种分母各算一遍"的一半）。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getToken = vi.fn(() => 'tok')
vi.mock('../src/auth', () => ({ getToken: () => getToken() }))
vi.mock('../src/api', () => ({ apiUrl: (p) => p }))

const { createExposureReporter, newSessionId, visibleBlockIds, MAX_INFLIGHT } = await import(
  '../src/exposure'
)

const readSrc = (rel) => readFileSync(resolve(process.cwd(), rel), 'utf8')

let fetchMock
let posts

beforeEach(() => {
  posts = []
  fetchMock = vi.fn((url, options) => {
    posts.push({ url, body: JSON.parse(options.body), headers: options.headers })
    return Promise.resolve({ ok: true, status: 201 })
  })
  globalThis.fetch = fetchMock
  getToken.mockReturnValue('tok')
  navigator.sendBeacon = vi.fn(() => true)
})

/* 造一批假的块元素：只有 clientHeight / 矩形，不依赖 happy-dom 的布局引擎。 */
function fakeRoot(items) {
  return {
    querySelectorAll: () =>
      items.map((it) => ({
        getAttribute: (name) => (name === 'data-block-id' ? it.id : null),
        clientHeight: it.h ?? 20,
        getBoundingClientRect: () => ({ top: it.top, bottom: it.bottom }),
      })),
  }
}

describe('曝光：纯函数', () => {
  it('会话 id 每次都不一样，带前缀、长度在契约上限内（str(64)）', () => {
    const a = newSessionId()
    const b = newSessionId()
    expect(a).not.toBe(b)
    expect(a.startsWith('s_')).toBe(true)
    expect(a.length).toBeLessThanOrEqual(64)
  })

  it('⭐ 只挑视口内的块，按文档顺序去重，零尺寸的不算', () => {
    const root = fakeRoot([
      { id: 'p0_b0', top: -10, bottom: 20 }, // 视口内
      { id: 'p0_b1', top: 100, bottom: 130 }, // 视口内
      { id: 'p0_b2', top: 900, bottom: 930 }, // 视口外（下）
      { id: 'p0_b3', top: -80, bottom: -40 }, // 视口外（上）
      { id: 'p0_b4', top: 10, bottom: 40, h: 0 }, // 零尺寸 = 没真渲染
      { id: 'p0_b1', top: 100, bottom: 130 }, // 重复
    ])
    expect(visibleBlockIds(root, { viewportHeight: 800 })).toEqual(['p0_b0', 'p0_b1'])
  })

  it('margin 把"刚好在视口下方"的块也算进来（视口判定的余量）', () => {
    // ⚠️ 余量方向要想清楚：`margin` 是**放宽**判定——把"几乎就要进来了"的也算上。
    // 视口高 800 时，top=830 的块默认不算；给了 40 的余量就该算。
    const root = fakeRoot([{ id: 'p0_b0', top: 830, bottom: 860 }])
    expect(visibleBlockIds(root, { viewportHeight: 800 })).toEqual([])
    expect(visibleBlockIds(root, { viewportHeight: 800, margin: 40 })).toEqual(['p0_b0'])
  })

  it('坏输入不崩：根节点为空 / 没有 querySelectorAll / 元素没有 block_id', () => {
    expect(visibleBlockIds(null)).toEqual([])
    expect(visibleBlockIds({})).toEqual([])
    expect(visibleBlockIds(fakeRoot([{ id: null, top: 0, bottom: 10 }]))).toEqual([])
  })
})

describe('曝光：上报协议与幂等', () => {
  it('⭐ 请求体是**单个对象**（N34 形状），不是批量数组', async () => {
    const r = createExposureReporter({ taskId: 46, sessionId: 's_test' })
    r.enter(['p0_b0'])
    await vi.waitFor(() => expect(posts.length).toBe(1))
    const body = posts[0].body
    expect(Array.isArray(body)).toBe(false)
    expect(body.task_id).toBe(46)
    expect(body.session_id).toBe('s_test')
    expect(body.block_id).toBe('p0_b0')
    // 进入时两个时间戳都给（后端取较大值，所以要给全）
    expect(typeof body.entered_at).toBe('string')
    expect(typeof body.left_at).toBe('string')
    expect(posts[0].url).toBe('/api/block-exposures')
    expect(posts[0].headers.Authorization).toBe('Bearer tok')
  })

  it('⭐ 同一块反复进入只报一次（用户滚来滚去不该刷请求）', async () => {
    const r = createExposureReporter({ taskId: 46, sessionId: 's_test' })
    r.enter(['p0_b0'])
    r.enter(['p0_b0'])
    r.enter(['p0_b0', 'p0_b0'])
    await vi.waitFor(() => expect(posts.length).toBe(1))
    await new Promise((res) => setTimeout(res, 20))
    expect(posts.length).toBe(1)
  })

  it('⭐ 离开会把 left_at 再报一次（"看了多久"的来源）', async () => {
    const times = ['2026-10-16T10:00:00.000Z', '2026-10-16T10:00:30.000Z']
    let i = 0
    const r = createExposureReporter({ taskId: 46, sessionId: 's_test', now: () => new Date(times[i++]) })
    r.enter(['p0_b0'])
    await vi.waitFor(() => expect(posts.length).toBe(1))
    r.leave(['p0_b0'])
    await vi.waitFor(() => expect(posts.length).toBe(2))
    expect(posts[1].body.block_id).toBe('p0_b0')
    expect(posts[1].body.entered_at).toBeNull() // 只推"离开"，不再乱改进入时间
    expect(posts[1].body.left_at).toBe('2026-10-16T10:00:30.000Z')
  })

  it('没报过进入的块，离开也不报（宁少一条，也不造一条没看过的记录）', async () => {
    const r = createExposureReporter({ taskId: 46, sessionId: 's_test' })
    r.leave(['p9_b9'])
    await new Promise((res) => setTimeout(res, 30))
    expect(posts.length).toBe(0)
  })

  it('⭐ 并发闸：一次报 183 块，同时在飞的请求不超过上限', async () => {
    // ⚠️ 放行要**一个一个来**：新请求是在上一个的微任务里递补的，
    //    一口气把解析器排空（while 循环）会让计数停在半路——那是用例写错了，不是实现的问题。
    const resolvers = []
    globalThis.fetch = vi.fn((url, options) => {
      posts.push({ url, body: JSON.parse(options.body) })
      return new Promise((res) => resolvers.push(() => res({ ok: true, status: 201 })))
    })
    const r = createExposureReporter({ taskId: 46, sessionId: 's_test' })
    const ids = Array.from({ length: 183 }, (_, n) => `p0_b${n}`)
    r.enter(ids)

    await vi.waitFor(() => expect(posts.length).toBe(MAX_INFLIGHT))
    // 放行一个 → 才递补一个：**总数始终不超过上限 + 已放行的**
    resolvers.shift()()
    await vi.waitFor(() => expect(posts.length).toBe(MAX_INFLIGHT + 1))

    // 把剩下的全部放行（每放一个都等新解析器就位）
    let released = 1
    while (released < ids.length) {
      await vi.waitFor(() => expect(resolvers.length).toBeGreaterThan(0))
      resolvers.shift()()
      released += 1
    }
    await vi.waitFor(() => expect(posts.length).toBe(ids.length))
    // 183 块一个不少、且每块只一次
    const seen = new Set(posts.map((p) => p.body.block_id))
    expect(seen.size).toBe(ids.length)
  })

  it('⭐ 一次失败不影响后面的块继续上报（旁支数据不许拖死队列）', async () => {
    let n = 0
    globalThis.fetch = vi.fn((url, options) => {
      n += 1
      posts.push(JSON.parse(options.body))
      if (n === 1) return Promise.reject(new Error('boom'))
      return Promise.resolve({ ok: true, status: 201 })
    })
    const r = createExposureReporter({ taskId: 46, sessionId: 's_test' })
    r.enter(['p0_b0', 'p0_b1', 'p0_b2'])
    await vi.waitFor(() => expect(posts.length).toBe(3))
    expect(posts.map((p) => p.block_id)).toEqual(['p0_b0', 'p0_b1', 'p0_b2'])
  })

  it('dispose 之后不再上报（切走阅读页那一瞬间的滚动不该再发请求）', async () => {
    const r = createExposureReporter({ taskId: 46, sessionId: 's_test' })
    r.dispose()
    r.enter(['p0_b0'])
    r.leave(['p0_b0'])
    await new Promise((res) => setTimeout(res, 30))
    expect(posts.length).toBe(0)
  })
})

describe('曝光：离开页面时用 Beacon 送最后一批', () => {
  it('⭐ 有 sendBeacon 就走 Beacon（普通 fetch 在关页时会被取消 = 静默丢数据）', async () => {
    const r = createExposureReporter({ taskId: 46, sessionId: 's_test' })
    r.enter(['p0_b0', 'p0_b1'])
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    r.beacon()
    expect(navigator.sendBeacon).toHaveBeenCalled()
    const [url, blob] = navigator.sendBeacon.mock.calls[0]
    expect(url).toBe('/api/block-exposures')
    expect(blob).toBeTruthy()
  })

  it('没看过任何块时，Beacon 一条都不补（不许造"看过"的记录）', () => {
    const r = createExposureReporter({ taskId: 46, sessionId: 's_test' })
    r.beacon()
    expect(navigator.sendBeacon).not.toHaveBeenCalled()
  })

  it('⭐ 补发有上限：183 块也不会一口气发 183 个（关页时后面会被丢掉）', async () => {
    const r = createExposureReporter({ taskId: 46, sessionId: 's_test' })
    const ids = Array.from({ length: 183 }, (_, n) => `p0_b${n}`)
    r.enter(ids)
    await vi.waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(0))
    navigator.sendBeacon.mockClear()
    r.beacon()
    expect(navigator.sendBeacon.mock.calls.length).toBeLessThanOrEqual(40)
    expect(navigator.sendBeacon.mock.calls.length).toBeGreaterThan(0)
  })

  it('没有 sendBeacon 时退回 keepalive fetch（并带上令牌）', async () => {
    navigator.sendBeacon = vi.fn(() => false)
    const r = createExposureReporter({ taskId: 46, sessionId: 's_test' })
    r.enter(['p0_b0'])
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    fetchMock.mockClear()
    r.beacon()
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    const [, options] = fetchMock.mock.calls[0]
    expect(options.keepalive).toBe(true)
    expect(options.headers.Authorization).toBe('Bearer tok')
    expect(JSON.parse(options.body).block_id).toBe('p0_b0')
  })
})

describe('曝光：接线（源码级守卫）', () => {
  it('⭐ ReadView 真的在观察块（不是只写了模块没人用）', () => {
    const src = readSrc('src/views/ReadView.vue')
    expect(src).toContain('createExposureReporter')
    expect(src).toContain('IntersectionObserver')
    // 三个收尾口都要接：离开视口、滚动/尺寸变化、页面隐藏
    expect(src).toContain('leave(')
    expect(src).toContain('scan(')
    expect(src).toContain('beacon(')
  })

  it('观察的是 `[data-block-id]`（两条渲染路径都挂了这个属性，不靠选择器猜）', () => {
    const src = readSrc('src/exposure.js')
    expect(src).toContain("querySelectorAll('[data-block-id]')")
    // 两条路径确实都挂了 data-block-id
    const view = readSrc('src/views/ReadView.vue')
    const hits = view.match(/:data-block-id=/g) || []
    expect(hits.length).toBeGreaterThanOrEqual(2)
  })
})
