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
 * 块编号 → 「第 X 页」。
 *
 * **出处只说页码、不说第几段**（2026-09-17 定的口径）：段号靠 PDF 版面切分算出来，
 * 实测在没见过的期刊上只有五六成准（见 `temp/seg-audit/审查结论_汇总.md`），
 * 而不准的段号比没有段号更糟——用户会拿它去数，数不上就整条出处都不信了。
 * 出处真正让人信的是**点下去那几句被高亮**（那是按文字匹配算的，不依赖分段）。
 *
 * 解析不出页码 → 返回空串，由调用方显示「位置待定」（**绝不裸露块编号**）。
 */
export function pageLabel(blockId) {
  const parsed = parseBlockId(blockId)
  return parsed ? `第 ${parsed.page + 1} 页` : ''
}

/**
 * 出处的完整标签：「第 X 页 ·「这一句的开头…」」。
 *
 * 两条都是硬要求：
 * ① **块必须真的在这个任务的块列表里**——模型偶尔会编出不存在的块编号，
 *    只按编号前缀给个页码，等于把编出来的位置当真显示（宁可写「位置待定」，也不假装）；
 * ② 缀上**这一句的开头**：一页里往往有好几个出处，只写页码的话几个标签长得一模一样，
 *    用户分不清哪个是哪个——缀上开头，没点之前就知道是哪几句。
 *
 * @param {string} blockId 用哪一块的页码
 * @param {Array} blocks 本任务的块列表（用来校验"这块真的存在" + 取开头）
 * @param {{chars?:number,text?:string}} [opts] `text` 可以传"合成后的那一整句"（见 mergeSourceRuns）
 */
export function sourceLabel(blockId, blocks, { chars = 12, text: textOverride } = {}) {
  const parsed = parseBlockId(blockId)
  if (!parsed) return ''
  const block = (blocks || []).find((item) => item?.block_id === blockId)
  if (!block) return ''
  const page = `第 ${parsed.page + 1} 页`
  const text = String(textOverride ?? block.text ?? '')
    .replace(/\s+/g, ' ')
    .trim()
  if (!text) return page
  const head = text.slice(0, chars).trim()
  return `${page} ·「${head}${text.length > chars ? '…' : ''}」`
}

/** 句子收尾的标点（中英文都算）。行末不是这些 → 这句话还没写完。 */
const SENTENCE_END = /[。！？…；：!?;:]["'”’』」）】》)\]]*$/

/** 这段文字是不是说到句子结尾了。 */
export function endsSentence(text) {
  return SENTENCE_END.test(String(text || '').trim())
}

/** 拼接两段文字：中文直接接上；英文单词被断开时补一个空格（与引擎侧 `_join_lines` 同规则）。 */
function joinText(head, tail) {
  if (!head) return tail
  if (!tail) return head
  const prev = head.slice(-1)
  const next = tail.slice(0, 1)
  if (/[A-Za-z0-9]/.test(prev) && /[A-Za-z0-9]/.test(next)) return `${head} ${tail}`
  return head + tail
}

/**
 * **把"同一句被换行切断"的相邻块合成一个出处。**
 *
 * 为什么需要：中文文献的块是**按行**切的（一页 39 个块 = 39 行），模型引用时会把
 * "上一行 + 下一行"当成两个块报回来。界面如果照单全收，就会显示成两个出处按钮——
 * 用户看到的是"同一句话被拆成两个出处"，而点下去两条各自只高亮半句。
 *
 * 规则（**只合并真的一直连下去的**）：
 * ① 两块在块列表里**紧挨着**、且在**同一页**；
 * ② 前一块**没有以句末标点收尾**（换了行但话没说完）。
 * 两条缺一不可——模型引两个不相邻的块，本来就该是两个出处。
 *
 * @returns {{id:string, ids:string[], text:string}[]} 每个 run 的 `id` 取第一块（页码以它为准）
 */
export function mergeSourceRuns(ids, blocks) {
  const list = blocks || []
  const position = new Map(list.map((block, i) => [block?.block_id, i]))
  const textOf = (id) => String(list[position.get(id)]?.text || '')
  const pageOf = (id) => parseBlockId(id)?.page

  const runs = []
  for (const id of [...new Set(ids || [])]) {
    // 对不上号的块编号**照旧保留成一条**：界面上写「位置待定」、点了说实话，
    // 总比"看起来模型没给出处"要诚实（模型给了、是我们对不上，这件事得让用户看见）
    if (!position.has(id)) {
      runs.push({ id, ids: [id], text: '' })
      continue
    }
    const last = runs[runs.length - 1]
    const prevId = last ? last.ids[last.ids.length - 1] : null
    const adjacent = prevId !== null && position.get(id) === position.get(prevId) + 1
    const samePage = prevId !== null && pageOf(prevId) === pageOf(id)
    const unfinished = prevId !== null && !endsSentence(textOf(prevId))
    if (adjacent && samePage && unfinished) {
      last.ids.push(id)
      last.text = joinText(last.text, textOf(id))
      continue
    }
    runs.push({ id, ids: [id], text: textOf(id) })
  }
  return runs
}

/**
 * 块编号 → 「第 X 页 · 第 Y 段」。
 *
 * ⚠️ **界面上已经不用它了**（见 `pageLabel` 的说明：段号不准，改说人话只说页码）。
 * 留着是因为它锁住了那条真教训：`b` 是**全文档全局序号**，段号必须按页内重算——
 * 实测任务 2 共 92 块 / 3 页，最后一块叫 `p2_b91`，直接把 b 当段号会显示成"第 92 段"。
 * 将来真把段落切分做到可信了（`temp/seg-audit/` 里有评测台），再把它接回来。
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
