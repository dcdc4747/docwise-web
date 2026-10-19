/**
 * 块级样式能不能"活着往返"（2026-10-19，真页面踩过的坑）。
 *
 * 事故经过：AI 把字号写在 `<p style="font-size:17px">` 上，结果
 * ① 编辑器 schema 没声明块级样式属性 → TipTap 解析时**静默丢掉**；
 * ② Markdown 转换也丢 → AI 再写一句正文走 `md → html` 会把整篇版式抹掉。
 * 表现就是"模型说改了、界面没变"，而且不报错。
 *
 * 所以这里钉三件事：
 *  - HTML 里的块级 style 经 `htmlToMd → mdToHtml` 仍在；
 *  - 编辑器声明了这些属性（否则渲染时又丢）；
 *  - 段落级样式不会被当成"未知标签"吞掉。
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { htmlToMd, mdToHtml } from '../src/writeRich'

const STYLED = '<p style="font-family: 黑体; font-size: 17px; line-height: 1.9;">摘要正文</p>'

describe('块级样式往返', () => {
  it('html → md 保留块级 style（原样内联 HTML）', () => {
    const md = htmlToMd(STYLED)
    expect(md).toContain('font-size: 17px')
    expect(md).toContain('黑体')
  })

  it('md → html 仍带着块级 style', () => {
    const round = mdToHtml(htmlToMd(STYLED))
    expect(round).toContain('font-size: 17px')
    expect(round).toContain('摘要正文')
  })

  it('二次往返也不丢（幂等）', () => {
    const once = mdToHtml(htmlToMd(STYLED))
    const twice = mdToHtml(htmlToMd(once))
    expect(twice).toContain('font-size: 17px')
  })

  it('没有样式的普通段落不被包成内联 HTML（别把 Markdown 弄脏）', () => {
    const md = htmlToMd('<p>普通一段</p>')
    expect(md).not.toContain('<p')
    expect(md.trim()).toBe('普通一段')
  })

  it('编辑器声明了块级样式属性（fontFamily / fontSize / lineHeight / textIndent）', () => {
    const source = readFileSync(
      path.resolve(process.cwd(), 'src/components/WriteEditor.vue'),
      'utf8',
    )
    expect(source).toContain('BlockStyle')
    for (const key of ['fontFamily', 'fontSize', 'lineHeight', 'textIndent']) {
      expect(source).toContain(key)
    }
    // 挂上扩展才算数：只定义不注册等于没有
    expect(source).toMatch(/FontFamily,\s*\n\s*BlockStyle,/)
  })
})
