/**
 * 写作页三栏可拖（素材 | 写作 | 助手）。
 *
 * 判据取"用户真会做的三件事"：
 *  ① 两条边界都在（`.wr-split-mats` / `.wr-split-helper`，能拖的都要有 role=separator）；
 *  ② 拖一下，宽度变了且**记住了**（localStorage，下次进来还是你调过的样子）；
 *  ③ 双击复位回默认（拖歪了有退路）。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// TipTap/ProseMirror 需要真实 DOM 量测，happy-dom 里跑不了；单测里换成轻量替身。
vi.mock('../src/components/WriteEditor.vue', () => import('./helpers/WriteEditorStub.js'))


vi.mock('../src/auth', () => ({
  authFetch: vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ items: [], drafts: [] }),
  })),
}))

import WriteView from '../src/views/WriteView.vue'

const MATS_KEY = 'docwise_write_mats_w'
const HELPER_KEY = 'docwise_write_helper_w'

function mountWrite() {
  return mount(WriteView, { attachTo: document.body })
}

/** 造一个 pointer 事件（happy-dom 的 PointerEvent 支持够用，不行就退回 MouseEvent）。 */
function pointer(type, x) {
  const Ctor = typeof PointerEvent !== 'undefined' ? PointerEvent : MouseEvent
  return new Ctor(type, { clientX: x, clientY: 120, bubbles: true, button: 0 })
}

async function drag(wrapper, selector, dx) {
  const el = wrapper.find(selector)
  expect(el.exists(), `${selector} 不存在`).toBe(true)
  // 组件的钳制要读真实宽度，happy-dom 里全是 0 → 给一个兜底宽度
  Object.defineProperty(window, 'innerWidth', { value: 1440, configurable: true })
  await el.trigger('pointerdown', { clientX: 400, clientY: 120, button: 0 })
  window.dispatchEvent(pointer('pointermove', 400 + dx))
  window.dispatchEvent(pointer('pointerup', 400 + dx))
  await flushPromises()
}

describe('写作页 · 三栏可拖', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('素材并入助手后只剩一条分隔条（写作 | 助手），且标了 role=separator', () => {
    const wrapper = mountWrite()
    // 2026-10-19：素材栏从独立一栏改成助手里的页签，所以"素材 | 写作"那条边界没有了
    expect(wrapper.find('.wr-split-mats').exists()).toBe(false)
    const helper = wrapper.find('.wr-split-helper')
    expect(helper.exists()).toBe(true)
    expect(helper.attributes('role')).toBe('separator')
    wrapper.unmount()
  })

  it('拖动会改宽度并记住（localStorage）', async () => {
    const wrapper = mountWrite()
    const body = wrapper.find('.wr-body')
    // 现在只有助手宽度可调（素材栏没了）
    expect(body.attributes('style')).toContain('--helper-w: 340px')

    await drag(wrapper, '.wr-split-helper', -50)
    expect(Number(localStorage.getItem(HELPER_KEY))).toBeGreaterThan(340)

    wrapper.unmount()
  })

  it('双击复位回默认宽度', async () => {
    localStorage.setItem(HELPER_KEY, '600')
    const wrapper = mountWrite()
    const body = wrapper.find('.wr-body')
    expect(body.attributes('style')).toContain('--helper-w: 600px')

    await wrapper.find('.wr-split-helper').trigger('dblclick')
    await flushPromises()

    expect(body.attributes('style')).toContain('--helper-w: 340px')
    expect(localStorage.getItem(HELPER_KEY)).toBe('340')
    wrapper.unmount()
  })
})
