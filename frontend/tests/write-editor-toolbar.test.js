/**
 * 编辑器工具栏的守卫（2026-10-19）。
 *
 * 为什么守源码：TipTap 在 happy-dom 里跑不了（需要真实 DOM 量测），
 * 但"工具栏有没有这些能力"是**产品承诺**，不该只靠人眼点一遍：
 * 用户明确要过 **字体 / 字号 / 行距 / 段距 / 标题级别**，少一个就是功能缺失。
 *
 * 同时守住两条转换口径（它们决定"改了能不能存住"）：
 *  ① 带 style 的 span 必须原样保留（否则字号/字体一保存就丢）；
 *  ② style 里的双引号必须转义（字体名自带引号，不转义会把 HTML 属性截断）。
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const read = (p) => readFileSync(path.resolve(process.cwd(), p), 'utf8')
const EDITOR = read('src/components/WriteEditor.vue')
const RICH = read('src/writeRich.js')

describe('写作编辑器 · 工具栏能力', () => {
  it('字体选择在（逐处生效，不是整篇）', () => {
    expect(EDITOR).toContain('FONT_FAMILIES')
    expect(EDITOR).toContain('setFontFamily')
    expect(EDITOR).toMatch(/font-family/)
  })

  it('字号选择在，且走 textStyle mark（逐处）', () => {
    expect(EDITOR).toContain('FONT_SIZES')
    expect(EDITOR).toContain('setFontSize')
    expect(EDITOR).toMatch(/font-size/)
  })

  it('标题级别 / 加粗 / 斜体 / 对齐 / 列表 / 引用都在', () => {
    for (const name of [
      'setHeading',
      'toggleBold',
      'toggleItalic',
      'setTextAlign',
      'toggleBulletList',
      'toggleOrderedList',
      'toggleBlockquote',
    ]) {
      expect(EDITOR, `缺 ${name}`).toContain(name)
    }
  })

  it('行距 / 段距 / 缩进在（文档级）', () => {
    expect(EDITOR).toContain('lineHeight')
    expect(EDITOR).toContain('paraSpacing')
    expect(EDITOR).toContain('indent')
  })

  it('转换层保留内联样式，且转义双引号', () => {
    expect(RICH).toContain('keepInlineStyle')
    expect(RICH).toMatch(/&quot;/)
  })

  it('字体回显做了归一化（存进去是双引号、选项里是单引号）', () => {
    expect(EDITOR).toContain('normalizeFamily')
  })
})
