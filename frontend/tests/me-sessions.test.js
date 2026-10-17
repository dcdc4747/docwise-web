/**
 * 「登录设备与会话」（N29）的三条界面口径。
 *
 * 为什么要钉：这张表之前出过三个真问题（用户截图报的）——
 * ① 会话**只增不减**，一屏 132 行；② 表格撑破卡片、时间折两行；
 * ③ **分不清哪台是自己**，吊销按钮长得一样，容易把自己踢下线。
 * 后端那边已封顶 20 条并给 `current`；这里钉前端怎么把它说清楚。
 */

import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import MeView from '../src/views/MeView.vue'

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

function stubApi({ items = [], total = 0 } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input) => {
      const path = String(input).split('?')[0]
      if (path === '/api/auth/me') {
        return json({ id: 1, username: 'demo', role: 'admin', display_name: null })
      }
      if (path === '/api/me/sessions') return json({ items, total })
      if (path === '/api/me/storage') return json({ total_bytes: 0, by_kind: {} })
      if (path === '/api/me/ledger') return json({ items: [] })
      if (path === '/api/me/preferences') return json({ prefs: {} })
      return json({}, 200)
    }),
  )
}

const SESSIONS = [
  {
    id: 11,
    user_agent: 'Mozilla/5.0 (Windows NT 10.0) Chrome/155',
    created_at: '2026-10-18T00:10:00+00:00',
    last_seen_at: '2026-10-18T00:10:00+00:00',
    expires_at: '2026-11-17T00:10:00+00:00',
    current: true,
  },
  {
    id: 12,
    user_agent: 'Mozilla/5.0 (iPhone) Safari/605',
    created_at: '2026-10-17T09:00:00+00:00',
    last_seen_at: '2026-10-17T09:00:00+00:00',
    expires_at: '2026-11-16T09:00:00+00:00',
    current: false,
  },
]

let wrapper = null

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('docwise_token', 'test-token')
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.unstubAllGlobals()
})

describe('登录设备与会话', () => {
  it('⭐ 标出「本机」，并且那一行的按钮叫「退出这台」（不是「吊销」）', async () => {
    stubApi({ items: SESSIONS, total: 2 })
    wrapper = mount(MeView)
    await new Promise((resolve) => setTimeout(resolve, 0))
    await new Promise((resolve) => setTimeout(resolve, 0))

    const rows = wrapper.findAll('.me-sessions tbody tr')
    expect(rows).toHaveLength(2)

    const current = rows.find((row) => row.classes().includes('me-this'))
    expect(current, '没有标出本机那一行').toBeTruthy()
    expect(current.text()).toContain('本机')
    expect(current.text()).toContain('退出这台')
    // 别人的行仍然是"吊销"
    expect(rows.find((row) => !row.classes().includes('me-this')).text()).toContain('吊销')
  })

  it('⭐ 说清"一共几台、只显示最近几台"（否则以为设备丢了）', async () => {
    // total 比 items 多：模拟"还有更早的会话没列出来"
    stubApi({ items: SESSIONS, total: 23 })
    wrapper = mount(MeView)
    await new Promise((resolve) => setTimeout(resolve, 0))
    await new Promise((resolve) => setTimeout(resolve, 0))

    const text = wrapper.find('.me-sessions-sum').text()
    expect(text).toContain('共 23 台设备在线')
    expect(text).toContain('只显示最近 2 台')
  })

  it('时间**一行放得下**（不能在窄列里折成两行）', async () => {
    stubApi({ items: SESSIONS, total: 2 })
    wrapper = mount(MeView)
    await new Promise((resolve) => setTimeout(resolve, 0))
    await new Promise((resolve) => setTimeout(resolve, 0))

    const when = wrapper.find('.me-sessions .me-when')
    const text = when.text()
    expect(text).toMatch(/^\d{2}\/\d{2} \d{2}:\d{2}$/)
    // 断言它不含换行（折行会带出 \n 或多个空格块）
    expect(text.includes('\n')).toBe(false)
  })
})
