/**
 * 版本历史面板（2026-10-19）。
 *
 * 为什么必须有：这一天起 **AI 能直接往正文里写**，写入是自动落地的。
 * 20 秒撤销只兜"刚写完那一下"，隔天想回到"AI 动手之前"只能靠版本。
 *
 * 盯三件事：
 *  ① 助手栏有「版本」页签，点开才拉列表；
 *  ② 列表只显示 来源 + 时间 + 字数，**不带正文**；
 *  ③ 「查看」与「回滚」分开——点一条不许直接改稿。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const VERSIONS = [
  { id: 9, source: 'user', note: null, created_at: '2026-10-19T02:00:00Z', chars: 120 },
  { id: 8, source: 'restore', note: null, created_at: '2026-10-19T01:40:00Z', chars: 96 },
]

const DRAFT = {
  id: 1,
  title: '开题报告',
  body_md: '# 开题报告\n\n正文。',
  body_html: '<h1>开题报告</h1><p>正文。</p>',
  template_id: null,
  updated_at: '2026-10-19T02:00:00Z',
  citations: [],
}

vi.mock('../src/auth', () => {
  const ok = (data) => ({ ok: true, status: 200, json: async () => data })
  const handler = (url) => {
    const path = String(url)
    if (path.includes('/versions/9')) {
      return ok({
        id: 9,
        body_md: '第九版正文',
        body_html: '<p>第九版正文</p>',
        source: 'user',
        created_at: '2026-10-19T02:00:00Z',
      })
    }
    if (path.includes('/versions')) return ok({ items: VERSIONS })
    if (path.includes('/drafts')) return ok({ items: [DRAFT] })
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

function mountWrite() {
  return mount(WriteView, { attachTo: document.body })
}

async function openVersions(wrapper) {
  const tab = wrapper.findAll('.wr-helper .tabs button').find((b) => b.text() === '版本')
  expect(tab, '助手栏没有「版本」页签').toBeTruthy()
  await tab.trigger('click')
  await flushPromises()
}

describe('写作页 · 版本历史', () => {
  beforeEach(() => {
    resetWrite()
  })

  it('助手栏有「版本」页签，点开之后面板出现', async () => {
    const wrapper = mountWrite()
    await flushPromises()
    expect(wrapper.findAll('.wr-helper .tabs button').map((b) => b.text())).toContain('版本')

    await openVersions(wrapper)
    expect(wrapper.find('.wr-versions').exists()).toBe(true)
    wrapper.unmount()
  })

  it('列表只显示来源/时间/字数（正文不预加载）', async () => {
    const wrapper = mountWrite()
    await flushPromises()
    await openVersions(wrapper)

    const text = wrapper.find('.wr-versions').text()
    expect(text).toContain('手动保存')
    expect(text).toContain('回滚前留档')
    expect(text).toContain('120 字')
    expect(text).not.toContain('第九版正文')
    wrapper.unmount()
  })

  it('点「查看」才读出正文；「回滚」是另一个按钮', async () => {
    const wrapper = mountWrite()
    await flushPromises()
    await openVersions(wrapper)

    const viewBtn = wrapper.findAll('.wr-versions button').find((b) => b.text() === '查看')
    await viewBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.wr-verpreview').text()).toContain('第九版正文')

    const restoreBtn = wrapper.findAll('.wr-versions button').find((b) => b.text() === '回滚')
    expect(restoreBtn).toBeTruthy()
    wrapper.unmount()
  })
})
