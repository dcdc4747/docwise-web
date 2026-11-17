/**
 * 焦点回收（全端检查 G3，2026-11-17）的用例。
 *
 * 为什么单独测：这层逻辑**错了不会崩**，只会让键盘用户的焦点悄悄落回 `body` ——
 * 抓不住就只能靠人肉走查（上一轮就是这么漏掉的）。
 */

import { readFileSync } from 'node:fs'
import path from 'node:path'

import { afterEach, describe, expect, it, vi } from 'vitest'

import { rememberFocus, returnFocus } from '../src/focusReturn'

const readSrc = (file) => readFileSync(path.resolve(process.cwd(), file), 'utf8')

afterEach(() => {
  document.body.innerHTML = ''
})

describe('rememberFocus', () => {
  it('什么都没聚焦时返回 null（别把 body / documentElement 当成"打开它的那个元素"）', () => {
    expect(rememberFocus()).toBeNull()
    expect(rememberFocus(null)).toBeNull()
    const fake = { activeElement: { tagName: 'HTML' }, body: { tagName: 'BODY' } }
    fake.documentElement = fake.activeElement
    expect(rememberFocus(fake)).toBeNull()
  })

  it('焦点在哪就记哪（按钮 / 输入框都算）', () => {
    document.body.innerHTML = '<button id="trigger">打开</button><input id="field" />'
    const button = document.getElementById('trigger')
    button.focus()
    expect(document.activeElement).toBe(button)
    expect(rememberFocus()).toBe(button)
  })
})

describe('returnFocus', () => {
  it('把焦点真的还回去', () => {
    document.body.innerHTML = '<button id="trigger">打开</button><button id="other">别处</button>'
    const button = document.getElementById('trigger')
    document.getElementById('other').focus()

    expect(returnFocus(button)).toBe(true)
    expect(document.activeElement).toBe(button)
  })

  it('没有可还的东西时什么都不做（不抛、不假装成功）', () => {
    expect(returnFocus(null)).toBe(false)
    expect(returnFocus(undefined)).toBe(false)
    expect(returnFocus({})).toBe(false)
  })

  it('元素已被卸载就不还——对着脱离文档的节点调 focus 是空操作', () => {
    const detached = document.createElement('button')
    detached.focus = vi.fn()
    expect(detached.isConnected).toBe(false)

    expect(returnFocus(detached)).toBe(false)
    expect(detached.focus).not.toHaveBeenCalled()
  })
})

/**
 * 三处弹层的**接线**守卫。
 *
 * 行为层面的真用例在 `check-drawer.test.js`（真挂载写作页、真按 Esc、真断言
 * `document.activeElement` 回到那颗按钮）。这里只防"有人把接线删了而没人发现"——
 * 被删掉时行为用例会红，但红在一个看不出因果的地方。
 */
describe('三处弹层都接上了焦点回收', () => {
  it('校对抽屉（写作页）：打开时记、关掉时还', () => {
    const source = readSrc('src/views/WriteView.vue')
    expect(source).toContain('rememberFocus()')
    expect(source).toContain('returnFocus(checkOpener)')
  })

  it('助手抽屉（阅读页）：Esc 关掉之后还给开关按钮', () => {
    const source = readSrc('src/views/ReadView.vue')
    expect(source).toContain('ref="assistToggleEl"')
    expect(source).toContain('returnFocus(assistToggleEl.value)')
  })

  it('设置弹窗：Esc 能关（此前只能摸回 ×），关掉之后焦点还回去', () => {
    const source = readSrc('src/components/AgentSettings.vue')
    expect(source).toContain("event.key === 'Escape'")
    expect(source).toContain('returnFocus(settingsOpener)')
  })
})
