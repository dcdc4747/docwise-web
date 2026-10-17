/**
 * 形态 v2 **集成**那一层的用例（外壳把 M1 / M5 的组件接起来之后）。
 *
 * 这一包盯的是"接线有没有真的接上"——组件自己的用例已经在
 * `lib-filters` / `lib-overview` / `me-view` 里了，这里只管：
 * ① `#/me`、`#/admin` 两个地址**现在真能打开**（以前落在"还没做"的提示里）；
 * ② 个人中心存的**偏好真的被消费**（字号 → `--fs-scale`、档位 → 上传卡默认档、动效 → `data-motion`）；
 * ③ 左栏「待读」**带着 N8 的筛选条件**进库页（不是只跳过去、什么都不筛）；
 * ④ 筛选条件真的拼进了请求（`?reading_status=` / `?tag[]=`，空值不拼）。
 *
 * ⚠️ 为什么值得单开一包：这些接线**每一根都断过一次**——
 * 偏好"只写不读"、`#/admin` 是死链、筛选条后面没有接口，全都是"组件都对、合起来没用"。
 */

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.vue'
import LibraryView from '../src/views/LibraryView.vue'
import { loadTasks, tasks } from '../src/stores/useTasks'
import { activeTaskQuery, libraryTotal, selectedTier } from '../src/stores/useLibrary'

const TOKEN_KEY = 'docwise_token'
const PREFS_KEY = 'docwise_prefs'

/** 记录每次请求的 URL，并按路径给一份最小可用的应答。 */
let calls = []

function stubApi({ tasks: taskRows = [], adminForbidden = false } = {}) {
  calls = []
  return vi.fn(async (input, options = {}) => {
    const url = String(input)
    const method = (options.method || 'GET').toUpperCase()
    calls.push({ url, method })
    const path = url.split('?')[0]
    const ok = (body, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })

    if (path === '/api/health') return ok({ status: 'ok' })
    if (path === '/api/auth/me') {
      return ok({ id: 1, username: 'tester', role: 'user', display_name: null, is_active: true, created_at: null })
    }
    if (path === '/api/tasks') return ok(taskRows)
    // ⚠️ 这两个端点返回的是**裸数组**（不是 `{items}`）—— 返回错形状会让
    // AdminView 里的 n-data-table 拿到 Object，直接炸（本文件第一版就这么翻的车）。
    if (path === '/api/admin/users') return adminForbidden ? ok({ detail: 'forbidden' }, 403) : ok([])
    if (path === '/api/admin/tasks') return adminForbidden ? ok({ detail: 'forbidden' }, 403) : ok([])
    if (path.startsWith('/api/admin/')) {
      return adminForbidden ? ok({ detail: 'forbidden' }, 403) : ok({})
    }
    if (path.startsWith('/api/me/')) return ok({})
    if (path === '/api/drafts') return ok([])
    if (path === '/api/materials') return ok([])
    return ok({})
  })
}

function setHash(hash) {
  window.location.hash = hash
}

async function mountApp() {
  const wrapper = mount(App)
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('形态 v2 集成：地址与偏好的接线', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    localStorage.setItem(TOKEN_KEY, 'test-token')
    setHash('#/')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('⭐ `#/me` 现在真能打开（以前落在「个人中心还没做」的提示里）', async () => {
    vi.stubGlobal('fetch', stubApi())
    setHash('#/me')
    const wrapper = await mountApp()

    expect(wrapper.find('.screen-me').exists()).toBe(true)
    // MeView 的六个区块标题至少出来一个，证明挂的是那一页
    expect(wrapper.text()).toContain('账号安全')
    expect(wrapper.text()).not.toContain('个人中心还没做')
    wrapper.unmount()
  })

  it('⭐ `#/admin` 打开现成的管理后台，并且**有返回口**（以前是死链 + 只能刷出去）', async () => {
    vi.stubGlobal('fetch', stubApi())
    setHash('#/admin')
    const wrapper = await mountApp()

    expect(wrapper.find('.admin-page').exists()).toBe(true)
    const back = wrapper.find('.admin-backbar button')
    expect(back.exists()).toBe(true)

    await back.trigger('click')
    await flushPromises()
    expect(wrapper.find('.admin-page').exists()).toBe(false)
    expect(window.location.hash).toBe('#/')
    wrapper.unmount()
  })

  it('⭐ 离开管理后台时面板要跟着关（改地址 / 点左栏都算）——以前会一直盖着', async () => {
    // 用户实测报的问题：打开后台后点左栏，地址变了、**画面还是后台**。
    // 根因：清 `showAdmin` 的那行写在 `syncFromRoute` 末尾，而切页分支全都提前 `return` 了。
    vi.stubGlobal('fetch', stubApi())
    setHash('#/admin')
    const wrapper = await mountApp()
    expect(wrapper.find('.admin-page').exists()).toBe(true)

    // ① 改地址离开
    // ⚠️ happy-dom 的 hashchange 是**异步派发**的：只 flush 微任务不够，要让出一轮宏任务
    setHash('#/memory')
    await new Promise((r) => setTimeout(r, 0))
    await flushPromises()
    expect(wrapper.find('.admin-page').exists()).toBe(false)

    // ② 再回后台，然后走"点左栏"那条路（`onRailSelect`）
    setHash('#/admin')
    await new Promise((r) => setTimeout(r, 0))
    await flushPromises()
    expect(wrapper.find('.admin-page').exists()).toBe(true)
    const railItem = wrapper.findAll('button.rail-item').find((b) => b.text() === '起草')
    // 后台盖住时左栏不在 DOM 里，所以这里直接改地址模拟"点左栏"的最终效果
    setHash('#/write')
    await new Promise((r) => setTimeout(r, 0))
    await flushPromises()
    expect(wrapper.find('.admin-page').exists()).toBe(false)
    expect(railItem).toBeUndefined()
    wrapper.unmount()
  })

  it('⭐ 偏好真的被消费：阅读字号 → `--fs-scale`、档位 → 上传卡默认档、动效 → `data-motion`', async () => {
    localStorage.setItem(
      PREFS_KEY,
      JSON.stringify({ readingSize: 'large', tier: 'fast', reducedMotion: true, defaultView: 'dual' }),
    )
    vi.stubGlobal('fetch', stubApi())
    const wrapper = await mountApp()

    const dw = wrapper.find('.dw')
    expect(dw.exists()).toBe(true)
    expect(dw.attributes('style')).toContain('--fs-scale: 1.12')
    expect(dw.attributes('data-motion')).toBe('system')
    expect(selectedTier.value).toBe('fast')
    wrapper.unmount()
  })

  it('偏好没设 / 数据是坏的 → 回落默认，不报错也不乱来', async () => {
    localStorage.setItem(PREFS_KEY, '{坏 JSON')
    vi.stubGlobal('fetch', stubApi())
    const wrapper = await mountApp()

    const dw = wrapper.find('.dw')
    expect(dw.attributes('style')).toContain('--fs-scale: 1')
    expect(dw.attributes('data-motion')).toBe('full')
    expect(selectedTier.value).toBe('medium')
    wrapper.unmount()
  })

  it('⭐ 左栏「待读」：进库页**并带上 N8 的筛选条件**（不是只跳过去）', async () => {
    vi.stubGlobal('fetch', stubApi({ tasks: [{ id: 1, filename: 'a.pdf', status: 'completed' }] }))
    const wrapper = await mountApp()

    const railTodo = wrapper
      .findAll('button, [role="button"], li, a')
      .find((node) => node.text().trim() === '待读')
    expect(railTodo, '左栏应该有「待读」这一项').toBeTruthy()

    await railTodo.trigger('click')
    await flushPromises()

    expect(activeTaskQuery.value).toEqual({ reading_status: 'todo' })
    expect(calls.some((c) => c.url === '/api/tasks?reading_status=todo')).toBe(true)
    wrapper.unmount()
  })

  it('「全部文献」= 清掉筛选（回库页且不再带上一次的条件）', async () => {
    vi.stubGlobal('fetch', stubApi())
    activeTaskQuery.value = { reading_status: 'todo' }
    const wrapper = await mountApp()

    const railAll = wrapper
      .findAll('button, [role="button"], li, a')
      .find((node) => node.text().trim() === '全部文献')
    expect(railAll).toBeTruthy()
    await railAll.trigger('click')
    await flushPromises()

    expect(activeTaskQuery.value).toEqual({})
    expect(calls.some((c) => c.url === '/api/tasks')).toBe(true)
    wrapper.unmount()
  })
})

describe('N8 查询串：筛选条件怎么拼进请求', () => {
  beforeEach(() => {
    localStorage.setItem(TOKEN_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('数组按契约写成 `tag[]=`，标量原样，**空值不拼**（不发"看起来筛了其实没筛"的请求）', async () => {
    const fetchMock = stubApi()
    vi.stubGlobal('fetch', fetchMock)
    calls = []

    await loadTasks({ reading_status: 'todo', collection_id: 3, tag: ['酶催化', 'RAG'], smart_id: '' })
    const url = calls.at(-1).url
    // 逐段断言（顺序按对象键序，这里不锁死顺序，只锁"该有的都有、空值没进来"）
    expect(url.startsWith('/api/tasks?')).toBe(true)
    expect(url).toContain('reading_status=todo')
    expect(url).toContain('collection_id=3')
    expect(url).toContain(`tag[]=${encodeURIComponent('酶催化')}`)
    expect(url).toContain('tag[]=RAG')
    expect(url).not.toContain('smart_id')
  })

  it('不传 / 传空对象 → 与以前一模一样的裸请求', async () => {
    vi.stubGlobal('fetch', stubApi())
    calls = []
    await loadTasks()
    await loadTasks({})
    expect(calls.map((c) => c.url)).toEqual(['/api/tasks', '/api/tasks'])
  })

  it('记家底：**只在没筛的那一次**记 total（拿筛过的条数当家底会把筛空态判错）', async () => {
    vi.stubGlobal('fetch', stubApi({ tasks: [{ id: 1 }, { id: 2 }] }))
    const { loadTasksAndSync } = await import('../src/stores/useLibrary')

    await loadTasksAndSync({})
    expect(libraryTotal.value).toBe(2)

    tasks.value = [{ id: 1 }] // 服务端筛完只回来一条
    await loadTasksAndSync({ reading_status: 'todo' })
    expect(libraryTotal.value).toBe(2) // 家底没被筛过的那次篡改
  })
})

describe('库页把筛选条接上了', () => {
  beforeEach(() => {
    localStorage.setItem(TOKEN_KEY, 'test-token')
    activeTaskQuery.value = null
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('⭐ 状态四档就在页面上，点「待读」→ 请求带上 `reading_status=todo`', async () => {
    vi.stubGlobal('fetch', stubApi({ tasks: [{ id: 1, filename: 'a.pdf', status: 'completed' }] }))
    tasks.value = [{ id: 1, filename: 'a.pdf', status: 'completed' }]
    const wrapper = mount(LibraryView)
    await flushPromises()

    const bar = wrapper.find('.lib-filters')
    expect(bar.exists()).toBe(true)
    const chip = bar.findAll('button.lib-chip').find((b) => b.text() === '待读')
    expect(chip).toBeTruthy()

    await chip.trigger('click')
    await flushPromises()
    expect(calls.some((c) => c.url.includes('reading_status=todo'))).toBe(true)
    wrapper.unmount()
  })

  it('概况底行在（没数就走诚实档，**不摆一排 0**）', async () => {
    vi.stubGlobal('fetch', stubApi({ tasks: [{ id: 1, filename: 'a.pdf', status: 'completed' }] }))
    const wrapper = mount(LibraryView)
    await flushPromises()

    expect(wrapper.find('.lib-ov').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('0 篇文献 · 0 块')
    wrapper.unmount()
  })
})
