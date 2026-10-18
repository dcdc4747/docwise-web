/**
 * 结构化工具结果的「人话」摘要（纯字符串解析）。
 *
 * 后端发来的 `excerpt` 是 Python `str(dict)` 的前 300/400 个字符
 * （见 `backend/app/agent/runtime.py`：`str(part.content)[:400]`），
 * **不是 JSON**——单引号、里层还可能被截断。所以这里只做字符扫描：
 * **不 eval、不 JSON.parse**，也**不对解析不出的内容做猜测**。
 * 抽不到就返回空数组，界面保持原样（不认识的结果不塞卡片）。
 */

/** 卡片最多显示的 chip 行数（多了会把过程区又撑乱）。 */
const MAX_CHIPS = 3

const CHECK_TOOL = /run[_ -]?check/i
const MATRIX_TOOL = /matrix/i

/** Python repr 里常见的一字符转义；其余转义原样保留字符本身。 */
const ESCAPES = {
  0: '\0',
  n: '\n',
  r: '\r',
  t: '\t',
  "'": "'",
  '"': '"',
  '\\': '\\',
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * `'key':` / `"key":` 之后的值起点（跳过冒号与空白）；找不到返回 -1。
 *
 * @param {string} text
 * @param {string} key
 * @param {number} [from]
 */
function valueStart(text, key, from = 0) {
  const re = new RegExp(`['"]${escapeRegExp(key)}['"]\\s*:\\s*`, 'g')
  re.lastIndex = from
  const hit = re.exec(text)
  return hit ? hit.index + hit[0].length : -1
}

/**
 * 从引号位置读一个字符串值；**引号没闭合（被截断）返回 null**。
 *
 * @param {string} text
 * @param {number} quoteAt
 */
function readQuoted(text, quoteAt) {
  const quote = text[quoteAt]
  if (quote !== "'" && quote !== '"') return null
  let out = ''
  let i = quoteAt + 1
  while (i < text.length) {
    const ch = text[i]
    if (ch === '\\') {
      const next = text[i + 1]
      if (next === undefined) return null
      if (next === 'x') {
        const hex = text.slice(i + 2, i + 4)
        if (!/^[0-9a-fA-F]{2}$/.test(hex)) return null
        out += String.fromCharCode(parseInt(hex, 16))
        i += 4
      } else if (next === 'u') {
        const hex = text.slice(i + 2, i + 6)
        if (!/^[0-9a-fA-F]{4}$/.test(hex)) return null
        out += String.fromCharCode(parseInt(hex, 16))
        i += 6
      } else {
        out += Object.prototype.hasOwnProperty.call(ESCAPES, next) ? ESCAPES[next] : next
        i += 2
      }
      continue
    }
    if (ch === quote) return out
    out += ch
    i += 1
  }
  return null
}

/**
 * 取 `key` 后面那个 `{...}` / `[...]` 的原文。
 *
 * 截断（括号没闭合）时返回**到末尾为止**的片段并标 `closed: false`：
 * 里面已经完整出现的字段仍然可以读，但不假装它完整。
 *
 * @param {string} text
 * @param {string} key
 * @param {'{'|'['} open
 */
function containerAfter(text, key, open) {
  const start = valueStart(text, key)
  if (start < 0 || text[start] !== open) return null
  const close = open === '{' ? '}' : ']'
  let depth = 0
  for (let i = start; i < text.length; i += 1) {
    const ch = text[i]
    if (ch === "'" || ch === '"') {
      // 跳过整个字符串，避免把字符串里的括号当成结构
      const quote = ch
      i += 1
      while (i < text.length && text[i] !== quote) {
        if (text[i] === '\\') i += 1
        i += 1
      }
      continue
    }
    if (ch === open) depth += 1
    else if (ch === close) {
      depth -= 1
      if (depth === 0) return { text: text.slice(start, i + 1), closed: true }
    }
  }
  return { text: text.slice(start), closed: false }
}

/**
 * 读 `key` 的字符串值；不是字符串 / 被截断都返回 null。
 *
 * @param {string} text
 * @param {string} key
 * @param {number} [from]
 */
function stringValue(text, key, from = 0) {
  const start = valueStart(text, key, from)
  if (start < 0) return null
  return readQuoted(text, start)
}

/** `term_rate` 里的 `note`（没有就 null；不会把顶层 `note` 误当术语说明）。 */
function termRateNote(text) {
  const rate = containerAfter(text, 'term_rate', '{')
  if (!rate) return null
  const note = stringValue(rate.text, 'note')
  return note && note.trim() ? note.trim() : null
}

/** 顶层 `citation_gaps_note` 的值（没有就 null）。 */
function citationGapsNote(text) {
  const note = stringValue(text, 'citation_gaps_note')
  return note && note.trim() ? note.trim() : null
}

/**
 * `findings` 数组里数 `{'kind'`（与任务约定一致）。
 *
 * 数组被截断时只数**已经露出来**的那几条，不估总数。
 *
 * @param {string} text
 */
function findingsLine(text) {
  const array = containerAfter(text, 'findings', '[')
  if (!array) return null
  const count = (array.text.match(/\{\s*['"]kind['"]\s*:/g) || []).length
  return `发现 ${count} 处`
}

/** 去空、去重、最多 `MAX_CHIPS` 条（顺序保留）。 */
function uniqueChips(items) {
  const out = []
  const seen = new Set()
  for (const item of items) {
    const text = String(item == null ? '' : item).trim()
    if (!text || seen.has(text)) continue
    seen.add(text)
    out.push(text)
    if (out.length >= MAX_CHIPS) break
  }
  return out
}

/**
 * 把一个工具结果压成卡片要显示的内容。
 *
 * 目前只认识 `run_check`（`kind: 'check'`）；`matrix` 只记类型、不解析内容；
 * 其余工具一律 `unknown` 且**不带任何内容**（界面保持原样）。
 *
 * @param {string} name 工具名
 * @param {string} excerpt 后端给的 Python dict 字符串片段（可能被截断）
 * @returns {{kind: 'check'|'matrix'|'unknown', lines: string[], chips: string[]}}
 */
export function summarizeToolResult(name, excerpt) {
  const tool = String(name == null ? '' : name)
  const text = typeof excerpt === 'string' ? excerpt : ''

  if (CHECK_TOOL.test(tool)) {
    const lines = []
    const findings = findingsLine(text)
    if (findings) lines.push(findings)
    return {
      kind: 'check',
      lines,
      chips: uniqueChips([termRateNote(text), citationGapsNote(text)]),
    }
  }

  if (MATRIX_TOOL.test(tool)) return { kind: 'matrix', lines: [], chips: [] }

  return { kind: 'unknown', lines: [], chips: [] }
}
