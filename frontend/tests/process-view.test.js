/**
 * E15「处理过程」一屏（`views/ProcessView.vue`，`#/process`）的用例。
 *
 * 这一屏是**「AI 每个环节做了什么」的界面版证据**（数据源＝环节台账 `memory_events`，契约 N17；
 * 与「我的 · AI 使用台账」同源），所以用例盯的是"披露有没有被含糊过去"：
 *
 * ① 台账条目按**新的在前**渲染（桩故意乱序给，页面必须自己排对）；
 * ② ⭐ `actor` 的芯片文案**逐字**对数据模型契约 §2.8
 *    （`▲ 正文发往模型 API` / `● 不出本机`）——这一列就是"数据流向的证据"；
 * ③ `payload` 默认收起、点了才展开；**没有 payload 就不给控件**（别摆一个点不动的按钮）；
 * ④ 空态必须说**为什么没有**，且分清"一条都没跑过"与"只是这个筛选下没有"；
 * ⑤ 左栏「处理过程」**真的接上了** `#/process`（源码结构断言，防它又被塞回"还没做"那张表）；
 * ⑥ 窄档不许溢出的样式契约（JSON 自己横滚、手机档给标签栏让位、**不许出现 `100vw`**）。
 */

import { readFileSync } from 'node:fs'

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { parseHash } from '../src/router'
import ProcessView from '../src/views/ProcessView.vue'

/** 桩：**故意把新的那条放后面**（id 1 时间更早），页面必须自己排成"新的在前"。 */
const EVENTS = [
  {
    id: 1,
    task_id: 42,
    layer: 'L0',
    stage: 'extract',
    actor: 'local',
    tool: 'text-layer',
    summary: '抽取文字层：42 块',
    payload: { blocks: 42, text_source: 'text-layer' },
    created_at: '2026-10-15T02:00:00Z',
  },
  {
    id: 2,
    task_id: 42,
    layer: 'L0',
    stage: 'translate',
    actor: 'api',
    tool: 'engine',
    summary: '翻译完成：42/42 块有译文',
    payload: null,
    created_at: '2026-10-15T03:30:00Z',
  },
]

function json(status, body) {
  return {
    ok: status < 400,
    status,
    json: async () => body,
    blob: async () => ({ size: 1, type: 'application/octet-stream' }),
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
  }
}

/** 一个极简的「后端」：只认这一屏用到的三条路（`/api/tasks`、`/api/memory-events`、台账导出）。 */
function stubApi({ tasks = [{ id: 42, filename: '化学 arXiv' }], events = EVENTS, onEvents } = {}) {
  const calls = []
  const fetchMock = vi.fn(async (url) => {
    const raw = String(url)
    const [path, search = ''] = raw.split('?')
    const query = new URLSearchParams(search)
    calls.push(raw)
    if (path.endsWith('/api/tasks')) return json(200, tasks)
    if (path.endsWith('/api/memory-events')) {
      return json(200, onEvents ? onEvents(query) : { items: events })
    }
    if (path.endsWith('/api/me/ledger')) return json(200, 'stage,actor\n')
    return json(404, { detail: '没这条路由' })
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

async function mountProc(options) {
  const calls = stubApi(options)
  const wrapper = mount(ProcessView)
  await flushPromises()
  return { wrapper, calls }
}

/** 源码读取：本项目既有做法（结构断言用，见 `mount-points.test.js`）。 */
function srcText(relative) {
  return readFileSync(new URL(relative, import.meta.url), 'utf8')
}

beforeEach(() => {
  localStorage.clear()
  // 导出那步在 happy-dom 里没有实现，替换掉（这一屏只用它触发下载）
  URL.createObjectURL = vi.fn(() => 'blob:process-view')
  URL.revokeObjectURL = vi.fn()
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('E15 处理过程一屏', () => {
  it('台账条目渲染出来，且**新的在前**（桩给的是乱序）', async () => {
    const { wrapper } = await mountProc()

    const sums = wrapper.findAll('.proc-sum').map((node) => node.text())
    expect(sums).toEqual(['翻译完成：42/42 块有译文', '抽取文字层：42 块'])
    // 时间是人话格式（不裸露 ISO 串），且**不是**把函数源码印在页面上
    const at = wrapper.findAll('.proc-at').map((node) => node.text())
    expect(at[0]).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)
    expect(wrapper.text()).not.toMatch(/function |=>|\{\{/)
  })

  it('⭐ 流向芯片逐字对契约：api =「▲ 正文发往模型 API」、local =「● 不出本机」', async () => {
    const { wrapper } = await mountProc()

    const chips = wrapper.findAll('.proc-flow')
    expect(chips).toHaveLength(2)
    // ⚠️ 这两串是**证据的一部分**，改一个字符等于改了对外口径
    expect(wrapper.get('.proc-flow.is-api').text()).toBe('▲ 正文发往模型 API')
    expect(wrapper.get('.proc-flow.is-local').text()).toBe('● 不出本机')
    // 形状也要分得开（色盲安全）：两枚芯片不许用同一个类
    expect(wrapper.get('.proc-flow.is-api').classes()).toContain('is-api')
    expect(wrapper.get('.proc-flow.is-local').classes()).toContain('is-local')
  })

  it('payload 默认收起、点了才展开；**没有 payload 就不给控件**', async () => {
    const { wrapper } = await mountProc()

    // 默认：一条明细都不展开
    expect(wrapper.find('.proc-json').exists()).toBe(false)
    const items = wrapper.findAll('.proc-item')
    // 只有带 payload 的那条有控件（另一条 payload=null）
    expect(items[0].find('.proc-more').exists()).toBe(false)
    expect(items[1].find('.proc-more').text()).toBe('看明细')

    await items[1].get('.proc-more').trigger('click')
    expect(items[1].get('.proc-json').text()).toContain('"blocks": 42')
    expect(items[1].get('.proc-more').text()).toBe('收起明细')

    await items[1].get('.proc-more').trigger('click')
    expect(items[1].find('.proc-json').exists()).toBe(false)
  })

  it('空态说**为什么**没有（一条都没跑过 → 指出跑一次就会出现）', async () => {
    const { wrapper } = await mountProc({ events: [] })

    const empty = wrapper.get('.proc-empty').text()
    expect(empty).toContain('还没有环节记录')
    expect(empty).toContain('上传并跑一篇文献')
    expect(wrapper.findAll('.proc-item')).toHaveLength(0)
  })

  it('空态分清两种"没有"：筛选下没有 ≠ 一条都没跑过', async () => {
    const { wrapper } = await mountProc({
      onEvents: (query) => (query.get('task_id') === '42' ? { items: [] } : { items: EVENTS }),
    })
    // 先看"有数据"的样子
    expect(wrapper.findAll('.proc-item')).toHaveLength(2)

    // 选了某一篇之后后端回空 → 文案必须换成"当前筛选下没有"
    await wrapper.findAll('select')[0].setValue('42')
    await flushPromises()
    const empty = wrapper.get('.proc-empty').text()
    expect(empty).toContain('当前筛选下没有记录')
    expect(empty).not.toContain('还没有环节记录')
  })

  it('取不到就如实说，并且**不拿假数据顶**（错误态整屏为空 + 说原因）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        const path = String(url).split('?')[0]
        if (path.endsWith('/api/memory-events')) throw new Error('boom')
        return json(200, [])
      }),
    )
    const wrapper = mount(ProcessView)
    await flushPromises()

    expect(wrapper.get('.hnote-text').text()).toContain('台账暂时取不到')
    expect(wrapper.get('.hnote-text').text()).toContain('不拿假数据顶')
    expect(wrapper.findAll('.proc-item')).toHaveLength(0)
  })

  it('导出复用已有的台账端点（同一张表，不另造一套）', async () => {
    const { wrapper, calls } = await mountProc()

    await wrapper.get('.proc-csv').trigger('click')
    await flushPromises()
    expect(calls.some((url) => url.includes('/api/me/ledger?format=csv'))).toBe(true)

    await wrapper.get('.proc-md').trigger('click')
    await flushPromises()
    expect(calls.some((url) => url.includes('/api/me/ledger?format=md'))).toBe(true)
  })

  it('⭐ 左栏「处理过程」真的接上了 #/process（不是"还没做"的提示）', () => {
    const app = srcText('../src/App.vue')

    // 路由表的真源就在 router.js 里（`#/process` 本来就认识）
    expect(parseHash('#/process')).toEqual({ name: 'process', params: {} })
    // 左栏那张表的这一项必须是"真跳"，**不许**再有 note（有 note 就只会弹提示）
    expect(app).toMatch(/process:\s*\{\s*go:\s*\{\s*name:\s*'process'\s*\}\s*\}/)
    expect(app).not.toMatch(/process:\s*'处理过程页'/)
    // 屏也要挂上（且排在阅读区之前，否则"读着一篇 + 点处理过程"会被 currentTask 吃掉）
    expect(app).toMatch(/<ProcessView\s*\/>/)
    expect(app).toMatch(/view === 'process'/)
  })

  it('窄档不溢出的样式契约：JSON 自己横滚 + 手机档给标签栏让位 + 不许出现 100vw', () => {
    const css = srcText('../src/style.css')
    const start = css.indexOf('[E15]')
    expect(start).toBeGreaterThan(-1)
    // ⚠️ `[E15]` 本身写在**注释块内部**，所以要**从注释的起点**切，
    //    否则切片从注释中间开始、开头的 `/*` 不在切片里，注释根本剥不掉（实测踩过）。
    const commentStart = css.lastIndexOf('/*', start)
    const section = css.slice(commentStart < 0 ? start : commentStart)

    expect(section).toMatch(/\.dw \.proc-json\s*\{[^}]*overflow-x:\s*auto/)
    expect(section).toMatch(/@media \(max-width: 719px\)/)
    // 手机档底部要给 R6 的标签栏（含安全区）让位，否则最后一条被盖住
    expect(section).toMatch(/var\(--tabbar-h[\s\S]*env\(safe-area-inset-bottom/)
    // 窄屏判据：这一屏**不许**用 100vw 撑宽整页
    // ⚠️ 必须**剥掉注释再判**：这段的注释里正大光明写着「不写 `100vw`」，
    //    直接 not.toContain 会被自己的说明文字判红（自指假红，实测踩过）。
    const declarations = section.replace(/\/\*[\s\S]*?\*\//g, '')
    expect(declarations).not.toContain('100vw')
  })
})
