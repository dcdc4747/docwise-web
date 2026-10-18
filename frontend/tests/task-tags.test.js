/**
 * 卡片上的标签（N7）——真挂 `LibraryView` 点一遍。
 *
 * 盯三条：
 * 1. ⭐ **全量替换**：点「＋ 标签」加一个，请求体必须是「已有的 + 新的」，
 *    只发新的会把别的标签抹掉；
 * 2. ⭐ **kind 沿用**：新贴的标签如果已有同名标签，`kind` 要用已有的（不然会把 method 改成 topic）；
 * 3. ⭐ **点 chip 上的 × 是删除**（同样整组发）。
 */

import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import LibraryView from '../src/views/LibraryView.vue'
import { loadTasksAndSync } from '../src/stores/useLibrary'

const json = (status, body) => ({
  ok: status < 400,
  status,
  json: async () => body,
  text: async () => JSON.stringify(body),
  headers: { get: () => 'application/json' },
})

const TASK = {
  id: 7,
  filename: 'p.pdf',
  status: 'completed',
  progress: 1,
  tier: 'fast',
  source_lang: 'en',
  target_lang: 'zh',
  native: false,
  created_at: '2026-10-18T00:00:00+00:00',
  elapsed_seconds: 30,
  last_read_page: 1,
  collection_ids: [],
  tags: ['RAG'],
  archived: false,
}

function stubApi() {
  const puts = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url, init = {}) => {
      const path = String(url).split('?')[0]
      const method = (init.method || 'GET').toUpperCase()
      if (path.endsWith('/tags') && method === 'PUT') {
        puts.push({ path, body: JSON.parse(init.body || '{}') })
        return json(200, { items: [] })
      }
      if (path === '/api/tasks') return json(200, [TASK])
      if (path === '/api/tasks/7') return json(200, TASK)
      if (path === '/api/tags') {
        return json(200, {
          items: [
            { id: 1, name: '方法', kind: 'method', doc_count: 1 },
            { id: 2, name: 'RAG', kind: 'topic', doc_count: 1 },
          ],
        })
      }
      if (path === '/api/collections' || path === '/api/smart-collections') return json(200, { items: [] })
      if (path === '/api/me/overview') {
        return json(200, { tasks: 1, blocks: 3, materials: 0, citations: 0 })
      }
      if (path === '/api/me/preferences') return json(200, { prefs: {} })
      return json(200, {})
    }),
  )
  return puts
}

const settle = async (times = 4) => {
  for (let i = 0; i < times; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
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

describe('卡片标签（N7）', () => {
  it('⭐ 加一个标签：请求体是「已有的 + 新的」整组，且新标签沿用同名标签的 kind', async () => {
    const puts = stubApi()
    wrapper = mount(LibraryView)
    await loadTasksAndSync()
    await settle(6)

    // 卡片上有「RAG」这个 chip
    expect(wrapper.text()).toContain('RAG')

    // 点「＋ 标签」→ 输入「方法」→ 回车
    const addButton = wrapper.findAll('button').find((b) => b.text().includes('＋ 标签'))
    expect(addButton, '没找到「＋ 标签」按钮').toBeTruthy()
    await addButton.trigger('click')
    await settle(2)

    const input = wrapper.find('.lib-tag-input')
    expect(input.exists(), '没出现输入框').toBe(true)
    await input.setValue('方法')
    await input.trigger('keydown', { key: 'Enter' })
    await settle(6)

    expect(puts.length, '没有发 N7 请求').toBe(1)
    const names = puts[0].body.tags.map((t) => t.name)
    expect(names).toContain('RAG') // ⭐ 已有标签必须还在（全量替换）
    expect(names).toContain('方法')
    // kind：方法 = method（沿用已有标签），RAG = topic
    expect(puts[0].body.tags.find((t) => t.name === '方法').kind).toBe('method')
    expect(puts[0].body.tags.find((t) => t.name === 'RAG').kind).toBe('topic')
  })

  it('⭐ 点 chip 上的 × 是删除：整组里不再有它', async () => {
    const puts = stubApi()
    wrapper = mount(LibraryView)
    // ⚠️ 别依赖上一条用例留下的模块状态：自己拉一次
    await loadTasksAndSync()
    await settle(6)

    const chip = wrapper.find('.lib-tag-chip')
    expect(chip.exists()).toBe(true)
    await chip.trigger('click')
    await settle(6)

    expect(puts.length).toBe(1)
    expect(puts[0].body.tags.map((t) => t.name)).not.toContain('RAG')
  })
})
