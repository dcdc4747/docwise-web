/**
 * App.vue 渲染冒烟测试。
 *
 * 存在的理由（F 批的真实事故）：模板里把函数当值插值（少写一对括号），
 * Vue 会 `String(fn)` 把**整个函数源码印在页面上**——而 `vite build` 一声不吭，
 * 最后是用户截图发现的。所以这里挂载真实的 App.vue、走一遍"打开一篇正在翻译的论文"，
 * 断言页面上出现的是人话、不出现任何源码痕迹。
 */

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.vue'

const HEALTH = {
  status: 'ok',
  service: 'docwise-web',
  checks: { database: true, worker: true },
  queue_size: 0,
  running_task_id: null,
  auth: { demo_autologin: false, session_days: 30 },
}

const TASK = {
  id: 7,
  filename: 'paper.pdf',
  status: 'in_progress',
  progress: 0.4,
  tier: 'fast',
  created_at: '2026-09-10T12:00:00',
  stage: 'translating',
  eta_seconds: 25,
  elapsed_seconds: 12,
  started_at: '2026-09-10T12:00:10',
  finished_at: null,
}

const TASK_DETAIL = {
  ...TASK,
  error_message: null,
  translated_path: null,
  dual_translated_path: null,
  blocks: [],
  files_ready: { mono: false, dual: false },
  understanding_status: 'pending',
  queue_position: null,
  engine_progress: { done: 2, total: 5, percent: 0.4, rate: 1.72, eta_seconds: 25 },
}

/** 页面文本里不该出现的东西：函数源码 / 模板语法 / 序列化对象。 */
const SOURCE_LEAKS = ['function ', '=>', 'ref(', 'computed(', '{{', 'undefined']

function stubFetch() {
  return vi.fn(async (input, init = {}) => {
    const url = typeof input === 'string' ? input : String(input?.url ?? input)
    const method = (init.method || 'GET').toUpperCase()
    const json = (data) => ({ ok: true, status: 200, json: async () => data })

    if (url.includes('/api/health')) return json(HEALTH)
    if (url.includes('/api/auth/me')) {
      return json({ id: 1, username: 'tester', display_name: '测试用户', role: 'user' })
    }
    if (url.includes('/api/auth/ticket') && method === 'POST') return json({ ticket: 't' })
    if (url.match(/\/api\/tasks\/7\/?$/)) return json(TASK_DETAIL)
    if (url.includes('/api/tasks')) return json([TASK])
    return json({})
  })
}

function mountApp() {
  return mount(App, { attachTo: document.body })
}

describe('App.vue 页面渲染', () => {
  let wrapper = null

  beforeEach(() => {
    localStorage.clear()
    globalThis.fetch = stubFetch()
  })

  afterEach(() => {
    // 一定要卸载：否则上一个用例挂载的组件还在跑（轮询/请求回调），
    // 会串到下个用例里，造成"单跑能过、一起跑就红"的假故障
    wrapper?.unmount()
    wrapper = null
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('未登录时渲染登录页，且页面文本里没有源码痕迹', async () => {
    wrapper = mountApp()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('登录')
    for (const leak of SOURCE_LEAKS) {
      expect(text).not.toContain(leak)
    }
  })

  it('打开正在翻译的论文：进度区显示人话（页进度 / 已用 / 预计剩余），不印函数源码', async () => {
    localStorage.setItem('docwise_token', 'test-token')
    wrapper = mountApp()
    await flushPromises()

    // 历史列表里点"查看进度" → 打开工作台
    const openButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('查看进度'))
    expect(openButton, '历史列表里没找到"查看进度"按钮，说明列表没渲染出来').toBeTruthy()
    await openButton.trigger('click')
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('正在翻译 · 第 2/5 页 · 1.72 页/秒')
    expect(text).toContain('已用 12 秒')
    expect(text).toContain('引擎预计还需 25 秒')
    // 这正是当初印着一整段 `function Be(){...}` 的地方
    for (const leak of SOURCE_LEAKS) {
      expect(text).not.toContain(leak)
    }
  })

  it('引擎还没报进度时：说"还在准备"，不显示假的百分比', async () => {
    localStorage.setItem('docwise_token', 'test-token')
    const base = stubFetch()
    const noEngine = { ...TASK_DETAIL, engine_progress: null }
    globalThis.fetch = vi.fn(async (input, init) => {
      const url = typeof input === 'string' ? input : String(input?.url ?? input)
      if (url.match(/\/api\/tasks\/7\/?$/)) {
        return { ok: true, status: 200, json: async () => noEngine }
      }
      return base(input, init)
    })

    wrapper = mountApp()
    await flushPromises()
    const openButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('查看进度'))
    await openButton.trigger('click')
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('正在翻译 · 引擎还在准备')
    expect(text).not.toContain('第 2/5 页')
    for (const leak of SOURCE_LEAKS) {
      expect(text).not.toContain(leak)
    }
  })
})
