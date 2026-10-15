/**
 * 起草页的文本层 —— **纯函数**（无状态、不发请求、不碰 DOM）。
 *
 * 为什么单独一个文件：这几件事都要被单测钉住，而它们跟请求、跟组件生命周期都没关系。
 * ⚠️ **这一层一个字都不代写**：所有函数只做"把用户已经写下的字切开/排好/数一数"，
 * 没有任何生成、补全、改写（形态 §3.2：正文一个字都不替用户生成）。
 *
 * 三件事：
 * ① `outlineOf()` —— 把正文里的 `#` 标题行读成提纲（提纲跟着正文走，不另存一份）；
 * ② `previewBlocks()` / `citeSegments()` —— 把正文切成可直接渲染的块与片段，
 *    并把 `[n]` 单独成段，**这样预览里才能点 [n] 回原文**（textarea 里点不了）；
 * ③ `insertMarker()` / `uploadTemplateId()` —— 插入 `[n]` 标记、从模板文件名取标识。
 */

/** `[n]` 引文标记（1–3 位数字）。**只认半角方括号**——全角「［1］」不当标记（那多半是用户自己写的字）。 */
const CITE_RE = /\[(\d{1,3})\]/g

/** 标题行：`# 标题`（1–6 级，`#` 与文字之间至少一个空格）。 */
const HEADING_RE = /^(#{1,6})\s+(.+?)\s*$/

/**
 * 把正文里的标题行读成提纲。
 *
 * ⚠️ **只读不判断**：`## ` 开头就是二级，不做"这看起来像不像标题"的猜测——
 * 提纲是用户自己写下的结构，不是我们猜出来的结构。
 *
 * @param {string} bodyMd 正文（markdown 源码）
 * @returns {{level: number, text: string, line: number, offset: number, key: string}[]}
 *          `offset` 是这一行在正文里的字符下标（点提纲要能把光标放到那里）。
 */
export function outlineOf(bodyMd) {
  const text = String(bodyMd ?? '')
  const lines = text.split('\n')
  const items = []
  let offset = 0
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]
    const match = HEADING_RE.exec(line)
    if (match) {
      items.push({
        level: match[1].length,
        text: match[2],
        line: i,
        offset,
        key: `${offset}`,
      })
    }
    offset += line.length + 1 // +1 = 换行符
  }
  return items
}

/**
 * 把一段文字按 `[n]` 切成片段。
 *
 * @returns {{kind: 'text'|'cite', text: string, order?: number}[]}
 *          `kind: 'cite'` 的片段是**标记本身**（`text` 是原文 `[1]`，`order` 是数字 1）。
 */
export function citeSegments(text) {
  const raw = String(text ?? '')
  const segments = []
  let last = 0
  CITE_RE.lastIndex = 0
  let match = CITE_RE.exec(raw)
  while (match) {
    if (match.index > last) {
      segments.push({ kind: 'text', text: raw.slice(last, match.index) })
    }
    segments.push({ kind: 'cite', text: match[0], order: Number(match[1]) })
    last = match.index + match[0].length
    match = CITE_RE.exec(raw)
  }
  if (last < raw.length) segments.push({ kind: 'text', text: raw.slice(last) })
  return segments
}

/**
 * 把正文切成可渲染的块：标题行各自成块，其余按**空行**分段。
 *
 * ⚠️ 这是**最小渲染**（标题 + 段落 + `[n]`），不是完整 markdown——
 * 界面上的名字叫「预览」，别让它看起来像"我们已经支持全部 markdown 语法"。
 *
 * @returns {{kind: 'heading'|'paragraph', level?: number, segments: object[]}[]}
 */
export function previewBlocks(bodyMd) {
  const text = String(bodyMd ?? '')
  if (!text.trim()) return []
  const lines = text.split('\n')
  const blocks = []
  let buffer = []

  const flush = () => {
    if (!buffer.length) return
    const joined = buffer.join('\n')
    blocks.push({ kind: 'paragraph', segments: citeSegments(joined) })
    buffer = []
  }

  for (const line of lines) {
    const match = HEADING_RE.exec(line)
    if (match) {
      flush()
      blocks.push({
        kind: 'heading',
        level: match[1].length,
        segments: citeSegments(match[2]),
      })
      continue
    }
    if (!line.trim()) {
      flush()
      continue
    }
    buffer.push(line)
  }
  flush()
  return blocks
}

/**
 * 在 `offset` 处插入 `[order]` 标记。
 *
 * @returns {{text: string, caret: number}} 新正文 + **插入之后**光标该落在哪
 *          （调用方拿它设 `setSelectionRange`，不然插完光标会跳到末尾）。
 */
export function insertMarker(text, offset, order) {
  const raw = String(text ?? '')
  const n = Number(offset)
  const pos = Number.isFinite(n) ? Math.min(Math.max(0, Math.trunc(n)), raw.length) : raw.length
  const marker = `[${Number(order) || 0}]`
  return { text: raw.slice(0, pos) + marker + raw.slice(pos), caret: pos + marker.length }
}

/** template_id 的列宽上限（契约 §2.7：`str(64)`）——超了要在**前端**先截，别让后端 422。 */
export const TEMPLATE_ID_MAX = 64

/**
 * 从上传的模板文件名取 `template_id`（`upload:<文件名>`，截到 64 字符）。
 *
 * ⚠️ 只取**文件名**当标识：模板文件本身本期不入库（契约 §2.7 只存标识），
 * 所以界面上必须如实说明这一点，不许让用户以为模板文件被存下来了。
 */
export function uploadTemplateId(filename) {
  const base = String(filename ?? '').trim() || '未命名模板'
  const id = `upload:${base}`
  return id.length > TEMPLATE_ID_MAX ? id.slice(0, TEMPLATE_ID_MAX) : id
}

/** 能读进来的模板格式（纯文本）。`.docx` 是二进制包，前端没有解析器——如实拒绝，不假装读到了。 */
export const TEXT_TEMPLATE_RE = /\.(md|markdown|txt)$/i
