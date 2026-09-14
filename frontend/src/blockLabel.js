/**
 * 块编号 → 人话位置，以及"按文本找块"的纯函数。
 *
 * 为什么单独一个模块：形态约定「出处永远说人话」（第 X 页 · 第 Y 段），
 * 而块编号 `p1_b3` 对用户是乱码。这段逻辑要能被单测锁住，所以抽成纯函数。
 */

/** 形如 `p<页序>_b<全文档块序>`；`b` 是**全文档全局序号**，不是页内段号。 */
const BLOCK_RE = /^p(\d+)_b(\d+)$/

export function parseBlockId(blockId) {
  const matched = BLOCK_RE.exec(String(blockId || ''))
  if (!matched) return null
  return { page: Number(matched[1]), index: Number(matched[2]) }
}

/**
 * 块编号 → 「第 X 页 · 第 Y 段」。
 * - 页号 = 块编号里的页序 + 1（人从 1 数起）；
 * - **段号必须按页内重算**：`b` 是全文档序号（实测任务 2 共 92 块 / 3 页，最后一块叫 `p2_b91`），
 *   直接把 b 当段号会显示成"第 92 段"。
 * - 解析不出、或该块不在本任务的块列表里 → 返回空串，由调用方显示"位置待定"，
 *   **绝不裸露块编号**（宁可不给，也不假装）。
 */
export function blockLabel(blockId, allBlockIds) {
  const parsed = parseBlockId(blockId)
  if (!parsed) return ''
  const samePage = (allBlockIds || []).filter((id) => {
    const item = parseBlockId(id)
    return item && item.page === parsed.page
  })
  const position = samePage.indexOf(blockId)
  if (position < 0) return ''
  return `第 ${parsed.page + 1} 页 · 第 ${position + 1} 段`
}

/**
 * 文本归一化：**必须做 NFKC**。
 * 实测译稿文字层里混着 CJK 兼容汉字（U+F900–FAFF，长得一样、码位不同）：
 * 含兼容字的片段 NFKC 归一化前后，search_for 命中数从 1 掉到 0——不做归一化就是静默失配。
 */
export function normalizeText(value) {
  return String(value ?? '')
    .normalize('NFKC')
    .toLowerCase()
}

/** 在任务的块里按文本找块（术语定位用；术语表目前没有出处字段）。找不到就返回 null，由调用方直说。 */
export function findBlockByText(needle, blocks) {
  const target = normalizeText(needle).trim()
  if (!target) return null
  for (const block of blocks || []) {
    const text = normalizeText(block?.text)
    const translated = normalizeText(block?.translated)
    if (text.includes(target) || translated.includes(target)) return block || null
  }
  return null
}

/**
 * 把块列表排成"段落精读"的行：块行 + 跨页分隔行（段号在页内重算、每翻一页插一条分隔）。
 *
 * 为什么要有它：左栏如果只用 iframe 看 PDF，浏览器自带阅读器是个黑盒——拿不到 DOM，
 * 「点出处 → 滚到那一段 → 高亮」就物理上做不到。段落精读用的是我们自己的 DOM，锚点才成立。
 *
 * @returns {{kind:'page',page:number,label:string}|{kind:'block',block:object,page:number|null,index:number|null,label:string}[]
 */
export function buildParagraphRows(blocks) {
  const rows = []
  let lastPage = null
  for (const block of blocks || []) {
    const parsed = parseBlockId(block?.block_id)
    const page = parsed ? parsed.page : null
    if (page !== null && page !== lastPage) {
      rows.push({ kind: 'page', page, label: `第 ${page + 1} 页` })
      lastPage = page
    }
    rows.push({
      kind: 'block',
      block,
      page,
      label: '', // 段号要按页内重算，整页块都齐了才知道，渲染前用 appendBlockNumbers 补
    })
  }
  return appendBlockNumbers(rows)
}

/** 给每一行补上「段 N」（页内序号，从 1 数起）；页分隔行原样返回，别动它的标签。 */
export function appendBlockNumbers(rows) {
  const counters = new Map()
  return (rows || []).map((row) => {
    if (row.kind !== 'block') return row
    if (row.page === null) return { ...row, index: null, label: '' }
    const next = (counters.get(row.page) || 0) + 1
    counters.set(row.page, next)
    return { ...row, index: next, label: `段 ${next}` }
  })
}
