/**
 * 校对检查报告的导出层 —— **纯函数**（无状态、不发请求、不碰 DOM）。
 *
 * 为什么单独一个文件：序列化最容易"看起来对"——少导一段、CSV 里的引号没转义、
 * 草稿名里的 `/` 被带进文件名，这几种都不会崩、只会悄悄错，所以单独一层 + 单测钉住。
 *
 * 三条口径（E11 卡）：
 * ① ⭐ **导出的内容和界面所见一致**：判语言 / 判制式（判不出就写「未能识别」）、
 *    每条 finding 的原句 / 原因 / 判据 / 建议引的那一条、**筛子账那几句如实说明**。
 *    「为什么只报这么少」正是我们与同类工具的差别，**不许只导结论**。
 * ② **不报百分比**：汇总只写「报出 N 处，另有 M 处判不出」（卡④⑧：报百分比要带前提，
 *    不带前提的百分比会直接改变结论）。
 * ③ **导出不改稿**：这一层只把界面上那份报告抄出来，不动正文、不调接口、不写库。
 */

/** 支持的导出格式（导出按钮的 `data-format` 与文件扩展名共用这一份取值）。 */
export const EXPORT_FORMATS = ['md', 'csv']

/** `severity` 只有两档（后端 `engine.py` 的口径），说人话再说一遍。 */
const LEVELS = { report: '待处理', unknown: '判不出' }

/** 分组里没有的条目（引擎加了新的 `kind` 而后端分组还没跟上）——**照导，不许漏条目**。 */
const FALLBACK_KIND = '其他'

/** 文件名里草稿名最多留多少个字（再长就把时间戳挤出可视区）。 */
const TITLE_MAX = 40

/**
 * 有没有"可以导出的报告"。
 *
 * ⚠️ **判的是"报告在不在"，不是"有没有查出问题"**：一份「报出 0 处」的报告
 * 也是有效结论（它证明这次检查跑过了），照样能导出；**没跑过检查才没有按钮**。
 */
export function canExport(report) {
  return Boolean(report && typeof report === 'object')
}

/** 把任意值收成一行人话（换行 / 连续空白折成一个空格——CSV 与 Markdown 都不吃多行原句）。 */
function clean(value) {
  return String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim()
}

function pad(number) {
  return String(number).padStart(2, '0')
}

function asDate(value) {
  return value instanceof Date ? value : new Date(value)
}

/** 报告里那句"什么时候导的"（本地时间，用户在哪儿看到的就是哪儿的钟）。 */
export function formatStamp(date = new Date()) {
  const d = asDate(date)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 文件名里的时间戳（`20261016-1405`）。 */
export function fileStamp(date = new Date()) {
  const d = asDate(date)
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`
}

/**
 * 导出文件名：`校对检查-<草稿名>-<时间戳>.<ext>`。
 *
 * ⚠️ **草稿名是用户自己起的**，里面可能有 `/` `\` `:` 这类字符——直接拼进
 * `download` 属性会被浏览器当路径切掉，所以这里先把它们换成 `-`，再截到 40 字。
 */
export function exportFilename(title, format = 'md', date = new Date()) {
  const safe =
    clean(title)
      .replace(/[\\/:*?"<>|\u0000-\u001f]/g, '-')
      .slice(0, TITLE_MAX) || '未命名草稿'
  const ext = EXPORT_FORMATS.includes(format) ? format : 'md'
  return `校对检查-${safe}-${fileStamp(date)}.${ext}`
}

/** 各格式的 MIME（Blob 的类型，Excel 那边靠它认 CSV）。 */
export function exportMimeType(format) {
  return format === 'csv' ? 'text/csv;charset=utf-8' : 'text/markdown;charset=utf-8'
}

/** 级别说人话（引擎给了第三档也不吞掉，如实写出来）。 */
function levelOf(item) {
  return LEVELS[item?.severity] || clean(item?.severity) || '未标级别'
}

/**
 * 把界面上的分组摊平成"一行一条"。
 *
 * 顺序 = 界面顺序（`checkGroups` 的 `KIND_ORDER`），**分组里没有的条目补在最后**——
 * 宁可多导一条"其他"，也不许因为分组没跟上就把报告导少。
 */
function flattenRows({ report, groups }) {
  const rows = []
  const seen = new Set()
  for (const group of Array.isArray(groups) ? groups : []) {
    for (const item of Array.isArray(group?.items) ? group.items : []) {
      rows.push({ kind: clean(group.label) || FALLBACK_KIND, item })
      if (item?.id != null) seen.add(item.id)
    }
  }
  for (const item of Array.isArray(report?.findings) ? report.findings : []) {
    if (item?.id != null && seen.has(item.id)) continue
    rows.push({ kind: FALLBACK_KIND, item })
  }
  return rows
}

/**
 * 「建议引这一条」那一行：**出处只有一种写法**——`来源名 · 第 X 页 ·「这一句的开头…」`
 * （全站硬约定，不写第几段）。拿不到来源名就只写页码与引文，**不编一个来源出来**。
 *
 * `sourceNameOf(item)` 由调用方注入（界面上是 `suggestedSource`：素材在列表里就用它的快照，
 * 不在就如实说"素材已不在列表里"）——这一层不碰 store，所以做成参数。
 */
function suggestLine(item, sourceNameOf) {
  const suggest = item?.suggest
  if (!suggest) return ''
  const head = []
  const name = typeof sourceNameOf === 'function' ? clean(sourceNameOf(item)) : ''
  if (name) head.push(name)
  const page = clean(suggest.page)
  if (page) head.push(`第 ${page} 页`)
  const quote = clean(suggest.quote)
  // ⚠️ 分隔符与 `CiteChip` 一字不差：`来源名 · 第 X 页 ·「原句开头…」`——
  // 第二个 `·` 后面**没有空格**。导出的字串要能在屏幕上对得出来，别自成一套写法。
  const prefix = head.join(' · ')
  if (quote) return prefix ? `${prefix} ·「${quote}」` : `「${quote}」`
  return prefix
}

/**
 * 报告 → Markdown（**带全部条目 + 筛子账**）。
 *
 * @param {{report: object, step?: object, groups?: object[], title?: string,
 *          stamp?: string, sourceNameOf?: (item: object) => string}} options
 *        `step` 是界面上的 `checkStep`（已把 `unknown` 说成「未能识别」）；
 *        `stamp` 由调用方传（纯函数不自己取当前时间，测试才定得住）。
 * @returns {string}
 */
export function reportToMarkdown({ report, step, groups, title, stamp, sourceNameOf } = {}) {
  const draftTitle = clean(title) || '未命名草稿'
  const at = clean(stamp) || formatStamp(new Date())
  const summary = report?.summary || {}
  const reported = Number(summary.reported) || 0
  const unknown = Number(summary.unknown) || 0
  const ledger = (Array.isArray(step?.ledger) ? step.ledger : []).map(clean).filter(Boolean)
  const rows = flattenRows({ report, groups })

  const lines = []
  lines.push(`# 校对检查报告 · ${draftTitle}`)
  lines.push('')
  lines.push(`- 导出时间：${at}`)
  lines.push(`- 判语言：${clean(step?.lang) || '未能识别'}`)
  lines.push(`- 引用制式：${clean(step?.style) || '未能识别'}`)
  lines.push(`- 汇总：报出 ${reported} 处，另有 ${unknown} 处判不出`)
  lines.push('')
  lines.push('> 报告只出结论，不替你改稿：改不改由你定。')
  lines.push('')
  lines.push('## 筛子账（为什么只报这么少）')
  lines.push('')
  if (ledger.length) {
    for (const note of ledger) lines.push(`- ${note}`)
  } else {
    // 账是空的就如实说"这次没有"，**不拿一句漂亮话补位**
    lines.push('- 引擎这次没有给出筛子说明。')
  }
  lines.push('')

  if (!rows.length) {
    lines.push('## 查出的问题')
    lines.push('')
    lines.push('这份稿子没查出问题。')
    lines.push('')
    return lines.join('\n')
  }

  lines.push(`## 查出的问题（共 ${rows.length} 条）`)
  lines.push('')
  let currentKind = ''
  let index = 0
  for (const row of rows) {
    if (row.kind !== currentKind) {
      currentKind = row.kind
      lines.push(`### ${currentKind}`)
      lines.push('')
    }
    index += 1
    lines.push(`#### ${index}. ${clean(row.item?.sentence) || '（这一条没有原句）'}`)
    lines.push('')
    lines.push(`- 级别：${levelOf(row.item)}`)
    const reason = clean(row.item?.reason)
    if (reason) lines.push(`- 原因：${reason}`)
    const ruleRef = clean(row.item?.rule_ref)
    if (ruleRef) lines.push(`- 判据：${ruleRef}`)
    const suggested = suggestLine(row.item, sourceNameOf)
    if (suggested) lines.push(`- 建议引这一条：${suggested}`)
    lines.push('')
  }
  return lines.join('\n')
}

/** CSV 单元格：一律加引号，内部引号翻倍（原句里出现 `"` 或 `,` 都不会把行切坏）。 */
function csvCell(value) {
  return `"${String(value ?? '').replace(/"/g, '""')}"`
}

/**
 * 报告 → CSV（**一行一条 finding**，方便进表格 / 统计）。
 *
 * ⚠️ 筛子账是"说明文字"、不是表格数据，所以只进 Markdown——这不是漏，是 CSV 的语义：
 * 把说明混进数据行会让这份 CSV 再也算不了。界面上也照实写着这句话。
 *
 * ⚠️ **带 UTF-8 BOM**：不带的话 Excel 会把中文当本地编码，打开就是乱码。
 */
export function reportToCsv({ report, groups, sourceNameOf, bom = true } = {}) {
  const rows = flattenRows({ report, groups })
  const header = ['类型', '级别', '原句', '原因', '判据', '建议引用的出处']
  const body = rows.map((row) => [
    row.kind,
    levelOf(row.item),
    clean(row.item?.sentence),
    clean(row.item?.reason),
    clean(row.item?.rule_ref),
    suggestLine(row.item, sourceNameOf),
  ])
  const text = [header, ...body].map((cells) => cells.map(csvCell).join(',')).join('\r\n')
  return `${bom ? '\ufeff' : ''}${text}\r\n`
}

/** 按格式取文本（调用方只认一个入口，省得自己 switch）。 */
export function reportToText(format, options = {}) {
  return format === 'csv' ? reportToCsv(options) : reportToMarkdown(options)
}
