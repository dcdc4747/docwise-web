/**
 * 卡③ 知识库筛选区（`LibFilters.vue`，issue #111）的用例。
 *
 * 这个组件**只出筛选条**（取数与列表归页面），所以它的价值全在三条纪律上：
 * ① 筛选**能清空**（点当前档 = 取消，且随时有「清除筛选」出口）；
 * ② ⭐「有文献但被筛没了」要说清**是筛选造成的** + 给出路，**绝不说"暂无数据"**；
 * ③ 智能集合的**规则必须露出来**（规则不说出来，它就是一条写死的按钮）。
 */

import { readFileSync } from 'node:fs'
import path from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import LibFilters from '../src/components/LibFilters.vue'

const collections = [
  { id: 1, name: '手性课题', count: 3 },
  { id: 2, name: '待复现', count: 2 },
]
const tags = [{ name: '手性' }, { name: '酶催化' }]
const smartCollections = [
  {
    id: 1,
    name: '待读',
    query: { all: [{ field: 'reading_status', op: 'eq', value: 'todo' }] },
    count: 3,
    builtin: true,
  },
]

const readStyle = () => readFileSync(path.resolve(process.cwd(), 'src/style.css'), 'utf8')

/** 按可见文案找一颗筛选芯片。 */
function chip(wrapper, text) {
  return wrapper.findAll('button.lib-chip').find((item) => item.text().startsWith(text))
}

describe('LibFilters 知识库筛选区', () => {
  it('状态四档：点「待读」发出 `reading_status=todo`，点「全部」把它清掉', async () => {
    const wrapper = mount(LibFilters)

    await chip(wrapper, '待读').trigger('click')
    expect(wrapper.emitted('change').at(-1)[0]).toEqual({ reading_status: 'todo' })

    await wrapper.setProps({ filters: { reading_status: 'todo' } })
    await chip(wrapper, '全部').trigger('click')
    expect(wrapper.emitted('change').at(-1)[0]).toEqual({})
  })

  it('集合 / 标签也走同一条路：点一次筛上，再点一次取消（筛选能清空）', async () => {
    const wrapper = mount(LibFilters, { props: { collections, tags } })

    await chip(wrapper, '手性课题').trigger('click')
    expect(wrapper.emitted('change').at(-1)[0]).toEqual({ collection_id: 1 })

    await wrapper.setProps({ filters: { collection_id: 1 } })
    await chip(wrapper, '手性课题').trigger('click')
    expect(wrapper.emitted('change').at(-1)[0]).toEqual({})

    await wrapper.setProps({ filters: {} })
    await chip(wrapper, '酶催化').trigger('click')
    // 契约字段是 `tag[]`（数组）——发出去的就是数组，不是一个字符串
    expect(wrapper.emitted('change').at(-1)[0]).toEqual({ tag: ['酶催化'] })
  })

  it('⭐ 标签是**多选**（`tag[]`）：加一个进数组、再点同一个从数组里去掉', async () => {
    const wrapper = mount(LibFilters, { props: { tags, filters: { tag: ['手性'] } } })

    // 已经选中的那颗是选中态
    expect(chip(wrapper, '手性').classes()).toContain('is-on')

    await chip(wrapper, '酶催化').trigger('click')
    expect(wrapper.emitted('change').at(-1)[0]).toEqual({ tag: ['手性', '酶催化'] })

    await wrapper.setProps({ filters: { tag: ['手性', '酶催化'] } })
    await chip(wrapper, '手性').trigger('click')
    expect(wrapper.emitted('change').at(-1)[0]).toEqual({ tag: ['酶催化'] })

    // 「当前」那一行要把两个标签都念出来
    expect(wrapper.find('.lib-fl-sum').text()).toContain('标签：手性 / 酶催化')
  })

  it('宿主只给了 shown、没给 total → 出口照样出，但说明要诚实（说不清是筛没了还是库是空的）', () => {
    const wrapper = mount(LibFilters, {
      props: { filters: { reading_status: 'todo' }, shown: 0 },
    })

    const empty = wrapper.find('.empty')
    expect(empty.exists()).toBe(true)
    const desc = empty.find('.empty-desc').text()
    expect(desc).toContain('说不清')
    expect(desc).toContain('先清除筛选看看')
    expect(wrapper.text()).not.toContain('暂无数据')
  })

  it('⭐ 自跑模式：不登录取数也能看到筛选条，且点击是真的在筛（筛空了当场给出口）', async () => {
    const wrapper = mount(LibFilters, { props: { demo: true } })

    // ① 标明"这是示例数据"（示例不标注就成了假数据）
    expect(wrapper.find('.hnote').text()).toContain('自跑模式')
    expect(wrapper.find('.hnote').text()).toContain('示例数据')

    // ② 示例库 4 篇，默认筛「待读」→ 2 篇，所以还没有空态
    expect(wrapper.find('.lib-fl-sum').text()).toContain('状态：待读')
    expect(wrapper.find('.empty').exists()).toBe(false)

    // ③ 点一个示例里必然筛空的智能集合（「扫描件」）→ 出口当场出现
    const scan = wrapper
      .findAll('button.lib-chip')
      .find((item) => item.text().startsWith('扫描件'))
    await scan.trigger('click')

    const empty = wrapper.find('.empty')
    expect(empty.exists()).toBe(true)
    expect(empty.find('.empty-desc').text()).toContain('库里共 4 篇')
    expect(empty.find('.empty-desc').text()).toContain('智能集合：扫描件')

    // ④ 出口当场能用（自跑模式下清的是本地示例筛选）
    await wrapper.find('button.empty-clear').trigger('click')
    expect(wrapper.find('.empty').exists()).toBe(false)
    expect(wrapper.emitted('clear')).toBeUndefined()
  })

  it('⭐ 智能集合的规则必须露出来（悬停能看到"规则：状态 = 待读"，键盘用户也能听到）', () => {
    const wrapper = mount(LibFilters, { props: { smartCollections } })

    // 状态行里也有一颗「待读」，所以按"带规则说明"来认智能集合那一颗
    const smart = wrapper
      .findAll('button.lib-chip')
      .find((item) => item.attributes('title') !== undefined)
    expect(smart).toBeTruthy()
    expect(smart.attributes('title')).toBe('规则：状态 = 待读')
    expect(smart.attributes('aria-label')).toContain('规则：状态 = 待读')
  })

  it('⭐ 有文献但被筛没了：说清是筛选造成的 + 给出口，且绝不说"暂无数据"', async () => {
    const wrapper = mount(LibFilters, {
      props: { filters: { reading_status: 'todo' }, total: 9, shown: 0 },
    })

    const empty = wrapper.find('.empty')
    expect(empty.exists()).toBe(true)
    expect(empty.find('.empty-title').text()).toBe('这个筛选下没有文献')

    // 说清"是筛选造成的"，并带上库里真实篇数
    const desc = empty.find('.empty-desc').text()
    expect(desc).toContain('筛选')
    expect(desc).toContain('9')

    expect(wrapper.text()).not.toContain('暂无数据')

    const clear = wrapper.find('button.empty-clear')
    await clear.trigger('click')
    expect(wrapper.emitted('clear')).toHaveLength(1)
  })

  it('库里本来就是空的（没筛、total=0）→ 不许在这里冒充"筛空了"（那是页面的真空态）', () => {
    const wrapper = mount(LibFilters, { props: { total: 0, shown: 0 } })

    expect(wrapper.find('.empty').exists()).toBe(false)
  })

  it('有筛选时给出「当前」一行与「清除筛选」；没筛选时这一行整块不出现', async () => {
    const wrapper = mount(LibFilters, { props: { collections } })
    expect(wrapper.find('.lib-fl-clear').exists()).toBe(false)

    await wrapper.setProps({ filters: { collection_id: 1 } })
    expect(wrapper.find('.lib-fl-sum').text()).toContain('集合：手性课题')

    await wrapper.find('button.lib-fl-clear').trigger('click')
    expect(wrapper.emitted('clear')).toHaveLength(1)
  })

  it('没有集合 / 标签 / 智能集合时，那几行整块不渲染（不摆空壳）', () => {
    const wrapper = mount(LibFilters)

    expect(wrapper.findAll('.lib-fl-row')).toHaveLength(1)
  })

  it('样式按 token 走：芯片与概况行都不写死色值', () => {
    const css = readStyle()

    const chipStart = css.indexOf('.dw .lib-chip {')
    expect(chipStart).toBeGreaterThan(-1)
    const chipRule = css.slice(chipStart, chipStart + 300)
    expect(chipRule).toContain('var(--')
    expect(chipRule).not.toMatch(/#[0-9a-f]{3,6}/i)

    const lineStart = css.indexOf('.dw .lib-ov-line')
    expect(lineStart).toBeGreaterThan(-1)
    expect(css.slice(lineStart, lineStart + 200)).toContain('tabular-nums')
  })

  it('渲染出来的文本不含源码痕迹、也不含 emoji', () => {
    const wrapper = mount(LibFilters, {
      props: { collections, tags, smartCollections, total: 9, shown: 0, filters: { tag: '手性' } },
    })

    const text = wrapper.text()
    expect(text).not.toContain('function ')
    expect(text).not.toContain('=>')
    expect(text).not.toContain('{{')
    expect(text).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u)
  })
})
