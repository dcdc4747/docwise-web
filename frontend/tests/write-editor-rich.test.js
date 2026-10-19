/**
 * 编辑器能插图、能插表（2026-10-19）。
 *
 * 为什么是源码级 + 纯函数级：TipTap/ProseMirror 需要真实 DOM 量测，happy-dom 里挂不起来。
 * 但"有没有这个能力"是产品承诺（用户明确要图与表），所以钉三件事：
 * 扩展真的注册了、工具栏真有入口、转换层不会把图片和表格吃掉。
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { htmlToMd, mdToHtml } from '../src/writeRich'

const EDITOR = readFileSync(
  path.resolve(process.cwd(), 'src/components/WriteEditor.vue'),
  'utf8',
)

describe('编辑器 · 插图与表格', () => {
  it('注册了 Image 与 Table 系列扩展（命名导出，v3 没有默认导出）', () => {
    expect(EDITOR).toContain("from '@tiptap/extension-image'")
    expect(EDITOR).toContain("from '@tiptap/extension-table'")
    expect(EDITOR).toMatch(/Image\.configure\(/)
    expect(EDITOR).toMatch(/Table\.configure\(/)
    expect(EDITOR).toContain('TableRow')
    expect(EDITOR).toContain('TableHeader')
    expect(EDITOR).toContain('TableCell')
  })

  it('工具栏有插图与插表入口，表格里才有那五个操作', () => {
    expect(EDITOR).toContain('pickImage')
    expect(EDITOR).toContain('insertTable')
    expect(EDITOR).toContain('tableCmd')
    expect(EDITOR).toMatch(/v-if="inTable"/)
    for (const label of ['＋行', '＋列', '－行', '－列', '删表']) {
      expect(EDITOR, `缺 ${label}`).toContain(label)
    }
  })

  it('插图走本地 dataURL，且有体积上限（不静默失败）', () => {
    expect(EDITOR).toContain('readAsDataURL')
    expect(EDITOR).toMatch(/1_500_000|1500000/)
    expect(EDITOR).toContain("emit('image-error'")
  })

  it('图片在 Markdown 往返里原样保留', () => {
    const html = '<p>看图</p><img src="data:image/png;base64,AAA" alt="图1">'
    const md = htmlToMd(html)
    expect(md).toContain('<img')
    expect(md).toContain('data:image/png')
    expect(mdToHtml(md)).toContain('<img')
  })

  it('表格在 Markdown 往返里原样保留（不能被拆成纯文本）', () => {
    const html =
      '<table><thead><tr><th>列A</th></tr></thead>' +
      '<tbody><tr><td>1</td></tr></tbody></table>'
    const md = htmlToMd(html)
    expect(md).toContain('<table')
    const back = mdToHtml(md)
    expect(back).toContain('<table')
    expect(back).toContain('列A')
  })
})
