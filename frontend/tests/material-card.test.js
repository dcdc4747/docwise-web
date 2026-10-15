/**
 * 卡② 素材卡组件（`MaterialCard.vue`，issue #110）的用例。
 *
 * 这个组件**不在自己的页面里**（素材库页由外壳负责人装配），所以它坏掉时没有"一眼看得见的白屏"——
 * 只能靠这里把它的三条纪律钉住：
 * ① **快照就是快照**（删掉源任务后仍显示出处）；
 * ② **三个状态一眼可辨**（正常 / 源文献已删 / 软删）；
 * ③ **键盘可达的原生元素**（不许 `div` + `@click`；死链不许做成活链）。
 */

import { readFileSync } from 'node:fs'
import path from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MaterialCard from '../src/components/MaterialCard.vue'

/** 契约 §2.4 的 `Material` 快照（字段一个不多、一个不少）。 */
const snapshot = {
  id: 7,
  text_quote: '（原文）读者信任一个答案，取决于能否跳回它出处的那句话。',
  translated_quote: 'Readers trust an answer when they can jump back to the sentence it came from.',
  page: 3,
  source_name: 'EBSCO_05-mono.pdf',
  note: '选题依据',
  task_id: 42,
  block_id: 'p2_b7',
  deleted_at: null,
  created_at: '2026-10-15T02:00:00+00:00',
}

const readStyle = () => readFileSync(path.resolve(process.cwd(), 'src/style.css'), 'utf8')
const readComponent = () =>
  readFileSync(path.resolve(process.cwd(), 'src/components/MaterialCard.vue'), 'utf8')

describe('MaterialCard 素材卡', () => {
  it('正常态：原文快照 + 译文 + 备注 + 出处芯片（来源名 · 第 X 页）', () => {
    const wrapper = mount(MaterialCard, { props: { material: snapshot } })

    expect(wrapper.find('.mat-quote').text()).toContain('读者信任一个答案')
    expect(wrapper.find('.mat-trans').text()).toContain('Readers trust an answer')
    expect(wrapper.find('.mat-note').text()).toContain('备注：选题依据')

    const chip = wrapper.find('.cite-chip')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('EBSCO_05-mono.pdf')
    expect(chip.text()).toContain('第 3 页')
  })

  it('点出处 → emit locate，并把**整份快照**带出去（滚动与高亮归页面的现有 traceTo）', async () => {
    const wrapper = mount(MaterialCard, { props: { material: snapshot } })

    await wrapper.find('.cite-chip').trigger('click')

    const events = wrapper.emitted('locate')
    expect(events).toHaveLength(1)
    expect(events[0][0]).toEqual(snapshot)
  })

  it('⭐ 源文献已删（task_id 为 null）：诚实说"仅存快照"，且出处**置灰不可点**', async () => {
    const orphan = { ...snapshot, task_id: null, block_id: null }
    const wrapper = mount(MaterialCard, { props: { material: orphan } })

    // ① 快照字段照常显示（出处是深拷贝，所以这一态才成立）
    expect(wrapper.find('.cite-chip').text()).toContain('EBSCO_05-mono.pdf')
    expect(wrapper.find('.cite-chip').text()).toContain('第 3 页')

    // ② 诚实档：说清是"源文献已删除"，并说明为什么出处还有效
    const note = wrapper.find('.hnote')
    expect(note.exists()).toBe(true)
    expect(note.text()).toContain('源文献已删除，仅存快照')
    expect(note.text()).toContain('深拷贝')

    // ③ 死链不许做成活链：容器 inert（鼠标点不动、键盘也进不去）
    const frozen = wrapper.find('.mat-frozen')
    expect(frozen.exists()).toBe(true)
    expect(frozen.element.hasAttribute('inert')).toBe(true)

    await frozen.find('.cite-chip').trigger('click')
    expect(wrapper.emitted('locate')).toBeUndefined()
  })

  it('软删（deleted_at 非空）：状态一眼可辨 + 给"撤销删除"这个原生按钮', async () => {
    const removed = { ...snapshot, deleted_at: '2026-10-15T03:00:00+00:00' }
    const wrapper = mount(MaterialCard, { props: { material: removed } })

    expect(wrapper.find('.mat-card').classes()).toContain('is-deleted')
    expect(wrapper.find('.mat-badge').text()).toContain('已删除')
    expect(wrapper.find('.mat-badge').text()).toContain('7 天')

    const restore = wrapper.find('button.mat-restore')
    expect(restore.exists()).toBe(true)
    expect(restore.element.tagName).toBe('BUTTON')

    await restore.trigger('click')
    const events = wrapper.emitted('restore')
    expect(events).toHaveLength(1)
    expect(events[0][0]).toEqual(removed)
  })

  it('三个状态一眼可辨：类名不同（正常 / 源文献已删 / 软删）', () => {
    const normal = mount(MaterialCard, { props: { material: snapshot } })
    const orphan = mount(MaterialCard, { props: { material: { ...snapshot, task_id: null } } })
    const removed = mount(MaterialCard, { props: { material: { ...snapshot, deleted_at: 'x' } } })

    expect(normal.find('.mat-card').classes()).not.toContain('is-orphan')
    expect(normal.find('.mat-card').classes()).not.toContain('is-deleted')
    expect(orphan.find('.mat-card').classes()).toContain('is-orphan')
    expect(removed.find('.mat-card').classes()).toContain('is-deleted')
  })

  it('中文文献没有译文（translated_quote 为 null）→ 整行不渲染，不写"暂无译文"', () => {
    const wrapper = mount(MaterialCard, {
      props: { material: { ...snapshot, translated_quote: null } },
    })

    expect(wrapper.find('.mat-trans').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('暂无译文')
  })

  it('⭐ 出处口径：整卡不许出现"第 Y 段"', () => {
    const wrapper = mount(MaterialCard, { props: { material: snapshot } })

    expect(wrapper.text()).not.toContain('段')
  })

  it('键盘可达：可交互的全是原生 button，且源码里没有 `div` + `@click`', () => {
    const wrapper = mount(MaterialCard, {
      props: { material: { ...snapshot, deleted_at: 'x' } },
    })

    const buttons = wrapper.findAll('button')
    expect(buttons.length).toBeGreaterThanOrEqual(2)
    for (const button of buttons) {
      expect(button.element.tagName).toBe('BUTTON')
    }

    // 机械判据：整卡只靠原生控件，不靠给 div 挂点击
    expect(readComponent()).not.toMatch(/<div[^>]*@click/)
  })

  it('自跑模式：不登录取数也能把三种状态看全（demo / ?demo=mock）', () => {
    const wrapper = mount(MaterialCard, { props: { demo: true } })

    expect(wrapper.findAll('.mat-card')).toHaveLength(3)
    expect(wrapper.findAll('.mat-card.is-orphan')).toHaveLength(1)
    expect(wrapper.findAll('.mat-card.is-deleted')).toHaveLength(1)
  })

  it('没给 material 又不是自跑模式 → 什么都不渲染（不炸、不空转）', () => {
    const wrapper = mount(MaterialCard)

    expect(wrapper.find('.mat-card').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('样式按 token 走：冻结态用 --unknown（置灰不是红），卡片不写死色值', () => {
    const css = readStyle()

    const frozen = css.indexOf('.dw .mat-frozen .cite-chip')
    expect(frozen).toBeGreaterThan(-1)
    const frozenRule = css.slice(frozen, frozen + 220)
    expect(frozenRule).toContain('var(--unknown')
    expect(frozenRule).not.toMatch(/#[0-9a-f]{3,6}/i)

    const card = css.indexOf('.dw .mat-card {')
    expect(card).toBeGreaterThan(-1)
    const cardRule = css.slice(card, card + 260)
    expect(cardRule).toContain('var(--')
    expect(cardRule).not.toMatch(/#[0-9a-f]{3,6}/i)
  })

  it('渲染出来的文本不含源码痕迹（模板里少写一对括号会把函数源码印上屏——踩过）', () => {
    const wrapper = mount(MaterialCard, { props: { demo: true } })

    const text = wrapper.text()
    expect(text).not.toContain('function ')
    expect(text).not.toContain('=>')
    expect(text).not.toContain('{{')
    expect(text).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u)
  })
})
