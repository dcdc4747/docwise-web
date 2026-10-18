/**
 * 写作页的富文本 ⇄ Markdown 转换层（**纯函数**，不发请求、不碰 DOM 之外的东西）。
 *
 * 为什么要有这一层：
 * - 库里的稿子仍是 **Markdown**（`drafts.body_md`）：引文 `[n]`、大纲 `#` 解析、
 *   导出、AI 写入的锚点校验，全都按 Markdown 做；
 * - 编辑器是 **HTML**（TipTap/ProseMirror）。
 * 两者互转只此一处，坏也只坏一处，而且能被 vitest 钉住。
 *
 * 口径（刻意保守）：
 * 1. **不认识的 HTML 原样保留**，不猜、不丢；
 * 2. Markdown 只认我们真的会产出的那几样（标题 / 加粗 / 斜体 / 列表 / 引用 /
 *    代码 / 段落），避免把用户正文里的数学符号当成 Markdown 语法吃掉；
 * 3. 行内 `[n]` **原样保留**（引文标记不是 Markdown 链接）。
 */

import { marked } from 'marked'
import TurndownService from 'turndown'

/** Markdown → 编辑器用的 HTML。空正文给一个空段落，编辑器才不会"没地方落光标"。 */
export function mdToHtml(md) {
  const text = String(md == null ? '' : md)
  if (!text.trim()) return '<p></p>'
  const html = marked.parse(text, { gfm: true, breaks: false, async: false })
  return String(html || '<p></p>')
}

const turndown = new TurndownService({
  headingStyle: 'atx',
  bulletListMarker: '-',
  codeBlockStyle: 'fenced',
  emDelimiter: '*',
})

// `[n]` 这类文本不能被转义成 `\[n\]`（引文标记要逐字保留）
turndown.escape = (value) => String(value)

// 带 `style` 的 span（逐处字号）**原样保留**成内联 HTML ——
// 这正是"不同字号能存住"的关键：turndown 默认会把它拆成纯文本，样式就丢了。
turndown.addRule('keepInlineStyle', {
  filter: (node) =>
    node.nodeName === 'SPAN' && Boolean(node.getAttribute && node.getAttribute('style')),
  replacement: (content, node) => `<span style="${node.getAttribute('style')}">${content}</span>`,
})

// 空段落（TipTap 的空行）转成空行，而不是 `<p></p>` 残留
turndown.addRule('emptyParagraph', {
  filter: (node) =>
    node.nodeName === 'P' && !node.textContent.trim() && !node.querySelector('img'),
  replacement: () => '\n',
})

/** 编辑器 HTML → Markdown（存库用）。 */
export function htmlToMd(html) {
  const raw = String(html == null ? '' : html)
  if (!raw.trim()) return ''
  let md = turndown.turndown(raw)
  // 收尾：多余空行压成最多一行；首尾空白去掉
  md = md.replace(/\n{3,}/g, '\n\n').replace(/[ \t]+$/gm, '').trim()
  return md
}

/** 编辑器的空态判据（全空白 = 空稿）。 */
export function isBlankHtml(html) {
  return !String(html || '').replace(/<[^>]*>/g, '').trim()
}
