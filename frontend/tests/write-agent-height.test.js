/**
 * 右栏助手骨架（AssistPane）的守卫用例。
 *
 * 为什么守源码而不守渲染：happy-dom **不应用外部样式表**，量不到"输入框在哪"。
 * 但这个 bug 属于"错了不报红"那一类——每一条 CSS 都合法，
 * 只是高度链上某一级不参与 flex，输入框就悬到面板中间（已经犯过三次：
 * 读懂页的 237px 中间节点、模型下拉的定位容器、写作页的 display:block）。
 *
 * 所以这里钉两件事：
 *  ① 两个页面都必须走同一个骨架组件（不许各自写一套容器）；
 *  ② 骨架里的高度链必须完整（`flex:1` + `min-height:0` 缺一不可）。
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const read = (p) => readFileSync(path.resolve(process.cwd(), p), 'utf8')
const CSS = read('src/style.css')

/** 取某个选择器**最后一条**规则体（同选择器可能先有旧规则，级联以下面那条为准）。 */
function ruleBody(selector) {
  const at = CSS.lastIndexOf(selector)
  if (at === -1) return ''
  const open = CSS.indexOf('{', at)
  const close = CSS.indexOf('}', open)
  return CSS.slice(open + 1, close)
}

describe('右栏助手骨架 · AssistPane', () => {
  it('两个页面都复用它（不再各自写容器）', () => {
    for (const view of ['src/views/ReadView.vue', 'src/views/WriteView.vue']) {
      const src = read(view)
      expect(src, `${view} 没有用 AssistPane`).toContain('<AssistPane')
      expect(src, `${view} 没有导入 AssistPane`).toContain(
        "import AssistPane from '../components/AssistPane.vue'",
      )
    }
  })

  it('骨架的高度链完整（可伸缩列 + 吃掉剩余高度）', () => {
    const root = ruleBody('.dw .assist-pane {')
    expect(root, 'style.css 缺 .assist-pane').not.toBe('')
    expect(root).toMatch(/display:\s*flex/)
    expect(root).toMatch(/flex-direction:\s*column/)
    expect(root).toMatch(/min-height:\s*0/)

    const body = ruleBody('.dw .assist-pane-body {')
    expect(body, 'style.css 缺 .assist-pane-body').not.toBe('')
    expect(body).toMatch(/flex:\s*1\s+1\s+auto/)
    expect(body).toMatch(/min-height:\s*0/)
  })

  it('页签之外的东西不许塞进 .tabs（读懂页契约：只有三个页签）', () => {
    const pane = read('src/components/AssistPane.vue')
    // above-tabs 插槽必须在 `.tabs` **之前**
    const slot = pane.indexOf('name="above-tabs"')
    const tabs = pane.indexOf('class="tabs"')
    expect(slot).toBeGreaterThan(-1)
    expect(tabs).toBeGreaterThan(slot)
  })

  it('写作页的 agent 包装层仍要吃掉剩余高度', () => {
    const chat = ruleBody('.dw .wr-helper-body > .wr-chat {')
    expect(chat, 'style.css 缺 .wr-helper-body > .wr-chat').not.toBe('')
    expect(chat).toMatch(/flex:\s*1\s+1\s+auto/)
    expect(chat).toMatch(/min-height:\s*0/)
  })
})
