/**
 * 卡③ 知识库概况底行（`LibOverview.vue`，issue #111）的用例。
 *
 * 它只做两件事，但两件都容易被做歪：
 * ① **概况必须是可读的文字明细**（不许只有色块 —— 只有色块等于什么都没说）；
 * ② **数据没就位就如实说**，不许摆一排 0 冒充"统计好了"。
 */

import { readFileSync } from 'node:fs'
import path from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import LibOverview from '../src/components/LibOverview.vue'

const stats = { tasks: 12, blocks: 340, materials: 5, citations: 3 }
const tags = [
  { name: '手性', count: 4 },
  { name: '酶催化', count: 2 },
]

const readStyle = () => readFileSync(path.resolve(process.cwd(), 'src/style.css'), 'utf8')

describe('LibOverview 知识库概况', () => {
  it('⭐ 概况行带文字明细：篇 / 块 / 素材 / 引用四段都在', () => {
    const wrapper = mount(LibOverview, { props: { stats } })

    const line = wrapper.find('.lib-ov-line').text()
    expect(line).toBe('12 篇文献 · 340 块 · 5 条素材 · 3 条引用')
  })

  it('标签云：标签名带计数，点一下把标签名交出去（筛选归页面）', async () => {
    const wrapper = mount(LibOverview, { props: { stats, tags } })

    const items = wrapper.findAll('button.lib-tag')
    expect(items).toHaveLength(2)
    expect(items[0].text()).toContain('手性')
    expect(items[0].text()).toContain('4')
    expect(items[0].attributes('aria-label')).toContain('手性')
    expect(items[0].element.tagName).toBe('BUTTON')

    await items[0].trigger('click')
    expect(wrapper.emitted('pick-tag').at(-1)[0]).toBe('手性')
  })

  it('⭐ 数据没就位（没给 stats）→ 如实说"暂未接入"，**不摆一排 0**', () => {
    const wrapper = mount(LibOverview)

    expect(wrapper.find('.hnote').text()).toContain('暂未接入')
    expect(wrapper.find('.lib-ov-line').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('0 篇文献')
  })

  it('标签拿不到 → 标签云整块不渲染（不摆空壳）', () => {
    const wrapper = mount(LibOverview, { props: { stats } })

    expect(wrapper.find('.lib-cloud').exists()).toBe(false)
  })

  it('只有名字没有名字的标签条目直接丢掉，且单个缺字段按 0 计（不崩）', () => {
    const wrapper = mount(LibOverview, {
      props: { stats: { tasks: 3 }, tags: [{ name: '手性' }, null, { count: 9 }] },
    })

    expect(wrapper.findAll('button.lib-tag')).toHaveLength(1)
    expect(wrapper.find('.lib-ov-line').text()).toBe('3 篇文献 · 0 块 · 0 条素材 · 0 条引用')
  })

  it('样式按 token 走：概况行的数字用 tabular-nums（数字列对齐），不写死色值', () => {
    const css = readStyle()

    const start = css.indexOf('.dw .lib-ov-line')
    expect(start).toBeGreaterThan(-1)
    const rule = css.slice(start, start + 220)
    expect(rule).toContain('tabular-nums')
    expect(rule).toContain('var(--')
    expect(rule).not.toMatch(/#[0-9a-f]{3,6}/i)
  })

  it('渲染出来的文本不含源码痕迹、也不含 emoji', () => {
    const wrapper = mount(LibOverview, { props: { stats, tags } })

    const text = wrapper.text()
    expect(text).not.toContain('function ')
    expect(text).not.toContain('=>')
    expect(text).not.toContain('{{')
    expect(text).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u)
  })
})
