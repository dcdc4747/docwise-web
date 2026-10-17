/**
 * M7「记忆」页（`views/MemoryView.vue`，`#/memory`）的用例。
 *
 * 这一页记的是**这个人的用法偏好**，所以用例盯的是"有没有把它说实、做对"：
 *
 * 1. ⭐ **"用过几次"如实**：0 次就是"还没用过"（不许说成"常用"，也不许当"聪明度"吹）；
 * 2. ⭐ **空态说清"为什么空"**：尤其"改过的句子"那一栏——**不许写"暂无数据"敷衍，
 *    也不许写"正在学习"骗人**，要说清门槛（两周 / 500 段）与现状；
 * 3. ⭐ **能改、能停用、能删**：停用后仍看得见（"先别用，但别丢"）；
 * 4. ⭐ **删除给撤销窗口**（设计规范 §7.7）：点「删」**不立刻发请求**，5 秒内能撤回；
 * 5. ⭐ **校验缺哪边说哪边**：别弹一句"输入有误"了事；
 * 6. ⭐ **接线的结构守卫**：`#/memory` 真的从"还没做"那张表里摘掉了、`PAGES` 里有它
 *    ——否则左栏点了只 toast 回库页。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  CITE_OPTIONS,
  EDITED_EMPTY_TEXT,
  citeLabel,
  countsText,
  emptyTextFor,
  hitsText,
  isPaused,
  validateTerm,
} from '../src/memoryText'
import MemoryView from '../src/views/MemoryView.vue'

const readSrc = (rel) => readFileSync(resolve(process.cwd(), rel), 'utf8')

const json = (status, body) => ({
  ok: status < 400,
  status,
  json: async () => body,
  text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
})

/** 极简「后端」：只认这一页用到的三条路（列表 / 写入 / 单条改删）。 */
function stubApi({ items = [], counts = { term: 0, cite: 0 } } = {}) {
  const calls = []
  const state = { items: [...items] }
  const fetchMock = vi.fn(async (url, options = {}) => {
    const raw = String(url)
    const [path] = raw.split('?')
    const method = String(options.method || 'GET').toUpperCase()
    calls.push({ method, path, body: options.body ? JSON.parse(options.body) : null })

    if (path.endsWith('/api/memories') && method === 'GET') {
      const term = state.items.filter((i) => i.kind === 'term').length
      const cite = state.items.filter((i) => i.kind === 'cite').length
      // ⚠️ 返回**副本**：真接口每次都是新解析出来的 JSON 数组；
      // 同一个引用回去 Vue 会认为"没变"、不重渲染（第一版桩就这么坑过自己）。
      const items = state.items.map((i) => ({ ...i }))
      return json(200, { items, counts: { term, cite }, enabled_counts: { term, cite } })
    }
    if (path.endsWith('/api/memories') && method === 'POST') {
      const body = JSON.parse(options.body)
      const hit = state.items.find((i) => i.kind === body.kind && i.source === body.source)
      if (hit) {
        hit.target = body.target
        return json(201, { item: hit, created: false })
      }
      const created = {
        id: state.items.length + 1,
        kind: body.kind,
        source: body.source,
        target: body.target,
        hits: 0,
        enabled: true,
      }
      state.items.push(created)
      return json(201, { item: created, created: true })
    }
    if (method === 'PATCH') {
      const id = Number(path.split('/').pop())
      const hit = state.items.find((i) => i.id === id)
      const body = JSON.parse(options.body)
      Object.assign(hit, body)
      return json(200, { item: hit })
    }
    if (method === 'DELETE') {
      const id = Number(path.split('/').pop())
      state.items = state.items.filter((i) => i.id !== id)
      return json(200, { deleted: true, id })
    }
    return json(404, { detail: '没这条路由' })
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

async function mountMem(options) {
  const calls = stubApi(options)
  const wrapper = mount(MemoryView)
  await flushPromises()
  return { wrapper, calls }
}

const TERM = {
  id: 1,
  kind: 'term',
  source: 'chiral',
  target: '手性',
  hits: 0,
  enabled: true,
}

const CITE = {
  id: 2,
  kind: 'cite',
  source: 'default',
  target: 'author-year',
  hits: 3,
  enabled: true,
}

beforeEach(() => {
  vi.unstubAllGlobals()
})

afterEach(() => {
  vi.useRealTimers()
})

/* ---------------------------------------------------------------- 纯逻辑 */

describe('记忆文案的纯逻辑', () => {
  it('⭐ 0 次说成"还没用过"，不是"常用"', () => {
    expect(hitsText(0)).toBe('还没用过')
    expect(hitsText(1)).toBe('用过 1 次')
    expect(hitsText(12)).toBe('用过 12 次')
  })

  it('坏数据不编数字', () => {
    expect(hitsText(-1)).toBe('—')
    expect(hitsText('x')).toBe('—')
    expect(hitsText(undefined)).toBe('—')
  })

  it('引用格式：认识的给人话，不认识的原样显示（不许编）', () => {
    expect(citeLabel('author-year')).toContain('作者-年份')
    expect(citeLabel('numeric')).toContain('数字编号')
    expect(citeLabel('hanging')).toBe('hanging')
    expect(citeLabel('')).toBe('')
    expect(CITE_OPTIONS.length).toBeGreaterThanOrEqual(2)
  })

  it('⭐ 空态分种类说，不是一句"暂无数据"', () => {
    expect(emptyTextFor('term')).toContain('还没有术语习惯')
    expect(emptyTextFor('cite')).toContain('还没有设引用格式')
    expect(emptyTextFor('term')).not.toBe(emptyTextFor('cite'))
    expect(emptyTextFor('term')).not.toContain('暂无数据')
  })

  it('⭐ "改过的句子"那段说清门槛，不敷衍也不骗人', () => {
    expect(EDITED_EMPTY_TEXT).toContain('两周')
    expect(EDITED_EMPTY_TEXT).toContain('500')
    // 不许用这两句话糊弄过去
    expect(EDITED_EMPTY_TEXT).not.toContain('暂无数据')
    expect(EDITED_EMPTY_TEXT).not.toContain('正在学习')
  })

  it('校验缺哪边说哪边', () => {
    expect(validateTerm('', '手性')).toMatchObject({ ok: false, error: expect.stringContaining('原文') })
    expect(validateTerm('chiral', '')).toMatchObject({ ok: false, error: expect.stringContaining('习惯') })
    expect(validateTerm('  chiral  ', ' 手性 ')).toEqual({
      ok: true,
      source: 'chiral',
      target: '手性',
      error: '',
    })
    expect(validateTerm('x'.repeat(300), 'y').ok).toBe(false)
  })

  it('概况文案', () => {
    expect(countsText({ term: 0, cite: 0 })).toBe('还没有任何记忆')
    expect(countsText({ term: 3, cite: 1 })).toBe('术语 3 条 · 引用 1 条')
    expect(countsText({ term: 2 })).toBe('术语 2 条')
  })

  it('停用状态认得出来', () => {
    expect(isPaused({ enabled: false })).toBe(true)
    expect(isPaused({ enabled: true })).toBe(false)
    expect(isPaused(null)).toBe(false)
  })
})

/* ---------------------------------------------------------------- 页面 */

describe('记忆页', () => {
  it('⭐ 一条都没有时如实说"还没有"，并给出怎么加的话', async () => {
    const { wrapper } = await mountMem({ items: [], counts: { term: 0, cite: 0 } })
    const text = wrapper.text()
    expect(text).toContain('还没有任何记忆')
    expect(text).toContain('还没有术语习惯')
    expect(text).toContain('还没有设引用格式')
    // 三条都要在，别只画一个空框
    expect(wrapper.find('.mem-add').exists()).toBe(true)
  })

  it('列表把术语与引用分开展示，并显示"用过几次"', async () => {
    const { wrapper } = await mountMem({ items: [TERM, CITE] })
    const text = wrapper.text()
    expect(text).toContain('chiral')
    expect(text).toContain('手性')
    expect(text).toContain('还没用过') // 术语 0 次
    expect(text).toContain('用过 3 次') // 引用 3 次
    expect(text).toContain('作者-年份')
  })

  it('⭐ 加一条：校验不过就不发请求，并说缺哪边', async () => {
    const { wrapper, calls } = await mountMem({ items: [] })
    await wrapper.get('.mem-add').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('不能为空')
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0)
  })

  it('加一条成功：POST 带上 kind/source/target，输入框清空', async () => {
    const { wrapper, calls } = await mountMem({ items: [] })
    await wrapper.get('.mem-new-src').setValue('chiral')
    await wrapper.get('.mem-new-dst').setValue('手性')
    await wrapper.get('.mem-add').trigger('submit')
    await flushPromises()
    const post = calls.find((c) => c.method === 'POST')
    expect(post.body).toEqual({ kind: 'term', source: 'chiral', target: '手性' })
    expect(wrapper.text()).toContain('手性')
  })

  it('⭐ 改说法：PATCH 只带 target（不重发 source）', async () => {
    const { wrapper, calls } = await mountMem({ items: [TERM] })
    await wrapper.get('.mem-edit').trigger('click')
    const inputs = wrapper.findAll('.mem-input')
    // 第 0 个是"原文里怎么写"（只读），第 1 个是"你习惯叫什么"
    expect(inputs[0].attributes('readonly')).toBeDefined()
    await inputs[1].setValue('手征性')
    await wrapper.get('.mem-save').trigger('click')
    await flushPromises()
    const patch = calls.find((c) => c.method === 'PATCH')
    expect(patch.body).toEqual({ target: '手征性' })
    expect(wrapper.text()).toContain('手征性')
  })

  it('⭐ 停用之后还看得见，并标着"已停用（不注入）"', async () => {
    const { wrapper, calls } = await mountMem({ items: [TERM] })
    await wrapper.get('.mem-toggle').trigger('click')
    await flushPromises()
    const patch = calls.find((c) => c.method === 'PATCH')
    expect(patch.body).toEqual({ enabled: false })
    expect(wrapper.text()).toContain('已停用（不注入）')
    // 仍然列着（"先别用，但别丢"）
    expect(wrapper.text()).toContain('chiral')
  })

  it('⭐ 删除先给 5 秒撤销窗口，到点才真发 DELETE', async () => {
    vi.useFakeTimers()
    const { wrapper, calls } = await mountMem({ items: [TERM] })

    await wrapper.get('.mem-del').trigger('click')
    // 点了删，**还没真删**
    expect(calls.filter((c) => c.method === 'DELETE')).toHaveLength(0)
    expect(wrapper.find('.mem-undo').exists()).toBe(true)

    // 到点才真删
    await vi.advanceTimersByTimeAsync(5200)
    await flushPromises()
    expect(calls.filter((c) => c.method === 'DELETE')).toHaveLength(1)
  })

  it('⭐ 5 秒内撤销 → 一条 DELETE 都不发，行还在', async () => {
    vi.useFakeTimers()
    const { wrapper, calls } = await mountMem({ items: [TERM] })

    await wrapper.get('.mem-del').trigger('click')
    await wrapper.get('.mem-undo').trigger('click')
    await vi.advanceTimersByTimeAsync(6000)
    await flushPromises()

    expect(calls.filter((c) => c.method === 'DELETE')).toHaveLength(0)
    expect(wrapper.text()).toContain('chiral')
  })

  it('引用习惯选了就存（POST kind=cite, source=default）', async () => {
    const { wrapper, calls } = await mountMem({ items: [] })
    await wrapper.get('.mem-select-new').setValue('numeric')
    await flushPromises()
    const post = calls.find((c) => c.method === 'POST')
    expect(post.body).toEqual({ kind: 'cite', source: 'default', target: 'numeric' })
  })

  it('取不到就如实说，不拿假数据顶', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(500, { detail: '炸了' })),
    )
    const wrapper = mount(MemoryView)
    await flushPromises()
    expect(wrapper.text()).toContain('记忆暂时取不到')
    expect(wrapper.text()).toContain('不拿假数据顶')
  })
})

/* ---------------------------------------------------------------- 接线（结构守卫） */

describe('接线：这页真能打开', () => {
  it('⭐ `#/memory` 不再被"还没做"那张表挡住，且真渲染 MemoryView', () => {
    const app = readSrc('src/App.vue')
    // 左栏那条要真跳转（不是弹一句 toast）
    expect(app).toMatch(/memory:\s*\{\s*go:\s*\{\s*name:\s*'memory'\s*\}/)
    // 页面必须真渲染（否则点了地址变了、屏没变）
    expect(app).toContain("view === 'memory'")
    expect(app).toContain('<MemoryView')
    // `PAGES` 得认识 memory，否则 `view` 会被算成 'library'
    expect(app).toMatch(/PAGES = \{[^}]*memory:\s*'memory'/)
  })

  it('⚠️ 不许再出现"记忆页还没做"这种把用户挡在门外的文案', () => {
    const app = readSrc('src/App.vue')
    expect(app).not.toContain('记忆页（形态 v2 的 M7）还没做')
  })

  it('窄屏排版：标签不许断在词中间（`.mem-field` 可换行 + 标签 `nowrap`）', () => {
    // ⚠️ 实拍抓到过：390 下「插引文默认用」被挤成「插引文默 / 认用」。
    // 这类问题构建不报、用例不报，只能靠截图发现 —— 所以用两条 CSS 断言钉住。
    const css = readSrc('src/style.css')
    const at = css.indexOf('.dw .mem-field {')
    expect(at, 'style.css 里没有 .mem-field 规则').toBeGreaterThan(-1)
    const block = css.slice(at, css.indexOf('}', at))
    expect(block).toMatch(/flex-wrap:\s*wrap/)
    expect(css).toMatch(/\.dw \.mem-field > span \{[^}]*white-space:\s*nowrap/)
  })
})
