/**
 * 助手栏六个页签的**互斥渲染**（2026-10-19 真出过 bug）。
 *
 * 现象（用户截图）：对话页签里输入框压到快捷问题上，下面还冒出「素材 · 1」——
 * 因为素材面板当时是无条件渲染的，等于两个面板叠在一个容器里。
 * 这类 bug 不会报错、也不会让任何单测变红，只能靠"同一时刻只许有一个面板"这条断言拦住。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const DRAFT = {
  id: 1,
  title: '开题报告',
  body_md: '# 开题报告\n\n正文。',
  body_html: '<h1>开题报告</h1><p>正文。</p>',
  template_id: null,
  updated_at: '2026-10-19T02:00:00Z',
  citations: [],
}

const MATERIAL = {
  id: 7,
  text_quote: '原句',
  translated_quote: '译文',
  page: 1,
  source_name: 'math_arXiv.pdf',
  note: '',
  task_id: 41,
  block_id: 'p0_b2',
  deleted_at: null,
  created_at: '2026-10-19T01:00:00Z',
}

vi.mock('../src/auth', () => {
  const ok = (data) => ({ ok: true, status: 200, json: async () => data })
  const handler = (url) => {
    const path = String(url)
    if (path.includes('/versions')) return ok({ items: [] })
    if (path.includes('/drafts')) return ok({ items: [DRAFT] })
    if (path.includes('/materials')) return ok({ items: [MATERIAL] })
    return ok({})
  }
  return {
    authFetch: async (url) => handler(url),
    apiJson: async (url) => (await handler(url)).json(),
  }
})

vi.mock('../src/components/WriteEditor.vue', () => import('./helpers/WriteEditorStub.js'))

import WriteView from '../src/views/WriteView.vue'
import { resetWrite } from '../src/stores/useWrite'

const PANES = ['.wr-matpane', '.wr-chat', '.wr-versions']

function visiblePanes(wrapper) {
  return PANES.filter((sel) => wrapper.find(sel).exists())
}

describe('写作页 · 助手页签互斥', () => {
  beforeEach(() => {
    resetWrite()
  })

  it('同一时刻只有一个面板（素材 / 对话 / 版本）', async () => {
    const wrapper = mount(WriteView, { attachTo: document.body })
    await flushPromises()

    for (const [label, expected] of [
      ['素材', '.wr-matpane'],
      ['对话', '.wr-chat'],
      ['版本', '.wr-versions'],
    ]) {
      const tab = wrapper.findAll('.wr-helper .tabs button').find((b) => b.text() === label)
      await tab.trigger('click')
      await flushPromises()
      expect(visiblePanes(wrapper), `选中「${label}」时面板不对`).toEqual([expected])
    }
    wrapper.unmount()
  })

  it('对话页签里输入框在面板底部（不压在快捷问题上）', async () => {
    const wrapper = mount(WriteView, { attachTo: document.body })
    await flushPromises()
    const tab = wrapper.findAll('.wr-helper .tabs button').find((b) => b.text() === '对话')
    await tab.trigger('click')
    await flushPromises()

    // 结构口径：输入框是 `.wr-chat` 的子节点，且 `.wr-chat` 里**没有**素材面板
    expect(wrapper.find('.wr-chat .agent-composer').exists()).toBe(true)
    expect(wrapper.find('.wr-chat .wr-matpane').exists()).toBe(false)
    wrapper.unmount()
  })
})
