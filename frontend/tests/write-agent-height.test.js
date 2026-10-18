/**
 * 写作页 agent 面板的高度链守卫。
 *
 * 为什么只能守源码：happy-dom 不应用外部样式表，量不到"输入框到底在哪"。
 * 但这个 bug 属于**错了不会报红**那一类——每一级都是合法 CSS，
 * 只是 `.wr-helper-body` 是 display:block，`.wr-chat` 就只有内容高，
 * 输入框悬在面板中间（用户 2026-10-19 截图报的"对话框顶上去了"）。
 *
 * 修前的实测（真页面 1440×765）：
 *   `.wr-helper-body` h=664 / `.wr-chat` h=308 / `.agent-composer` bottom=411（面板底 765）
 * 修后：
 *   `.agent-pane` h=640 / `.agent-composer` bottom=743，距面板底 10px（与读懂页一致）
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const CSS = readFileSync(path.resolve(process.cwd(), 'src/style.css'), 'utf8')

/** 取某个选择器**最后一条**规则体（同选择器可能先有一条旧的，级联以下面那条为准）。 */
function ruleBody(selector) {
  const at = CSS.lastIndexOf(selector)
  if (at === -1) return ''
  const open = CSS.indexOf('{', at)
  const close = CSS.indexOf('}', open)
  return CSS.slice(open + 1, close)
}

describe('写作页 · agent 输入框贴底（高度链）', () => {
  it('.wr-helper-body 必须是可伸缩的列（否则子元素拿不到剩余高度）', () => {
    const body = ruleBody('.dw .wr-helper-body {')
    expect(body, 'style.css 里没有这条规则').not.toBe('')
    expect(body).toMatch(/display:\s*flex/)
    expect(body).toMatch(/flex-direction:\s*column/)
    expect(body).toMatch(/min-height:\s*0/)
  })

  it('.wr-chat 要吃掉剩余高度（flex:1 + min-height:0）', () => {
    const chat = ruleBody('.dw .wr-helper-body > .wr-chat {')
    expect(chat, 'style.css 里没有这条规则').not.toBe('')
    expect(chat).toMatch(/flex:\s*1\s+1\s+auto/)
    expect(chat).toMatch(/min-height:\s*0/)
  })

  it('.agent-pane 在写作页也要撑满（否则输入框又会被顶上去）', () => {
    const pane = ruleBody('.dw .wr-helper-body > .wr-chat > .agent-pane {')
    expect(pane, 'style.css 里没有这条规则').not.toBe('')
    expect(pane).toMatch(/flex:\s*1\s+1\s+auto/)
    expect(pane).toMatch(/min-height:\s*0/)
  })
})
