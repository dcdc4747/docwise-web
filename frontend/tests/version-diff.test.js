/**
 * 版本对比（VersionDiff）用例。
 *
 * 这个组件是**纯展示**的：不请求接口、不碰 store，只把两段正文的差异摆出来。
 * 所以这里钉两件事：
 *  ① `diffLines` 的契约——返回 `[{type, text}]`，超长时带 `fallback` 标记；
 *  ② 组件真的按契约渲染——摘要、前缀、行号、特殊字符，以及超长退化成两栏。
 *
 * ⚠️ 特殊字符那条必须真挂载：`v-html` 一旦被后人加回来，`<script>` 就会变成元素，
 * 只读源码的断言挡不住这种回归。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import VersionDiff, { diffLines, MAX_DIFF_LINES } from '../src/components/VersionDiff.vue'

const typesOf = (rows) => rows.map((row) => row.type)
const textsOf = (rows) => rows.map((row) => row.text)

function render(before, after, props = {}) {
  return mount(VersionDiff, { props: { before, after, ...props } })
}

/** 3000+ 行的正文：用来验证退化路径，不真跑 LCS。 */
function longText(count, prefix) {
  return Array.from({ length: count }, (_, index) => `${prefix} ${index}`).join('\n')
}

describe('diffLines · 行级 diff', () => {
  it('相同文本全部是 same，返回值仍是干净的 {type, text} 数组', () => {
    const text = '第一行\n第二行\n第三行'
    const rows = diffLines(text, text)

    expect(rows.fallback).toBe(false)
    expect(rows).toEqual([
      { type: 'same', text: '第一行' },
      { type: 'same', text: '第二行' },
      { type: 'same', text: '第三行' },
    ])
    // fallback 是非枚举属性：不污染行数组本身（上面的 toEqual 就是证据，这里再钉一次）
    expect(Object.keys(rows)).toEqual(['0', '1', '2'])
  })

  it('纯新增：before 为空时全部是 add，且保持原顺序', () => {
    const rows = diffLines('', 'A\nB\nC')

    expect(rows.fallback).toBe(false)
    expect(typesOf(rows)).toEqual(['add', 'add', 'add'])
    expect(textsOf(rows)).toEqual(['A', 'B', 'C'])
  })

  it('纯删除：after 为空时全部是 del', () => {
    const rows = diffLines('A\nB\nC', '')

    expect(typesOf(rows)).toEqual(['del', 'del', 'del'])
    expect(textsOf(rows)).toEqual(['A', 'B', 'C'])
  })

  it('中间插入一行：只多一条 add，前后行仍是 same', () => {
    const rows = diffLines('a\nb\nc', 'a\nb\nX\nc')

    expect(typesOf(rows)).toEqual(['same', 'same', 'add', 'same'])
    expect(textsOf(rows)).toEqual(['a', 'b', 'X', 'c'])
  })

  it('首尾空行（含只含空白的行）被忽略，不进入 diff', () => {
    const rows = diffLines('\n \nA\nB\n\n', '\t\nA\nB\n\n  ')

    expect(rows).toHaveLength(2)
    expect(typesOf(rows)).toEqual(['same', 'same'])
    expect(textsOf(rows)).toEqual(['A', 'B'])
  })

  it('中间的空行保留（它不是"首尾空行"）', () => {
    const rows = diffLines('a\n\nb', 'a\n\nb')

    expect(typesOf(rows)).toEqual(['same', 'same', 'same'])
    expect(textsOf(rows)).toEqual(['a', '', 'b'])
  })

  it('空 before / 空 after / 两边都空，都不抛异常', () => {
    expect(diffLines('', '')).toHaveLength(0)
    expect(diffLines('   \n\n', '\t')).toHaveLength(0)
    expect(diffLines('', '')).toHaveProperty('fallback', false)
  })

  it('CRLF / CR 也按行切（不把 \\r 留在行尾）', () => {
    const rows = diffLines('a\r\nb', 'a\r\nc')

    expect(typesOf(rows)).toEqual(['same', 'del', 'add'])
    expect(textsOf(rows)).toEqual(['a', 'b', 'c'])
  })

  it('同一段里删除排在新增前面（红一行绿一行会难读）', () => {
    const rows = diffLines('a\nDELETE', 'a\nADD1\nADD2')

    expect(typesOf(rows)).toEqual(['same', 'del', 'add', 'add'])
    expect(textsOf(rows)).toEqual(['a', 'DELETE', 'ADD1', 'ADD2'])
  })

  it('上限边界：正好 3000 行不退化', () => {
    const text = longText(MAX_DIFF_LINES, '第')
    const rows = diffLines(text, text)

    expect(MAX_DIFF_LINES).toBe(3000)
    expect(rows.fallback).toBe(false)
    expect(rows).toHaveLength(MAX_DIFF_LINES)
    expect(rows.every((row) => row.type === 'same')).toBe(true)
  })

  it('超过 3000 行退化成"整段前 / 整段后"：fallback=true，不跑 LCS', () => {
    const count = MAX_DIFF_LINES + 1
    const rows = diffLines(longText(count, '旧'), longText(count, '新'))

    expect(rows.fallback).toBe(true)
    expect(rows).toHaveLength(count * 2)
    // 不复用任何 same：整段旧文在前，整段新文在后
    expect(rows.slice(0, count).every((row) => row.type === 'del')).toBe(true)
    expect(rows.slice(count).every((row) => row.type === 'add')).toBe(true)
    expect(rows[0]).toEqual({ type: 'del', text: '旧 0' })
    expect(rows[count]).toEqual({ type: 'add', text: '新 0' })
  })

  it('超长但两版一模一样：仍走两栏，但不能把"没改"说成"全改了"', () => {
    const text = longText(MAX_DIFF_LINES + 5, '同一行')
    const rows = diffLines(text, text)

    expect(rows.fallback).toBe(true)
    expect(rows).toHaveLength(MAX_DIFF_LINES + 5)
    expect(rows.every((row) => row.type === 'same')).toBe(true)
  })
})

describe('VersionDiff · 渲染', () => {
  it('顶部摘要：「新增 X 行，删除 Y 行」', () => {
    const wrapper = render('one\ntwo\nthree', 'one\nTWO\nthree\nfour')

    expect(wrapper.find('.vd-summary').text().trim()).toBe('新增 2 行，删除 1 行')
    expect(wrapper.find('.vd-summary').classes()).not.toContain('is-same')
  })

  it('没有差异时显示「这一版和当前稿一样」', () => {
    const wrapper = render('一样\n两行', '一样\n两行')

    const summary = wrapper.find('.vd-summary')
    expect(summary.text().trim()).toBe('这一版和当前稿一样')
    expect(summary.classes()).toContain('is-same')
    expect(summary.text()).not.toContain('新增')
  })

  it('add 绿底带 `+ `、del 红底带 `- `、same 灰字不带前缀', () => {
    const wrapper = render('same\nold', 'same\nnew')

    const same = wrapper.find('.vd-line-same')
    expect(same.find('.vd-sign').element.textContent).toBe('')
    expect(same.find('.vd-text').text()).toBe('same')

    const added = wrapper.find('.vd-line-add')
    expect(added.find('.vd-sign').element.textContent).toBe('+ ')
    expect(added.find('.vd-text').text()).toBe('new')

    const removed = wrapper.find('.vd-line-del')
    expect(removed.find('.vd-sign').element.textContent).toBe('- ')
    expect(removed.find('.vd-text').text()).toBe('old')

    // data-type 是给样式/测试的稳定钩子，颜色不是唯一语义
    expect(added.attributes('data-type')).toBe('add')
    expect(removed.attributes('data-type')).toBe('del')
  })

  it('行号默认不显示；showLineNumbers 时 before / after 各自从 1 计数', () => {
    expect(render('a', 'b').findAll('.vd-no')).toHaveLength(0)

    const wrapper = render('a\nb', 'a\nc', { showLineNumbers: true })
    const gutters = wrapper
      .findAll('.vd-line')
      .map((line) => line.findAll('.vd-no').map((node) => node.text()))

    expect(gutters).toEqual([
      ['1', '1'], // same a
      ['2', ''], // del b
      ['', '2'], // add c
    ])
  })

  it('两边都空：摘要说一样，并给出空态（不渲染假的 diff 行）', () => {
    const wrapper = render('', '')

    expect(wrapper.find('.vd-summary').text().trim()).toBe('这一版和当前稿一样')
    expect(wrapper.find('.vd-empty').text()).toBe('两边都没有正文。')
    expect(wrapper.findAll('.vd-line')).toHaveLength(0)
  })

  it('不传 before / after 也能挂载（props 有默认空串）', () => {
    const wrapper = mount(VersionDiff)

    expect(wrapper.find('.vd-summary').text().trim()).toBe('这一版和当前稿一样')
    expect(wrapper.find('.vd-empty').exists()).toBe(true)
  })

  it('⭐ 特殊字符按文本渲染：不生成元素、不执行脚本、不用 v-html', () => {
    const evil = '<script>alert("x")</script>'
    const wrapper = render('safe', `${evil}\nA & B > C < D`)

    // 文本节点里是原字面量；HTML 里被转义
    const texts = wrapper.findAll('.vd-line-add .vd-text').map((node) => node.text())
    expect(texts).toEqual([evil, 'A & B > C < D'])
    expect(wrapper.findAll('script')).toHaveLength(0)
    expect(wrapper.html()).toContain('&lt;script&gt;')
    expect(wrapper.html()).not.toContain('<script')
    expect(wrapper.html()).not.toContain('v-html')
  })

  it('⭐ 源码里没有 v-html（正文只能走插值）', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/components/VersionDiff.vue'),
      'utf8',
    )
    expect(source).not.toMatch(/v-html/)
  })

  it('超长退化渲染成前后两栏，不再逐行渲染', () => {
    const count = MAX_DIFF_LINES + 1
    const wrapper = render(longText(count, '旧'), longText(count, '新'))

    expect(wrapper.find('.vd-columns').exists()).toBe(true)
    expect(wrapper.findAll('.vd-col')).toHaveLength(2)
    expect(wrapper.findAll('.vd-pre')).toHaveLength(2)
    expect(wrapper.findAll('.vd-line')).toHaveLength(0)

    expect(wrapper.find('.vd-note').text()).toContain('超过 3000 行')
    expect(wrapper.find('.vd-note').text()).toContain('不做逐行比对')
    expect(wrapper.find('.vd-summary').text().trim()).toBe(
      `新增 ${count} 行，删除 ${count} 行`,
    )
    expect(wrapper.find('.vd-colhead').text()).toBe(`改动前 · ${count} 行`)

    const columns = wrapper.findAll('.vd-pre').map((node) => node.text())
    expect(columns[0]).toContain('旧 0')
    expect(columns[1]).toContain('新 0')
  })

  it('超长但两版相同：两栏照出，摘要仍是「这一版和当前稿一样」', () => {
    const text = longText(MAX_DIFF_LINES + 5, '同一行')
    const wrapper = render(text, text)

    expect(wrapper.find('.vd-columns').exists()).toBe(true)
    expect(wrapper.find('.vd-summary').text().trim()).toBe('这一版和当前稿一样')
    // 内容相同时提示里不该出现"摘要按整段计"（那会让用户以为有改动）
    expect(wrapper.find('.vd-note').text()).not.toContain('摘要按整段计')

    const columns = wrapper.findAll('.vd-pre').map((node) => node.text())
    expect(columns[0]).toBe(text)
    expect(columns[1]).toBe(text)
  })
})
