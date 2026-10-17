/**
 * E2「素材库」页（`views/MaterialsView.vue`，`#/materials`）的用例。
 *
 * 这一页解决的问题是"素材存下来了却查不了"，所以用例盯的是**查得对不对、说得实不实**：
 *
 * 1. ⭐ **筛选走后端**：选集合/标签 → 请求里必须带 `collection_id` / `tag`（**不靠前端过滤**，
 *    否则会与 N13 的口径悄悄不一致：`task_id` 为 null 的卡不属于任何集合）；
 * 2. ⭐ **空态分两种**：真空给"怎么产生第一条"，筛空给出口；
 * 3. ⭐ **筛选项取不到也要能看素材**，但要如实说"下拉里只有全部"；
 * 4. ⭐ **出错不拿假数据顶**；
 * 5. ⭐ **接线**：`#/materials` 真能打开（路由 + 切屏 + 左栏目标），否则点了只弹提示。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { parseHash } from '../src/router'
import {
  collectionNameOf,
  countsText,
  emptyText,
  filtersText,
  sourceLabel,
  sourceState,
} from '../src/materialsText'
import { resetMaterials } from '../src/stores/useMaterials'
import MaterialsView from '../src/views/MaterialsView.vue'

const readSrc = (rel) => readFileSync(resolve(process.cwd(), rel), 'utf8')

const json = (status, body) => ({
  ok: status < 400,
  status,
  json: async () => body,
  text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
})

const MAT = {
  id: 7,
  text_quote: 'chiral measures are pseudoscalars',
  translated_quote: '手性测度是赝标量',
  page: 3,
  source_name: 'chem_arXiv.pdf',
  note: null,
  task_id: 41,
  block_id: 'p3_b41',
  created_at: '2026-10-17T02:00:00Z',
}

/** 极简「后端」：只认这一屏用到的三条路（素材 / 集合 / 标签）。 */
function stubApi({ materials = [MAT], collections, tags, onMaterials } = {}) {
  const calls = []
  const fetchMock = vi.fn(async (url) => {
    const raw = String(url)
    const [path, search = ''] = raw.split('?')
    const query = new URLSearchParams(search)
    calls.push({ path, query: Object.fromEntries(query) })
    if (path.endsWith('/api/materials')) {
      return onMaterials ? onMaterials(query) : json(200, { items: materials })
    }
    if (path.endsWith('/api/collections')) {
      if (collections === null) return json(500, { detail: '炸了' })
      return json(200, { items: collections ?? [{ id: 1, name: '化学', doc_count: 2 }] })
    }
    if (path.endsWith('/api/tags')) {
      if (tags === null) return json(500, { detail: '炸了' })
      return json(200, { items: tags ?? [{ id: 1, name: '方法', kind: 'topic', doc_count: 1 }] })
    }
    return json(404, { detail: '没这条路由' })
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

async function mountMats(options) {
  const calls = stubApi(options)
  const wrapper = mount(MaterialsView)
  await flushPromises()
  return { wrapper, calls }
}

const materialsCalls = (calls) => calls.filter((c) => c.path.endsWith('/api/materials'))

beforeEach(() => {
  resetMaterials()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

/* ---------------------------------------------------------------- 纯逻辑 */

describe('素材库文案的纯逻辑', () => {
  it('量：0 条说"还没有"，其余说"共 N 条"', () => {
    expect(countsText(0)).toBe('还没有素材卡')
    expect(countsText(3)).toBe('共 3 条')
    expect(countsText('x')).toBe('—')
  })

  it('⭐ 有筛选时量换个说法（否则与空态打架：顶部说"一张都没有"、下面说"筛选下没有"）', () => {
    expect(countsText(0, { hasFilters: true })).toBe('本筛选 0 条')
    expect(countsText(3, { hasFilters: true })).toBe('本筛选 3 条')
    // 有筛选时**绝不许**说"还没有素材卡"
    expect(countsText(0, { hasFilters: true })).not.toContain('还没有')
  })

  it('⭐ 空态两种，不能混成"暂无数据"', () => {
    const none = emptyText({ hasFilters: false })
    const filtered = emptyText({ hasFilters: true })
    expect(none).toContain('还没有素材卡')
    expect(none).toContain('存为素材卡')
    expect(filtered).toContain('这个筛选下没有')
    expect(filtered).toContain('清空筛选')
    expect(none).not.toBe(filtered)
    expect(none).not.toContain('暂无数据')
  })

  it('筛选摘要：不筛也要明说"全部素材"', () => {
    expect(filtersText({})).toBe('全部素材')
    expect(filtersText({ collectionName: '化学' })).toBe('集合：化学')
    expect(filtersText({ collectionName: '化学', tag: '方法' })).toBe('集合：化学 · 标签：方法')
  })

  it('⭐ 出处三种状态分开说（别把"源文献已删"当正常卡）', () => {
    expect(sourceState({ task_id: 41, block_id: 'p0_b1' })).toMatchObject({ canLocate: true })
    expect(sourceState({ task_id: 41, block_id: '' })).toMatchObject({
      canOpen: true,
      canLocate: false,
    })
    const gone = sourceState({ task_id: null, block_id: 'p0_b1' })
    expect(gone.canOpen).toBe(false)
    expect(gone.reason).toContain('源文献已删除')
  })

  it('出处那一行的人话（页号缺失就说待定）', () => {
    expect(sourceLabel({ source_name: 'a.pdf', page: 3 })).toBe('a.pdf · 第 3 页')
    expect(sourceLabel({ source_name: 'a.pdf' })).toContain('页码待定')
    expect(sourceLabel({})).toContain('源文献名缺失')
  })

  it('集合名查不到就回空串，不用 id 冒充名字', () => {
    expect(collectionNameOf([{ id: 1, name: '化学' }], 1)).toBe('化学')
    expect(collectionNameOf([{ id: 1, name: '化学' }], 9)).toBe('')
    expect(collectionNameOf([], '')).toBe('')
  })
})

/* ---------------------------------------------------------------- 页面 */

describe('素材库页', () => {
  it('打开就取素材，并把卡片列出来', async () => {
    const { wrapper, calls } = await mountMats()
    expect(materialsCalls(calls)).toHaveLength(1)
    expect(wrapper.text()).toContain('共 1 条')
    expect(wrapper.text()).toContain('手性测度是赝标量')
  })

  it('⭐ 选集合 → 请求带 collection_id（筛选走后端）', async () => {
    const { wrapper, calls } = await mountMats({
      collections: [
        { id: 1, name: '化学', doc_count: 2 },
        { id: 2, name: '数学', doc_count: 1 },
      ],
    })
    await wrapper.get('.mats-collection').setValue('2')
    await flushPromises()
    const last = materialsCalls(calls).at(-1)
    expect(last.query).toEqual({ collection_id: '2' })
  })

  it('⭐ 选标签 → 请求带 tag', async () => {
    const { wrapper, calls } = await mountMats()
    await wrapper.get('.mats-tag').setValue('方法')
    await flushPromises()
    expect(materialsCalls(calls).at(-1).query).toEqual({ tag: '方法' })
  })

  it('⭐ 清空筛选 → 回到不带参数的请求', async () => {
    const { wrapper, calls } = await mountMats()
    await wrapper.get('.mats-collection').setValue('1')
    await flushPromises()
    expect(wrapper.find('.mats-clear').exists()).toBe(true)
    await wrapper.get('.mats-clear').trigger('click')
    await flushPromises()
    expect(materialsCalls(calls).at(-1).query).toEqual({})
    expect(wrapper.find('.mats-clear').exists()).toBe(false)
  })

  it('⭐ 筛空与真空说的是两句不同的话', async () => {
    const empty = await mountMats({ materials: [] })
    expect(empty.wrapper.text()).toContain('还没有素材卡')
    resetMaterials()
    vi.unstubAllGlobals()

    // 筛空：先有素材，再选一个筛出 0 条的集合
    const { wrapper } = await mountMats({
      collections: [{ id: 1, name: '化学', doc_count: 1 }],
      onMaterials: (query) =>
        json(200, { items: query.get('collection_id') ? [] : [MAT] }),
    })
    await wrapper.get('.mats-collection').setValue('1')
    await flushPromises()
    expect(wrapper.text()).toContain('这个筛选下没有')
    expect(wrapper.text()).not.toContain('还没有素材卡。')
    // ⚠️ 顶部那句量也**不许**说"还没有素材卡"（实拍抓到过这个矛盾）
    expect(wrapper.get('.mats-count').text()).toBe('本筛选 0 条')
  })

  it('⭐ 筛选项取不到时仍然能看素材，并如实说明', async () => {
    const { wrapper, calls } = await mountMats({ collections: null, tags: null })
    // 两个列表都挂 → 文案是「集合 / 标签列表暂时取不到」；素材列表照常显示
    expect(wrapper.find('.mats-filters-note').exists()).toBe(true)
    expect(wrapper.text()).toContain('列表暂时取不到')
    expect(wrapper.text()).toContain('共 1 条')
    expect(materialsCalls(calls)).toHaveLength(1)
  })

  it('素材接口失败 → 如实说（原样转述服务端那句），不拿假数据顶', async () => {
    const { wrapper } = await mountMats({ onMaterials: () => json(500, { detail: '炸了' }) })
    expect(wrapper.find('.mats-error').exists()).toBe(true)
    // `_messageOf` 会优先用服务端给的那句话，编不出来才回落到"素材加载失败"
    expect(wrapper.text()).toContain('炸了')
    expect(wrapper.findAll('.mats-cell')).toHaveLength(0)
  })
})

/* ---------------------------------------------------------------- 接线 */

describe('接线：#/materials 真能打开', () => {
  it('路由表里有 materials', () => {
    expect(parseHash('#/materials')).toMatchObject({ name: 'materials' })
  })

  it('左栏「素材」真跳转，且渲染 MaterialsView', () => {
    const app = readSrc('src/App.vue')
    expect(app).toMatch(/'lib-materials':\s*\{\s*go:\s*\{\s*name:\s*'materials'\s*\}\s*\}/)
    expect(app).toContain("view === 'materials'")
    expect(app).toContain('<MaterialsView')
    expect(app).toMatch(/PAGES = \{[\s\S]*?materials:\s*'materials'/)
  })

  it('⚠️ 不许再出现"素材列表接口还没做"这种把用户挡在门外的文案', () => {
    expect(readSrc('src/App.vue')).not.toContain('素材列表接口（契约 N13）还没做')
  })
})
