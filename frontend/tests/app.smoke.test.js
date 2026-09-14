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
    expect(text).toContain('正在翻译')
    expect(text).toContain('已用 12 秒')
    expect(text).toContain('引擎自报：第 2/5 页 · 1.72 页/秒')
    // 这正是当初印着一整段 `function Be(){...}` 的地方
    for (const leak of SOURCE_LEAKS) {
      expect(text).not.toContain(leak)
    }
    // 进度条必须还在（这个坑真踩过：没数字就不画 → 用户看到"进度条没了"）
    expect(wrapper.find('.n-progress').exists()).toBe(true)
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
    expect(text).toContain('正在翻译 · 引擎还没报进度')
    expect(text).not.toContain('第 2/5 页')
    // 没拿到数字时进度条也要在（只是不写百分比，改成流动条纹）
    const bar = wrapper.find('.n-progress')
    expect(bar.exists()).toBe(true)
    expect(bar.text()).not.toContain('%')
    for (const leak of SOURCE_LEAKS) {
      expect(text).not.toContain(leak)
    }
  })

  it('中文文献：上传区能选语言，选中文后翻译档位消失', async () => {
    localStorage.setItem('docwise_token', 'test-token')
    wrapper = mountApp()
    await flushPromises()

    expect(wrapper.text()).toContain('文献语言')
    expect(wrapper.text()).toContain('中文文献')
    expect(wrapper.text()).toContain('翻译档位')

    // 中文文献不翻译，档位没有意义 → 选中文后档位那块要收起来
    const zhInput = wrapper
      .findAll('input[type="radio"]')
      .find((i) => i.element.value === 'zh')
    expect(zhInput, '上传区没有"中文文献"选项').toBeTruthy()
    await zhInput.setValue()
    await flushPromises()

    const text = wrapper.text()
    expect(text).not.toContain('翻译档位')
    expect(text).toContain('中文文献不翻译')
    for (const leak of SOURCE_LEAKS) {
      expect(text).not.toContain(leak)
    }
  })

  it('中文文献：工作台显示"原文"，不提供中英对照与双语下载', async () => {
    localStorage.setItem('docwise_token', 'test-token')
    const base = stubFetch()
    const nativeTask = {
      ...TASK,
      status: 'completed',
      progress: 1,
      stage: null,
      eta_seconds: null,
      native: true,
      source_lang: 'zh',
      target_lang: 'zh',
    }
    const nativeDetail = {
      ...TASK_DETAIL,
      ...nativeTask,
      // 中文文献只有一份产物（原稿），没有双语稿
      files_ready: { mono: true, dual: false },
      engine_progress: null,
    }
    globalThis.fetch = vi.fn(async (input, init = {}) => {
      const url = typeof input === 'string' ? input : String(input?.url ?? input)
      const json = (data) => ({ ok: true, status: 200, json: async () => data })
      if (url.match(/\/api\/tasks\/7\/?$/)) return json(nativeDetail)
      if (url.includes('/api/tasks')) return json([nativeTask])
      return base(input, init)
    })

    wrapper = mountApp()
    await flushPromises()
    const openButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('继续读'))
    expect(openButton, '历史列表里没找到"继续读"按钮').toBeTruthy()
    await openButton.trigger('click')
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('这里就是原文')
    expect(text).toContain('下载原稿 PDF')
    expect(text).not.toContain('中英对照')
    expect(text).not.toContain('下载双语 PDF')
    for (const leak of SOURCE_LEAKS) {
      expect(text).not.toContain(leak)
    }
  })

  it('两级结构：打开一篇进 L2 阅读工作区，点「← 我的论文」回 L1 库页', async () => {
    localStorage.setItem('docwise_token', 'test-token')
    wrapper = mountApp()
    await flushPromises()

    // L1 库页：历史卡片在，阅读工作区不在
    expect(wrapper.find('.history-card').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('← 我的论文')

    const openButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('查看进度'))
    await openButton.trigger('click')
    await flushPromises()

    // L2 阅读工作区：有返回入口，库页的历史卡片收起（库与读不再同屏抢位置）
    expect(wrapper.text()).toContain('← 我的论文')
    expect(wrapper.find('.history-card').exists()).toBe(false)

    const back = wrapper
      .findAll('button')
      .find((b) => b.text().includes('← 我的论文'))
    await back.trigger('click')
    await flushPromises()

    expect(wrapper.find('.history-card').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('← 我的论文')
    for (const leak of SOURCE_LEAKS) {
      expect(wrapper.text()).not.toContain(leak)
    }
  })

  it('出处一律说人话：显示「第 X 页 · 第 Y 段」而不是块编号，且段号按页内重算', async () => {
    localStorage.setItem('docwise_token', 'test-token')
    const base = stubFetch()
    const done = {
      ...TASK,
      status: 'completed',
      progress: 1,
      stage: null,
      eta_seconds: null,
      finished_at: '2026-09-10T12:05:00',
    }
    const detail = {
      ...TASK_DETAIL,
      ...done,
      files_ready: { mono: true, dual: false },
      engine_progress: null,
      blocks: [
        { block_id: 'p0_b0', text: 'first', translated: '第一块', status: 'success', error: null },
        { block_id: 'p0_b1', text: 'second', translated: '第二块', status: 'success', error: null },
        // 全局块序是 2，但它是**第 2 页的第 1 段**——直接把 b 当段号就会显示"第 3 段"
        { block_id: 'p1_b2', text: 'third', translated: '第三块', status: 'success', error: null },
      ],
    }
    const answer = { answer: '按原文所述，这条结论有两条局限。', source_block_ids: ['p1_b2'], mode: 'full' }
    globalThis.fetch = vi.fn(async (input, init = {}) => {
      const url = typeof input === 'string' ? input : String(input?.url ?? input)
      const json = (data) => ({ ok: true, status: 200, json: async () => data })
      if (url.includes('/ask')) return json(answer)
      if (url.match(/\/api\/tasks\/7\/?$/)) return json(detail)
      if (url.includes('/api/tasks')) return json([done])
      return base(input, init)
    })

    wrapper = mountApp()
    await flushPromises()
    const openButton = wrapper
      .findAll('button')
      .find((b) => b.text().includes('继续读'))
    await openButton.trigger('click')
    await flushPromises()

    // 快捷提问 chips 应该只放"导读与术语都没答"的问题
    expect(wrapper.text()).toContain('这项研究有什么局限？')
    const chip = wrapper
      .findAll('button')
      .find((b) => b.text().includes('这项研究有什么局限？'))
    await chip.trigger('click')
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('第 2 页 · 第 1 段')
    expect(text).not.toContain('p1_b2') // 块编号只留给排查，不出现在界面上
    for (const leak of SOURCE_LEAKS) {
      expect(text).not.toContain(leak)
    }
  })
})
