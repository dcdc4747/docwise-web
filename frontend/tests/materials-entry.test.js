/**
 * 素材写入路径（M2 / 契约 §2.4 的 N12–N14）—— 前端那一半的用例。
 *
 * 这个文件盯四件事（都是"做错了看不出来"的）：
 *
 * ① ⭐ **三处入口共用同一条 store 路径**：划词浮标 / 问答出处 / 导读要点，点下去都是
 *    `POST /api/materials`，body 带 `task_id` + `block_id`（形状与契约 mock 一致）；
 * ② ⭐⭐ **撤销窗口开在发出 `DELETE` 之前**：契约里**没有"恢复"端点**，
 *    所以 5 秒内**一个请求都不发**、点「撤销」也**永远不发**；过期才发 `DELETE`；
 * ③ 存失败要**说人话**（按钮就地变「没存上，重试」+ 消息给得出原因），不静默；
 * ④ 起草页的「移除」入口 + 那条 5 秒撤销提示条。
 *
 * ⚠️ 三处入口的"都在"用**源码结构断言**（`app.smoke.test.js` 就是这么钉结构的）：
 *    ReadView 依赖整条阅读链路的状态，为它搭一套完整 mount 得不偿失；
 *    而"点击真的发请求"这条路径由 `MaterialSaveButton` 自己的 mount 用例覆盖。
 */

import { readFileSync } from 'node:fs'
import path from 'node:path'

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import MaterialSaveButton from '../src/components/MaterialSaveButton.vue'
import WriteView from '../src/views/WriteView.vue'
import {
  UNDO_MS,
  cancelPendingDelete,
  materials,
  pendingDelete,
  removeMaterial,
  resetMaterials,
  saveMaterial,
  saveState,
} from '../src/stores/useMaterials'
import { clearTasks } from '../src/stores/useTasks'
import { resetWrite } from '../src/stores/useWrite'

const HEALTH = {
  status: 'ok',
  service: 'docwise-web',
  checks: { database: true, worker: true },
  queue_size: 0,
  running_task_id: null,
  auth: { demo_autologin: false, session_days: 30 },
}
const USER = { id: 1, username: 'tester', display_name: '测试用户', role: 'user' }

function jsonOf(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

/** 一张素材卡（字段与契约 mock 的 `materialView` 一致）。 */
function materialOf(id, overrides = {}) {
  return {
    id,
    text_quote: `第 ${id} 段的原文`,
    translated_quote: null,
    page: id,
    source_name: 'chem.pdf',
    note: null,
    task_id: 42,
    block_id: `p${id}_b1`,
    deleted_at: null,
    created_at: '2026-10-16T02:00:00+00:00',
    ...overrides,
  }
}

let calls

function stubFetch({ postStatus = 201, deleteStatus = 200 } = {}) {
  calls = []
  const impl = vi.fn(async (input, init = {}) => {
    const url = typeof input === 'string' ? input : String(input?.url ?? input)
    const method = (init.method || 'GET').toUpperCase()
    calls.push({ method, url, body: init.body ? JSON.parse(init.body) : null })
    if (url.includes('/api/health')) return jsonOf(HEALTH)
    if (url.includes('/api/auth/me')) return jsonOf(USER)
    if (url.includes('/api/drafts')) return jsonOf({ items: [] })
    if (url.includes('/api/materials')) {
      if (method === 'POST') {
        if (postStatus !== 201) return jsonOf({ detail: '块不存在' }, postStatus)
        const body = JSON.parse(init.body)
        return jsonOf(
          materialOf(99, { task_id: body.task_id, block_id: body.block_id }),
          201,
        )
      }
      if (method === 'DELETE') {
        if (deleteStatus !== 200) return jsonOf({ detail: '删不掉' }, deleteStatus)
        return jsonOf({ deleted: true, id: 1, deleted_at: '2026-10-16T03:00:00+00:00' })
      }
      return jsonOf({ items: [] })
    }
    return jsonOf({})
  })
  return impl
}

const deletes = () => calls.filter((call) => call.method === 'DELETE')
const posts = () => calls.filter((call) => call.method === 'POST' && call.url.includes('/api/materials'))

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('docwise_token', 'test-token')
  window.history.replaceState(null, '', '#/write')
  globalThis.fetch = stubFetch()
  resetMaterials()
  resetWrite()
  clearTasks()
})

afterEach(() => {
  cancelPendingDelete()
  vi.useRealTimers()
  vi.restoreAllMocks()
  resetMaterials()
  resetWrite()
  clearTasks()
  document.body.innerHTML = ''
})

// ============================================================ ① 三处入口都在

describe('三处创建入口（契约要求「三处都在」）', () => {
  it('划词浮标 / 问答出处 / 导读要点各挂了一个 MaterialSaveButton', () => {
    const source = readFileSync(
      path.resolve(process.cwd(), 'src/views/ReadView.vue'),
      'utf8',
    )
    const used = source.match(/<MaterialSaveButton/g) || []
    expect(used.length).toBe(3)
    expect(source).toContain('variant="chip"') // ① 划词浮标
    expect(source).toContain('variant="src"') // ② 问答答案的出处
    expect(source).toContain('variant="guide"') // ③ 导读要点的出处
  })
})

// ============================================================ ② 点击真的发请求

describe('点一下就是 POST /api/materials', () => {
  it('浮标那一处：body 带 task_id 与 block_id', async () => {
    const wrapper = mount(MaterialSaveButton, {
      props: { taskId: 42, blockId: 'p2_b7', variant: 'chip' },
    })
    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(posts().length).toBe(1)
    expect(posts()[0].body).toEqual({ task_id: 42, block_id: 'p2_b7' })
    expect(wrapper.text()).toContain('已存为素材') // 就地反馈，不跳页
  })

  it('出处那一处（问答/导读共用同一组件）：形状一样', async () => {
    const wrapper = mount(MaterialSaveButton, {
      props: { taskId: 42, blockId: 'p0_b3', variant: 'src' },
    })
    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(posts().length).toBe(1)
    expect(posts()[0].body).toEqual({ task_id: 42, block_id: 'p0_b3' })
  })

  it('没有块坐标就不发请求（按钮置灰，title 说清为什么）', async () => {
    const wrapper = mount(MaterialSaveButton, { props: { taskId: 42, blockId: '' } })
    expect(wrapper.find('button').attributes('disabled')).toBeDefined()
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(posts().length).toBe(0)
    expect(wrapper.find('button').attributes('title')).toContain('没有块坐标')
  })
})

// ============================================================ ③ 失败要说人话

describe('存不上时给人话，不静默', () => {
  it('后端 404（比如块已被删）→ 按钮变「没存上，重试」+ 状态里带原因', async () => {
    globalThis.fetch = stubFetch({ postStatus: 404 })
    const wrapper = mount(MaterialSaveButton, {
      props: { taskId: 42, blockId: 'p9_b9', variant: 'src' },
    })
    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('没存上')
    expect(saveState.value.status).toBe('error')
    expect(saveState.value.message).toBeTruthy()
    expect(materials.value.length).toBe(0) // 没存上就不许往列表里塞
  })

  it('store 层面也不抛异常（返回值是 null，调用方不必 try/catch）', async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new Error('网络断了')
    })
    const created = await saveMaterial({ taskId: 42, blockId: 'p0_b1' })
    expect(created).toBeNull()
    expect(saveState.value.message).toContain('网络断了')
  })
})

// ============================================================ ④ 撤销窗口

describe('删除的撤销窗口开在发请求之前（契约没有恢复端点）', () => {
  it('5 秒内不发任何 DELETE；点撤销后也永远不发', async () => {
    vi.useFakeTimers()
    materials.value = [materialOf(1)]
    removeMaterial(1)

    // 立刻：卡片从列表里消失（只是被藏起来），但**一个请求都没发**
    expect(pendingDelete.value.id).toBe(1)
    await vi.advanceTimersByTimeAsync(UNDO_MS - 1)
    expect(deletes().length).toBe(0)

    cancelPendingDelete()
    await vi.advanceTimersByTimeAsync(UNDO_MS * 3)
    expect(deletes().length).toBe(0)
    expect(pendingDelete.value).toBeNull()
    expect(materials.value.map((item) => item.id)).toEqual([1]) // 卡片还在
  })

  it('过了 5 秒才真的发 DELETE，成功后从列表里去掉', async () => {
    vi.useFakeTimers()
    materials.value = [materialOf(1), materialOf(2)]
    removeMaterial(1)

    await vi.advanceTimersByTimeAsync(UNDO_MS)
    await flushPromises()

    expect(deletes().length).toBe(1)
    expect(deletes()[0].url).toContain('/api/materials/1')
    expect(materials.value.map((item) => item.id)).toEqual([2])
  })

  it('DELETE 失败时卡片放回列表，并把话说清楚', async () => {
    vi.useFakeTimers()
    globalThis.fetch = stubFetch({ deleteStatus: 500 })
    materials.value = [materialOf(1)]
    removeMaterial(1)

    await vi.advanceTimersByTimeAsync(UNDO_MS)
    await flushPromises()

    expect(materials.value.map((item) => item.id)).toEqual([1]) // 没删掉就得回来
    expect(saveState.value.status).not.toBe('error') // 别把删除失败记成"保存失败"
  })

  it('同时删两条时，前一条立刻提交（不留两个窗口互相覆盖）', async () => {
    vi.useFakeTimers()
    materials.value = [materialOf(1), materialOf(2)]
    removeMaterial(1)
    removeMaterial(2)
    await flushPromises()

    expect(deletes().length).toBe(1)
    expect(deletes()[0].url).toContain('/api/materials/1')
    await vi.advanceTimersByTimeAsync(UNDO_MS)
    await flushPromises()
    expect(deletes().length).toBe(2)
  })
})

// ============================================================ 起草页接线

describe('起草页：移除入口 + 撤销提示条', () => {
  it('点「移除」→ 卡片先消失、提示条出现；点「撤销」→ 卡片回来且**一个请求都没发**', async () => {
    vi.useFakeTimers()
    const wrapper = mount(WriteView, { attachTo: document.body })
    await flushPromises()
    materials.value = [materialOf(1, { text_quote: '手性测度是守恒的' })]
    await flushPromises()

    expect(wrapper.findAll('.wr-matslot').length).toBe(1)
    const removeBtn = wrapper
      .findAll('.wr-matslot-ops button')
      .find((btn) => btn.text() === '移除')
    expect(removeBtn).toBeTruthy()
    await removeBtn.trigger('click')
    await flushPromises()

    expect(wrapper.findAll('.wr-matslot').length).toBe(0) // 先藏起来
    const undo = wrapper.find('.wr-matundo')
    expect(undo.exists()).toBe(true)
    expect(undo.text()).toContain('5 秒内可撤销')
    expect(undo.text()).toContain('手性测度是守恒的') // 提示条说清是哪一条

    await undo.find('button').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.wr-matslot').length).toBe(1) // 卡片回来
    expect(wrapper.find('.wr-matundo').exists()).toBe(false)

    await vi.advanceTimersByTimeAsync(UNDO_MS * 2)
    expect(deletes().length).toBe(0) // 撤销之后永远不发
  })

  it('不撤销的话，5 秒后自动删掉', async () => {
    vi.useFakeTimers()
    const wrapper = mount(WriteView, { attachTo: document.body })
    await flushPromises()
    materials.value = [materialOf(1)]
    await flushPromises()

    const removeBtn = wrapper
      .findAll('.wr-matslot-ops button')
      .find((btn) => btn.text() === '移除')
    await removeBtn.trigger('click')
    await flushPromises()
    expect(deletes().length).toBe(0)

    await vi.advanceTimersByTimeAsync(UNDO_MS)
    await flushPromises()

    expect(deletes().length).toBe(1)
    expect(materials.value.length).toBe(0)
    expect(wrapper.find('.wr-matundo').exists()).toBe(false)
  })
})
