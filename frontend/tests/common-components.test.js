/**
 * F1 通用组件（出处芯片 / 诚实提示 / 空态）的用例。
 *
 * 这三个组件都**不渲染在自己的页面里**（它们是被 M1/M2 的页面拿去用的零件），
 * 所以坏掉的时候没有"一眼看得见的白屏"——只能靠这里的断言钉住它们的**契约**：
 * 芯片的内容顺序与"不许有段号"、诚实提示"必须说为什么"、空态"两种可分辨 + 不许说暂无数据"。
 *
 * ⚠️ 组件里那两条 `console.warn`（光秃秃的"无法判断" / 文案里带"暂无数据"）是**设计纪律的守卫**，
 * 这里连守卫本身一起测：**守卫自己坏掉 = 纪律形同虚设**。
 */

import { readFileSync } from 'node:fs'
import path from 'node:path'

import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import CiteChip from '../src/components/CiteChip.vue'
import EmptyState from '../src/components/EmptyState.vue'
import HonestNote from '../src/components/HonestNote.vue'

afterEach(() => {
  vi.restoreAllMocks()
})

/** 这两条断言要看的是**样式规则本身**（`bun run test` 在 `frontend/` 下跑）。 */
const readStyle = () => readFileSync(path.resolve(process.cwd(), 'src/style.css'), 'utf8')

describe('CiteChip 出处芯片', () => {
  it('渲染一条出处：来源名 · 第 X 页 ·「原句开头…」，顺序固定', () => {
    const wrapper = mount(CiteChip, {
      props: {
        cites: {
          source_name: 'EBSCO_05-mono.pdf',
          page: 3,
          quote: 'We evaluate how non-native readers use retrieval-augmented translation.',
        },
      },
    })

    const chip = wrapper.find('.cite-chip')
    expect(chip.exists()).toBe(true)

    const text = chip.text()
    expect(text).toContain('EBSCO_05-mono.pdf')
    expect(text.indexOf('EBSCO_05-mono.pdf')).toBeLessThan(text.indexOf('第 3 页'))
    expect(text.indexOf('第 3 页')).toBeLessThan(text.indexOf('「'))

    // 原句只给开头（默认 24 字）并以 … 收尾：芯片是"认领是哪句"，不是摘录全文
    expect(text).toContain('「We evaluate how')
    expect(text).toContain('…')
    expect(text).not.toContain('translation')
  })

  it('⭐ 一条结论命中两个出处 → 两个芯片在同一个容器里（只有一个形态，没有紧凑版）', () => {
    const wrapper = mount(CiteChip, {
      props: {
        cites: [
          { source_name: '文献 A', page: 2, quote: 'first' },
          { source_name: '文献 B', page: 9, quote: 'second' },
        ],
      },
    })

    expect(wrapper.findAll('.cite-chip')).toHaveLength(2)
    // 两个芯片同一个类名、同一个容器 = 没有"第二个出处形态"
    expect(wrapper.findAll('.cite-stack')).toHaveLength(1)
    expect(wrapper.findAll('.cite-chip')[0].classes()).toEqual(wrapper.findAll('.cite-chip')[1].classes())
  })

  it('纵向排列由这一段 CSS 定（不是各调用方自己摆）——防止有人把芯片改成横排', () => {
    const css = readStyle()
    const start = css.indexOf('.dw .cite-stack')
    expect(start).toBeGreaterThan(-1)
    expect(css.slice(start, start + 240)).toContain('flex-direction: column')
  })

  it('点整块 → emit locate，并原样带出快照字段（滚动与 1.6s 高亮归页面那边的现有 traceTo）', async () => {
    const cite = { source_name: '文献 A', page: 2, quote: 'q', block_id: 'b7', task_id: 12 }
    const wrapper = mount(CiteChip, { props: { cites: cite } })

    await wrapper.find('.cite-chip').trigger('click')

    const events = wrapper.emitted('locate')
    expect(events).toHaveLength(1)
    expect(events[0][0]).toEqual(cite)
  })

  it('页码取不到就不渲染页码（宁可不给，也不编一个坐标）', () => {
    const wrapper = mount(CiteChip, { props: { cites: { source_name: '文献 A' } } })

    const text = wrapper.find('.cite-chip').text()
    expect(text).toBe('文献 A')
    expect(text).not.toContain('页')
  })

  it('⭐ 不许说"第 Y 段"——芯片里只有页码，段号再准也不给', () => {
    const wrapper = mount(CiteChip, {
      props: { cites: { source_name: '文献 A', page: 3, quote: 'q', block_id: 'p2_b7' } },
    })

    expect(wrapper.text()).not.toContain('段')
  })

  it('键盘可达：整块是原生 button，且 aria-label 说明"点了会怎样"', () => {
    const wrapper = mount(CiteChip, { props: { cites: { source_name: '文献 A', page: 3 } } })

    const chip = wrapper.find('.cite-chip')
    expect(chip.element.tagName).toBe('BUTTON')
    expect(chip.attributes('aria-label')).toContain('跳到原文')
  })

  it('来源名缺失的条目直接丢掉（不许渲染成一个没有来源的空芯片）', () => {
    const wrapper = mount(CiteChip, { props: { cites: [{ page: 1 }, null] } })

    expect(wrapper.findAll('.cite-chip')).toHaveLength(0)
  })
})

describe('HonestNote 诚实提示', () => {
  it('渲染：一行文字 + 一个信息图标（图标从 sprite 取，不用 emoji）', () => {
    const wrapper = mount(HonestNote, { props: { text: '无法判断（稿件未含版式信息）' } })

    expect(wrapper.text()).toContain('无法判断（稿件未含版式信息）')
    const use = wrapper.find('svg use')
    expect(use.exists()).toBe(true)
    expect(use.attributes('href')).toBe('#i-info')
  })

  it('中性灰不是红也不是黄（颜色走 --unknown，不写死色值）', () => {
    const css = readStyle()
    const start = css.indexOf('.dw .hnote {')
    expect(start).toBeGreaterThan(-1)
    const rule = css.slice(start, start + 260)
    expect(rule).toContain('var(--unknown')
    expect(rule).not.toMatch(/#[0-9a-f]{3,6}/i)
  })

  it('⭐ 文案必须说"为什么"：只写"无法判断"四个字 → 开发环境报警', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})

    mount(HonestNote, { props: { text: '无法判断' } })

    expect(warn).toHaveBeenCalled()
  })

  it('带原因的文案不报警（守卫不许误伤正确用法）', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})

    mount(HonestNote, { props: { text: '暂无块级译文（这篇是 2026-09-30 之前跑的，当时还没落块级译文）' } })

    expect(warn).not.toHaveBeenCalled()
  })
})

describe('EmptyState 空态', () => {
  it('真空：给一个动作（主按钮），不是一行小链接', async () => {
    const wrapper = mount(EmptyState, {
      props: {
        variant: 'empty',
        title: '库里还没有文献',
        description: '上传一份 PDF，就能得到双语对照稿。',
        actionText: '上传文献',
      },
    })

    const button = wrapper.find('button.empty-action')
    expect(button.exists()).toBe(true)
    expect(button.classes()).toContain('primary')
    expect(button.text()).toBe('上传文献')
    expect(wrapper.text()).not.toContain('清除筛选')

    await button.trigger('click')
    expect(wrapper.emitted('action')).toHaveLength(1)
  })

  it('筛空了：说清是筛选造成的 + 给出口（不给"上传"主按钮）', async () => {
    const wrapper = mount(EmptyState, {
      props: { variant: 'filtered', title: '这个筛选下没有文献' },
    })

    // 不给兜底说明时，默认文案就把"是筛选造成的"说清
    expect(wrapper.find('.empty-desc').text()).toContain('筛选')
    expect(wrapper.find('button.empty-action').exists()).toBe(false)

    const clear = wrapper.find('button.empty-clear')
    expect(clear.text()).toBe('清除筛选')

    await clear.trigger('click')
    expect(wrapper.emitted('clear')).toHaveLength(1)
  })

  it('两种空态一眼可分辨：一个给动作、一个给出口', () => {
    const empty = mount(EmptyState, { props: { variant: 'empty', title: 'a', actionText: '上传文献' } })
    const filtered = mount(EmptyState, { props: { variant: 'filtered', title: 'a' } })

    expect(empty.find('button.empty-action').exists()).toBe(true)
    expect(empty.find('button.empty-clear').exists()).toBe(false)
    expect(filtered.find('button.empty-action').exists()).toBe(false)
    expect(filtered.find('button.empty-clear').exists()).toBe(true)
  })

  it('⚠️ 绝不说"暂无数据"：谁传进来就在开发环境报警', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})

    mount(EmptyState, { props: { variant: 'empty', title: '暂无数据', actionText: '上传文献' } })
    expect(warn).toHaveBeenCalled()

    warn.mockClear()
    mount(EmptyState, { props: { variant: 'empty', title: '库里还没有文献', actionText: '上传文献' } })
    expect(warn).not.toHaveBeenCalled()
  })
})
