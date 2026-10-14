/**
 * 哈希路由的单测（M0）。
 *
 * 分两层：
 * ① **纯函数**（`parseHash` / `buildHash`）——不碰浏览器，逐条把边界钉死；
 * ② **接线行为**（`navigate` / `onRouteChange`）——在 happy-dom 里真改 `location.hash`，
 *    验证"改地址会通知谁""同一个地址写两次只记一条历史""replace 不发新历史"。
 *
 * 为什么这层必须有单测：路由本身不渲染任何东西，**坏了不会白屏、只会"点返回回到错的页"
 * 或"刷新丢页"**——这两种都很难靠肉眼在几十屏里发现，只有断言能钉住。
 *
 * ⚠️ 组件级路由（进阅读区、刷新回原页）在 `app.smoke.test.js` 里另有覆盖。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  FALLBACK_ROUTE,
  ROUTES,
  buildHash,
  currentRoute,
  navigate,
  onRouteChange,
  parseHash,
} from '../src/router'

describe('parseHash：地址 → 路由', () => {
  it('空地址 / 只有一个 # → 库页', () => {
    expect(parseHash('')).toEqual({ name: 'library', params: {} })
    expect(parseHash('#')).toEqual({ name: 'library', params: {} })
    expect(parseHash('#/')).toEqual({ name: 'library', params: {} })
    expect(parseHash('/')).toEqual({ name: 'library', params: {} })
  })

  it('阅读页带出任务号（数字）', () => {
    expect(parseHash('#/read/12')).toEqual({ name: 'read', params: { taskId: 12 } })
    expect(parseHash('/read/12')).toEqual({ name: 'read', params: { taskId: 12 } })
  })

  it('任务号不合法的一律当"不认识的地址"落库页 —— 调用方永远不用处理"进了阅读页却没任务号"', () => {
    for (const bad of ['abc', '0', '-3', '1.5', '']) {
      expect(parseHash(`#/read/${bad}`).name).toBe(FALLBACK_ROUTE)
    }
  })

  it('已经声明但没做的页面也能被认出来（由页面那边如实说"还没做"）', () => {
    for (const name of ['write', 'memory', 'process', 'me', 'admin']) {
      expect(parseHash(`#/${name}`).name).toBe(name)
    }
  })

  it('未知地址 → 兜底路由（库页），不抛错', () => {
    for (const bad of ['#/garbage', '#/read', '#/library/x', '#/read/1/2', '#//']) {
      expect(parseHash(bad).name).toBe(FALLBACK_ROUTE)
    }
  })

  it('忽略查询串与末尾斜杠', () => {
    expect(parseHash('#/read/12?tab=guide').params.taskId).toBe(12)
    expect(parseHash('#/write/').name).toBe('write')
  })
})

describe('buildHash：路由 → 地址', () => {
  it('库页拼成 #/', () => {
    expect(buildHash('library')).toBe('#/')
  })

  it('阅读页把任务号填进参数段', () => {
    expect(buildHash('read', { taskId: 12 })).toBe('#/read/12')
  })

  it('未知路由名落兜底（与 parseHash 对称，不会拼出坏地址）', () => {
    expect(buildHash('nope')).toBe('#/')
  })

  it('参数缺失时不留下空段（宁可回到不带 id 的地址，也不拼出 #/read/）', () => {
    expect(buildHash('read', {})).toBe('#/read')
  })

  it('与 parseHash 互为逆运算（能来回）', () => {
    for (const [name, params] of [
      ['library', {}],
      ['read', { taskId: 7 }],
      ['write', {}],
      ['me', {}],
    ]) {
      expect(parseHash(buildHash(name, params))).toEqual({ name, params })
    }
  })

  it('路由表里每个 name 都能拼出一个能被解析回来的地址', () => {
    for (const name of Object.keys(ROUTES)) {
      const params = name === 'read' ? { taskId: 3 } : {}
      expect(parseHash(buildHash(name, params)).name).toBe(name)
    }
  })
})

describe('navigate / onRouteChange：真改地址', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '#/')
  })

  it('改地址会通知订阅方，且给的是解析后的路由', async () => {
    const seen = []
    const stop = onRouteChange((route) => seen.push(route))
    navigate('read', { taskId: 5 })
    expect(window.location.hash).toBe('#/read/5')
    // happy-dom 里 hashchange 是**异步派发**的，所以这里要等一拍——
    // 这条本身就是个重要事实：别在 `navigate()` 之后同步断言监听方已经收到。
    await vi.waitFor(() => expect(seen).toEqual([{ name: 'read', params: { taskId: 5 } }]))
    stop()
  })

  it('取消订阅之后不再收到通知（组件卸载必须调，否则监听越积越多）', () => {
    const spy = vi.fn()
    const stop = onRouteChange(spy)
    stop()
    navigate('write')
    expect(spy).not.toHaveBeenCalled()
  })

  it('地址没变就不写：不会平白多记一条历史', () => {
    window.history.replaceState(null, '', '#/read/9')
    const before = window.history.length
    navigate('read', { taskId: 9 })
    expect(window.history.length).toBe(before)
  })

  it('replace 不发新历史，但**照样广播**（否则监听方收不到、状态对不上）', () => {
    window.history.replaceState(null, '', '#/read/9')
    const before = window.history.length
    const spy = vi.fn()
    const stop = onRouteChange(spy)
    navigate('library', {}, { replace: true })
    expect(window.location.hash).toBe('#/')
    expect(window.history.length).toBe(before)
    expect(spy).toHaveBeenCalledTimes(1)
    stop()
  })

  it('currentRoute() 读的是当前地址', () => {
    window.history.replaceState(null, '', '#/read/42')
    expect(currentRoute()).toEqual({ name: 'read', params: { taskId: 42 } })
  })
})
