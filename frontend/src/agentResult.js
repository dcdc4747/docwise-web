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

// ============================================================ 矩阵（build_matrix）

/**
 * 矩阵列名 → `build_matrix` 行里的键。
 *
 * 后端（`backend/app/agent/packs/matrix.py`）给的是**扁平行**
 * （`{file, research_question, method, conclusion, terms, quote}`），
 * 而 `MatrixTable` 要的是 `{filename, cells: {列名: 值}}`——这里做一层搬运，
 * 两种形状都认（前端口径的 `cells` 优先）。
 */
const MATRIX_CELL_KEYS = {
  研究问题: 'research_question',
  方法: 'method',
  结论: 'conclusion',
  术语: 'terms',
  可引用句: 'quote',
}

/** 跳过空白（缩进、逗号后的空格都算）。 */
function skipSpace(text, at) {
  let i = at
  while (i < text.length && /\s/.test(text[i])) i += 1
  return i
}

/**
 * 引号串的结束位置（`readQuoted` 只给内容、不给位置，这里补一个扫描）。
 * 没闭合返回 -1。
 */
function stringEnd(text, quoteAt) {
  const quote = text[quoteAt]
  let i = quoteAt + 1
  while (i < text.length) {
    if (text[i] === '\\') {
      i += 2
      continue
    }
    if (text[i] === quote) return i + 1
    i += 1
  }
  return -1
}

/** `None` / `True` / `False` 三个 Python 字面量。 */
const PY_LITERALS = [
  ['None', null],
  ['True', true],
  ['False', false],
]

/** 数字（int / float / 科学计数法）。 */
const PY_NUMBER = /^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?/

/**
 * 从 `at` 起读一个 Python repr 值，连同它的结束位置。
 *
 * 只认 `build_matrix` 真会出现的形状：字符串 / `None` / `True` / `False` /
 * 数字 / 列表 / 字典。**读不完整（被截断）或超出这些形状一律返回 `null`**——
 * 上层据此宁可不显示，也不显示半张表。
 *
 * @param {string} text
 * @param {number} at
 * @returns {{value: unknown, next: number} | null}
 */
function valueAt(text, at) {
  const i = skipSpace(text, at)
  if (i >= text.length) return null
  const ch = text[i]

  if (ch === "'" || ch === '"') {
    const end = stringEnd(text, i)
    if (end < 0) return null
    const value = readQuoted(text, i)
    return value == null ? null : { value, next: end }
  }
  if (ch === '[') return listAt(text, i)
  if (ch === '{') return dictAt(text, i)

  for (const [name, value] of PY_LITERALS) {
    if (!text.startsWith(name, i)) continue
    const after = text[i + name.length]
    if (after === undefined || !/[\w]/.test(after)) return { value, next: i + name.length }
  }

  const number = PY_NUMBER.exec(text.slice(i))
  if (number) return { value: Number(number[0]), next: i + number[0].length }

  return null
}

/**
 * `[...]` 列表（允许尾逗号与换行）。
 * 没闭合 / 有一项读不出来 → `null`（**不返回"读到哪算哪"的半截数组**）。
 *
 * @param {string} text
 * @param {number} openAt
 * @returns {{value: unknown[], next: number} | null}
 */
function listAt(text, openAt) {
  const out = []
  let i = openAt + 1
  for (;;) {
    i = skipSpace(text, i)
    if (i >= text.length) return null
    if (text[i] === ']') return { value: out, next: i + 1 }
    const item = valueAt(text, i)
    if (!item) return null
    out.push(item.value)
    i = skipSpace(text, item.next)
    if (text[i] === ',') {
      i += 1
      continue
    }
    if (text[i] === ']') return { value: out, next: i + 1 }
    return null
  }
}

/**
 * `{...}` 字典（键必须是字符串，值照 `valueAt` 的认法）。
 * 没闭合 / 键不是字符串 / 结构不对 → `null`。
 *
 * @param {string} text
 * @param {number} openAt
 * @returns {{value: Record<string, unknown>, next: number} | null}
 */
function dictAt(text, openAt) {
  const out = {}
  let i = openAt + 1
  for (;;) {
    i = skipSpace(text, i)
    if (i >= text.length) return null
    if (text[i] === '}') return { value: out, next: i + 1 }

    const key = valueAt(text, i)
    if (!key || typeof key.value !== 'string') return null
    i = skipSpace(text, key.next)
    if (text[i] !== ':') return null

    const value = valueAt(text, i + 1)
    if (!value) return null
    out[key.value] = value.value

    i = skipSpace(text, value.next)
    if (text[i] === ',') {
      i += 1
      continue
    }
    if (text[i] === '}') return { value: out, next: i + 1 }
    return null
  }
}

/** 一格的值 → `MatrixTable` 认的形状（字符串 / 数字 / 布尔 / 字符串数组）。 */
function cellValue(raw) {
  if (raw == null) return null
  if (typeof raw === 'string' || typeof raw === 'number' || typeof raw === 'boolean') return raw
  if (Array.isArray(raw)) {
    return raw
      .map((item) => {
        if (item == null) return ''
        if (typeof item === 'string' || typeof item === 'number') return String(item)
        // 术语偶尔是 `{term, cn}`：取术语本身，不把整个对象印成 [object Object]
        if (typeof item === 'object' && typeof item.term === 'string') return item.term
        return ''
      })
      .filter((item) => item.trim() !== '')
  }
  // 导读字段的旧形状 `{text, source_block_ids}`：只取文本
  if (typeof raw === 'object' && typeof raw.text === 'string') return raw.text
  return null
}

/**
 * 一行 → `{filename, cells}`。
 *
 * 认不出形状（既没有可显示的文件名、也没有任何一格内容）返回 `null`：
 * 与其渲染一行空白的「—」，不如整张表都不显示。
 *
 * @param {unknown} raw
 * @param {string[]} columns
 */
function matrixRow(raw, columns) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const filename =
    typeof raw.filename === 'string'
      ? raw.filename
      : typeof raw.file === 'string'
        ? raw.file
        : ''

  const cells = {}
  if (raw.cells && typeof raw.cells === 'object' && !Array.isArray(raw.cells)) {
    for (const [column, value] of Object.entries(raw.cells)) {
      cells[column] = cellValue(value)
    }
  } else {
    for (const column of columns) {
      const key = MATRIX_CELL_KEYS[column] || column
      if (Object.prototype.hasOwnProperty.call(raw, key)) cells[column] = cellValue(raw[key])
      else if (Object.prototype.hasOwnProperty.call(raw, column)) cells[column] = cellValue(raw[column])
    }
  }

  if (!filename && !Object.keys(cells).length) return null
  return { filename, cells }
}

/**
 * 把 `build_matrix` 的 excerpt 解析成 `MatrixTable` 要的 `data`。
 *
 * excerpt 是后端 `str(part.content)[:300/400]` 的 **Python repr**（单引号、
 * `None`、还可能被截断），所以这里**纯字符扫描**：不 `eval`、不 `JSON.parse`、
 * 也不对读不出的内容做猜测。
 *
 * 边界（宁可不显示，也不显示半张错表）：
 * - **截断**（顶层括号/引号没闭合、列表里有一项读不出来）→ `null`；
 * - 没有 `rows`、或某一行认不出形状 → `null`；
 * - `rows: []` 是**解析成功**但空表（`AgentChat` 自己决定不渲染空表）；
 * - `topic: None` 当空；`columns` 里的「文献」剔掉（表格第一列固定是它）。
 *
 * @param {string} excerpt
 * @returns {{topic: string, columns: string[], rows: {filename: string, cells: Record<string, unknown>}[], missing: unknown[]} | null}
 */
export function parseMatrix(excerpt) {
  const text = typeof excerpt === 'string' ? excerpt : ''
  const start = text.indexOf('{')
  if (start < 0) return null

  const parsed = dictAt(text, start)
  // 半截 / 不是能读的 repr：整段作废
  if (!parsed) return null

  const raw = parsed.value
  // 没有 rows 就不是矩阵结果（别拿别的工具结果凑一张表）
  if (!Array.isArray(raw.rows)) return null

  const topic = typeof raw.topic === 'string' ? raw.topic.trim() : ''

  let columns = []
  if (raw.columns != null) {
    if (!Array.isArray(raw.columns)) return null
    columns = raw.columns
      .filter((column) => typeof column === 'string' && column.trim() !== '')
      .map((column) => column.trim())
      // `MatrixTable` 第一列固定「文献」；后端 columns 里也有这一条，
      // 不剔掉表头就会出现两个「文献」
      .filter((column) => column !== '文献')
  }

  const rows = []
  for (const rawRow of raw.rows) {
    const row = matrixRow(rawRow, columns)
    if (!row) return null
    rows.push(row)
  }

  return {
    topic,
    columns,
    rows,
    missing: Array.isArray(raw.missing) ? raw.missing : [],
  }
}

/**
 * 把一个工具结果压成卡片要显示的内容。
 *
 * 目前只认识 `run_check`（`kind: 'check'`）；`matrix` 只记类型、不解析内容
 * （矩阵由 `parseMatrix` + `MatrixTable` 单独渲染）；
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
