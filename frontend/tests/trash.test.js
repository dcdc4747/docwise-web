/**
 * 回收站页三条口径：
 * 1. 列表走 `?trashed=1`（正常列表里看不到删掉的）；
 * 2. **恢复**调 `POST /api/tasks/{id}/restore`；
 * 3. **彻底删除必须两步**：先点「彻底删除…」，再点「确认彻底删除」才发 `DELETE …/purge`。
 */

import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import TrashView from '../src/views/TrashView.vue'

const json = (status, body) => ({
  ok: status < 400,
  status,
  json: async () => body,
  text: async () => JSON.stringify(body),
  headers: { get: () => 'application/json' },
})

const TRASHED = [
  {
    id: 7,
    filename: 'spilled.pdf',
    status: 'completed',
    deleted_at: '2026-10-18T05:00:00+00:00',
    tags: [],
  },
  {
    id: 9,
    filename: 'old-draft.pdf',
    status: 'failed',
    deleted_at: '2026-10-17T09:30:00+00:00',
    tags: ['方法'],
  },
]

function stubApi({ items = TRASHED } = {}) {
  const calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url, init = {}) => {
      const path = String(url).split('?')[0]
      const full = String(url)
      const method = (init.method || 'GET').toUpperCase()
      if (method !== 'GET') calls.push({ path, method })
      if (method === 'GET' && full.includes('trashed=1')) return json(200, items)
      if (path === '/api/tasks') return json(200, [])
      return json(200, {})
    }),
  )
  return calls
}

const settle = async (times = 6) => {
  for (let i = 0; i < times; i += 1) await new Promise((resolve) => setTimeout(resolve, 0))
}

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

describe('回收站', () => {
  it('列出回收站里的文献，并显示删除时间', async () => {
    stubApi()
    wrapper = mount(TrashView)
    await settle(8)

    const rows = wrapper.findAll('.kn-row')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('spilled.pdf')
    expect(rows[0].text()).toContain('删除于')
    expect(rows[0].text()).toContain('10/18')
  })

  it('⭐ 恢复发 `POST /api/tasks/7/restore`', async () => {
    const calls = stubApi()
    wrapper = mount(TrashView)
    await settle(8)

    const restore = wrapper.findAll('.kn-row')[0].findAll('button').find((b) => b.text() === '恢复')
    expect(restore, '没找到「恢复」').toBeTruthy()
    await restore.trigger('click')
    await settle(8)

    expect(calls[0]).toEqual({ path: '/api/tasks/7/restore', method: 'POST' })
    expect(wrapper.text()).toContain('已恢复')
  })

  it('⭐ 彻底删除要两步：第一次点只出确认，不请求', async () => {
    const calls = stubApi()
    wrapper = mount(TrashView)
    await settle(8)

    const row = wrapper.findAll('.kn-row')[0]
    const first = row.findAll('button').find((b) => b.text().includes('彻底删除'))
    await first.trigger('click')
    await settle(4)

    expect(calls, '不该在第一次点击时就发请求').toHaveLength(0)
    expect(wrapper.text()).toContain('确认彻底删除')

    const confirm = wrapper.findAll('button').find((b) => b.text() === '确认彻底删除')
    await confirm.trigger('click')
    await settle(8)

    expect(calls[0]).toEqual({ path: '/api/tasks/7/purge', method: 'DELETE' })
    expect(wrapper.text()).toContain('不可恢复')
  })

  it('空回收站说清"删掉的会先到这里"', async () => {
    stubApi({ items: [] })
    wrapper = mount(TrashView)
    await settle(8)

    expect(wrapper.text()).toContain('回收站是空的')
    expect(wrapper.text()).toContain('不会直接消失')
  })
})
