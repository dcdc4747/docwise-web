/**
 * 集合的树（`parent_id`）——后端早就支持（防环 / 同父去重 / 删除时子集合上提），
 * 前端一直平铺。这里钉三件事：
 *
 * 1. ⭐ **子集合缩进显示**（`↳` + 缩进），父在子上面；
 * 2. ⭐ **移动**发的是 `PATCH {parent_id}`，移到顶层时是 `null`（不是 `''`、不是 `0`）；
 * 3. ⭐ **新建时能带父级**（`POST {name, parent_id}`）。
 */

import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CollectionsView from '../src/views/CollectionsView.vue'

const json = (status, body) => ({
  ok: status < 400,
  status,
  json: async () => body,
  text: async () => JSON.stringify(body),
  headers: { get: () => 'application/json' },
})

const COLLECTIONS = [
  { id: 1, name: '甲', parent_id: null, doc_count: 2, doc_count_deep: 3 },
  { id: 2, name: '乙', parent_id: 1, doc_count: 1, doc_count_deep: 1 },
  { id: 3, name: '丙', parent_id: 2, doc_count: 0, doc_count_deep: 0 },
]

function stubApi({ collections = COLLECTIONS } = {}) {
  const calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url, init = {}) => {
      const path = String(url).split('?')[0]
      const method = (init.method || 'GET').toUpperCase()
      if (method !== 'GET') calls.push({ path, method, body: JSON.parse(init.body || '{}') })
      if (path === '/api/collections' && method === 'GET') return json(200, { items: collections })
      if (path === '/api/collections' && method === 'POST') return json(200, { id: 9 })
      if (path.startsWith('/api/collections/')) return json(200, { ok: true })
      if (path === '/api/tags') return json(200, { items: [] })
      if (path === '/api/smart-collections') return json(200, { items: [] })
      if (path === '/api/me/overview') return json(200, { tasks: 0, blocks: 0, materials: 0, citations: 0 })
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

describe('集合的树', () => {
  it('⭐ 子集合缩进显示，父在子上面', async () => {
    stubApi()
    wrapper = mount(CollectionsView)
    await settle(8)

    const rows = wrapper.findAll('.kn-list .kn-row')
    const names = rows.map((row) => row.find('.kn-name').text())
    expect(names).toEqual(['甲', '乙', '丙'])

    const margins = rows.map((row) => row.attributes('style') || '')
    expect(margins[0]).toContain('0px')
    expect(margins[1]).toContain('18px')
    expect(margins[2]).toContain('36px')
    // 缩进的行有分支符号
    expect(rows[1].find('.kn-branch').exists()).toBe(true)
    expect(rows[0].find('.kn-branch').exists()).toBe(false)
  })

  it('⭐ 父集合显示「含子」篇数（两个计数不混）', async () => {
    stubApi()
    wrapper = mount(CollectionsView)
    await settle(8)

    const parent = wrapper.findAll('.kn-list .kn-row')[0]
    // 甲：直接 2 篇，含子 3 篇 → 两个数都要说
    expect(parent.find('.kn-num').text()).toContain('2 篇')
    expect(parent.find('.kn-num').text()).toContain('含子 3 篇')
  })

  it('⭐ 移到顶层发 `PATCH {parent_id: null}`', async () => {
    const calls = stubApi()
    wrapper = mount(CollectionsView)
    await settle(8)

    const child = wrapper.findAll('.kn-list .kn-row')[1]
    const select = child.find('select.kn-move')
    await select.setValue('')
    await settle(8)

    const patch = calls.find((call) => call.method === 'PATCH')
    expect(patch, '没有发 PATCH').toBeTruthy()
    expect(patch.path).toBe('/api/collections/2')
    expect(patch.body).toEqual({ parent_id: null })
  })

  it('⭐ 新建时带父级：`POST {name, parent_id}`', async () => {
    const calls = stubApi()
    wrapper = mount(CollectionsView)
    await settle(8)

    await wrapper.findAll('.kn-ops button')[1].trigger('click') // ＋ 新建集合
    await settle(2)
    const form = wrapper.find('.kn-editor')
    await form.find('input.kn-input').setValue('新子集合')
    await form.find('select.kn-select').setValue('1')
    await form.find('button[type=submit]').trigger('submit')
    await settle(8)

    const post = calls.find((call) => call.method === 'POST')
    expect(post, '没有发 POST').toBeTruthy()
    expect(post.body).toEqual({ name: '新子集合', parent_id: 1 })
  })

  it('⭐ 父级选项里不出现自己（防环：后端会 400，界面别让人点到）', async () => {
    stubApi()
    wrapper = mount(CollectionsView)
    await settle(8)

    const parentRow = wrapper.findAll('.kn-list .kn-row')[0]
    const values = [...parentRow.find('select.kn-move').findAll('option')].map((o) => o.attributes('value'))
    expect(values).not.toContain('1') // 自己
    expect(values).toContain('') // 顶层永远可选
  })
})
