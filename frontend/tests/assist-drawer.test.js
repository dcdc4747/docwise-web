/**
 * 断点缺口：1024–1099px 阅读页右栏改抽屉（形态 §3.4 第 2 档）。
 *
 * 这一条以前是**记录在案的缺口**（`docs/断点逐档量测记录_20261016.md` 第四节）：
 * 那一档 `.assist` 没有任何规则、只能继承 `≤1280` 的常驻形态，
 * 于是 1024 宽的窗口上左栏 260 + 右栏 340 吃掉 600px，正文只剩 764px。
 *
 * 缺口有三样东西要补，用例就盯这三样（**光有 CSS 不够**）：
 * 1. 抽屉形态的 CSS（照 `.wr-helper` 那套：fixed + translateX + 过渡）；
 * 2. 顶栏一个「助手」开关（`ReadView` 里此前没有任何 assist 开关）；
 * 3. 一个开合状态（`useUi.assistDrawerOpen`），且**默认收起**。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { beforeEach, describe, expect, it } from 'vitest'

import {
  assistClass,
  assistDrawerOpen,
  closeAssistDrawer,
  isNarrow,
  toggleAssistDrawer,
} from '../src/stores/useUi'

const readSrc = (rel) => readFileSync(resolve(process.cwd(), rel), 'utf8')

/** 剥注释（注释里会写 `translateX(100%)` 这种字样，不剥会把说明当成实现）。 */
const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '')
const CSS = stripComments(readSrc('src/style.css'))

/**
 * 取出**所有**同条件 `@media (...) {` 的整段（按花括号配平）。
 *
 * ⚠️ 必须返回数组：`@media (min-width: 1024px) and (max-width: 1099px)` 这条**写作页也用**
 * （`.wr-helper` 抽屉比阅读页先做）——只取第一个会拿到写作页那段，
 * 于是断言看起来"阅读页没有抽屉规则"，其实只是拿错了块（本用例第一版就这么假红过）。
 */
function mediaBlocks(css, condition) {
  const blocks = []
  let from = 0
  for (;;) {
    const start = css.indexOf(condition, from)
    if (start < 0) break
    const open = css.indexOf('{', start)
    let depth = 0
    let end = -1
    for (let i = open; i < css.length; i += 1) {
      if (css[i] === '{') depth += 1
      else if (css[i] === '}') {
        depth -= 1
        if (depth === 0) {
          end = i
          break
        }
      }
    }
    if (end < 0) break
    blocks.push(css.slice(open + 1, end))
    from = end + 1
  }
  return blocks
}

const BAND = mediaBlocks(CSS, '@media (min-width: 1024px) and (max-width: 1099px)')
/** 阅读页那段（写作页那段里是 `.wr-helper`）。 */
const READER_BAND = BAND.find((block) => block.includes('.dw .assist')) || ''

beforeEach(() => {
  assistDrawerOpen.value = false
  isNarrow.value = false
})

describe('助手抽屉的状态', () => {
  it('⭐ 默认收起（这一档正文要先拿回整宽）', () => {
    expect(assistDrawerOpen.value).toBe(false)
    expect(assistClass.value).toEqual(['assist', ''])
  })

  it('展开 / 收起 / Esc 关', () => {
    toggleAssistDrawer()
    expect(assistDrawerOpen.value).toBe(true)
    expect(assistClass.value).toContain('assist-open')
    toggleAssistDrawer()
    expect(assistDrawerOpen.value).toBe(false)
    toggleAssistDrawer()
    closeAssistDrawer()
    expect(assistDrawerOpen.value).toBe(false)
    // 幂等：已经收起时再关一次不报错
    closeAssistDrawer()
    expect(assistDrawerOpen.value).toBe(false)
  })

  it('手机上仍然是底部抽屉那套（别把两个状态混成一个）', () => {
    isNarrow.value = true
    expect(assistClass.value[0]).toBe('sheet')
    expect(assistClass.value).not.toContain('assist-open')
  })
})

describe('助手抽屉的 CSS（形如写作页 `.wr-helper` 的先例）', () => {
  it('⭐ 1024–1099 那一档确实存在抽屉规则（此前是缺口：一条都没有）', () => {
    expect(READER_BAND, '阅读页在这一档没有抽屉规则').not.toBe('')
    expect(READER_BAND).toContain('position: fixed')
    expect(READER_BAND).toContain('translateX(100%)')
    expect(READER_BAND).toContain('width: 340px')
    expect(READER_BAND).toContain('.dw .assist.assist-open { transform: none; }')
  })

  it('开关按钮：平时藏起来，只在这一档出现', () => {
    expect(CSS).toMatch(/\.dw \.assist-toggle \{ display: none; \}/)
    expect(READER_BAND).toMatch(/\.dw \.assist-toggle \{[^}]*display: inline-flex/)
  })

  it('⭐ 抽屉自己带关闭键（它会盖住顶栏那个开关，否则鼠标用户只有 Esc 一条路）', () => {
    const view = readSrc('src/views/ReadView.vue')
    expect(view).toContain('class="assist-close"')
    expect(view).toContain('@click="closeAssistDrawer"')
    expect(CSS).toMatch(/\.dw \.assist-close \{ display: none; \}/)
    expect(READER_BAND).toMatch(/\.dw \.assist-close \{[^}]*display: inline-flex/)
  })

  it('⚠️ ≥1100 不许把右栏也变成抽屉（规则必须关在那一档里）', () => {
    // 把所有同条件媒体查询整段删掉后，`translateX(100%)` 应当消失 ——
    // 说明抽屉形态没漏到通用规则里（漏出去的话 ≥1100 也会被推走）
    let rest = CSS
    for (const block of BAND) rest = rest.replace(block, '')
    expect(rest).not.toContain('translateX(100%)')
  })
})

describe('顶栏开关真的接上了', () => {
  it('ReadView 有「助手」按钮，绑定 toggleAssistDrawer，且开合文案/图标会变', () => {
    const view = readSrc('src/views/ReadView.vue')
    expect(view).toContain('assist-toggle')
    expect(view).toContain('@click="toggleAssistDrawer"')
    expect(view).toContain("assistDrawerOpen ? '收起助手' : '助手'")
    // 可访问性：展开状态要让读屏知道
    expect(view).toContain(':aria-expanded')
  })

  it('Esc 能关（键盘用户不必回去点按钮），且监听有解绑', () => {
    const view = readSrc('src/views/ReadView.vue')
    expect(view).toContain("event.key === 'Escape'")
    expect(view).toContain("addEventListener('keydown', onKeydown)")
    expect(view).toContain("removeEventListener('keydown', onKeydown)")
  })
})
