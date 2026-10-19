/**
 * AI 改版式痕迹条（`FormatChangeNote.vue`）的用例。
 *
 * 这一条补的是**一致性**：AI 标记（`AiBadge`）早就有了，但 AI 直接改版式
 * （字号 / 字体 / 行距 / 缩进）这条路上界面上什么都没有——用户回头看不出
 * "这段是谁动的"。用例盯四件事：
 * ① **自门控**：没有 changes 就整块不渲染（不出"AI 改了 0 处"这种空壳）；
 * ② ⭐ **不许编段号**：拿不到段号时说"若干处"，拿到几个就说几个；
 * ③ **折叠**：超过 5 个只列前 5 个再接「等 N 处」（全列会把提示条撑成两行）；
 * ④ **两个按钮是两件事**：`undo` / `dismiss` 各自 emit，互不冒充。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import FormatChangeNote from '../src/components/FormatChangeNote.vue'

/** `bun run test` 的 cwd 是 `frontend/`（与其它用例同一口径）。 */
const readSrc = (rel) => readFileSync(resolve(process.cwd(), rel), 'utf8')

/** 一条记录的形状（与 `WriteView.onDraftChangedByAi` 写进去的一致）。 */
function change(overrides = {}) {
  return {
    draftId: 1,
    versionId: null,
    blocks: [],
    summary: 'AI 改了版式',
    ...overrides,
  }
}

describe('FormatChangeNote 的显隐', () => {
  it('不传 changes 时整块不渲染（返回空）', () => {
    const wrapper = mount(FormatChangeNote)

    expect(wrapper.find('.fmt-note').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('changes 是空数组时同样不渲染（空壳会让人以为真发生了什么）', () => {
    const wrapper = mount(FormatChangeNote, { props: { changes: [] } })

    expect(wrapper.find('.fmt-note').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('有 changes 就渲染：报处数、列段号、给两个按钮', () => {
    const wrapper = mount(FormatChangeNote, {
      props: { changes: [change({ blocks: [2, 3] })] },
    })

    expect(wrapper.find('.fmt-note').exists()).toBe(true)
    const text = wrapper.text()
    expect(text).toContain('AI 改了 2 处版式')
    expect(text).toContain('（第 2、3 段）')

    const buttons = wrapper.findAll('button')
    expect(buttons).toHaveLength(2)
    expect(buttons.map((btn) => btn.text())).toEqual(['撤销这次改动', '知道了'])

    // 图标走 sprite（不是 emoji），且在提示条里
    expect(wrapper.find('.fmt-note svg use').attributes('href')).toBe('#i-spark')
  })
})

describe('段号文案（不许编）', () => {
  it('⭐ blocks 为空时只说「若干处」，不编任何段号', () => {
    const wrapper = mount(FormatChangeNote, { props: { changes: [change()] } })

    const text = wrapper.text()
    expect(text).toContain('AI 改了若干处版式')
    expect(text).toContain('具体段号没记下来')
    // "第 X 段"一个都不许出现（拿不到就是拿不到）
    expect(text).not.toMatch(/第\s*\d/)
  })

  it('段号超过 5 个就折叠：列出前 5 个 + 「等 N 处」，第 6 个不单列', () => {
    const wrapper = mount(FormatChangeNote, {
      props: { changes: [change({ blocks: [2, 3, 4, 5, 6, 7] })] },
    })

    const text = wrapper.text()
    expect(text).toContain('AI 改了 6 处版式')
    expect(text).toContain('（第 2、3、4、5、6… 等 6 处）')
    // 折叠后不该把第 6 个（段号 7）也铺出来
    expect(text).not.toContain('、7')
  })

  it('多批记录先并段号、去重、排序：处数按段数算，不按记录条数算', () => {
    const wrapper = mount(FormatChangeNote, {
      props: {
        changes: [
          change({ versionId: 7, blocks: [3, 1] }),
          change({ versionId: 8, blocks: [2, 1] }),
        ],
      },
    })

    const text = wrapper.text()
    expect(text).toContain('AI 改了 3 处版式')
    expect(text).toContain('（第 1、2、3 段）')
    expect(text).not.toContain('5 处')
  })
})

describe('两个按钮各管一件事', () => {
  it('点「撤销这次改动」emit undo（带上是哪一批）', async () => {
    const changes = [change({ blocks: [2] })]
    const wrapper = mount(FormatChangeNote, { props: { changes } })

    const buttons = wrapper.findAll('button')
    await buttons[0].trigger('click')

    expect(wrapper.emitted('undo')).toHaveLength(1)
    expect(wrapper.emitted('undo')[0][0]).toEqual(changes)
    // 撤销不等于"知道了"——不许同时把提示收掉
    expect(wrapper.emitted('dismiss')).toBeUndefined()
  })

  it('点「知道了」emit dismiss，且绝不触发 undo（只收提示、不碰稿子）', async () => {
    const changes = [change({ blocks: [2] })]
    const wrapper = mount(FormatChangeNote, { props: { changes } })

    const buttons = wrapper.findAll('button')
    await buttons[1].trigger('click')

    expect(wrapper.emitted('dismiss')).toHaveLength(1)
    expect(wrapper.emitted('dismiss')[0][0]).toEqual(changes)
    expect(wrapper.emitted('undo')).toBeUndefined()
  })

  it('默认摘要与标题句重复时不挂 title；更具体的摘要才作为说明露出', () => {
    const plain = mount(FormatChangeNote, { props: { changes: [change()] } })
    expect(plain.find('.fmt-note').attributes('title')).toBeUndefined()

    const detailed = mount(FormatChangeNote, {
      props: { changes: [change({ summary: '把第 2 至 4 段改成小四宋体' })] },
    })
    expect(detailed.find('.fmt-note').attributes('title')).toBe('把第 2 至 4 段改成小四宋体')
  })
})

/**
 * 写作页的接线（源码断言）：组件只有真挂上去、且传的是"空段号"，
 * 这条提示才既看得见、又**没有编段号**。渲染层已经由上面的 mount 用例覆盖。
 */
describe('写作页的接线', () => {
  const src = readSrc('src/views/WriteView.vue')

  it('⭐ 挂载点在正文上方（模板骨架提示条之前），且订阅了 undo / dismiss', () => {
    expect(src).toContain("import FormatChangeNote from '../components/FormatChangeNote.vue'")
    const mountAt = src.indexOf('<FormatChangeNote')
    const tplbarAt = src.indexOf('class="wr-tplbar"')
    expect(mountAt).toBeGreaterThan(-1)
    expect(tplbarAt).toBeGreaterThan(-1)
    expect(mountAt).toBeLessThan(tplbarAt)
    expect(src).toMatch(/@undo="undoAiFormatChange"/)
    expect(src).toMatch(/@dismiss="dismissAiFormatChange"/)
  })

  it('⭐ 记录时 blocks 必须是空数组（前端拿不到 changed_blocks，不许编段号）', () => {
    // 只在记这条提示的那一处判：周围不许出现 `blocks: [1, 2, 3]` 这种"看起来很真"的数字
    const at = src.indexOf('versionId: null')
    expect(at).toBeGreaterThan(-1)
    const around = src.slice(at, at + 220)
    expect(around).toContain('blocks: []')
    expect(around).not.toMatch(/blocks:\s*\[\s*\d/)

    // 撤销真的走版本回滚，且成功才说那句话
    expect(src).toContain('restoreVersion(target.id)')
    expect(src).toContain("'已回滚到改版式之前'")
  })
})
