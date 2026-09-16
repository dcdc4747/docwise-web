/**
 * PDF 文字层的纯函数：条目 → 行 → 可搜索文本 → 命中位置。
 *
 * 为什么单独一个模块：pdf.js 那一半（解析 / 渲染）必须真在浏览器里跑，很难单测；
 * 但「这一段文字在 PDF 的哪几行、该高亮哪些方块」是**纯几何 + 纯字符串**，
 * 抽出来就能用单测锁住——而"能不能对上"正是这个功能最容易悄悄坏掉的地方。
 *
 * 坐标口径：所有 rect 都是**缩放系数为 1 的视口坐标**（左上角为原点，单位是 PDF 点）。
 * 显示时统一乘一个缩放系数，这样窗口一变只改系数、不用重算命中。
 */
import { normalizeText } from './blockLabel'

/**
 * PDF 文字层专用归一化：在 blockLabel 的 NFKC + 小写之上再折叠空白。
 * 必须复用 blockLabel.normalizeText —— 译稿文字层里混着 CJK 兼容汉字（U+F900–FAFF），
 * 不归一化就是静默失配（那条教训写在 blockLabel.js 里）。
 */
export function pdfNormalize(value) {
  return normalizeText(value).replace(/\s+/g, ' ').trim()
}

/** 去掉所有空白：行与行之间、条目之间到底有没有空格，两个 PDF 不一定一致。 */
export function squash(value) {
  return pdfNormalize(value).replace(/ /g, '')
}

/**
 * 文本条目 → 行。
 *
 * 同一行要同时满足两条：
 *   ① **基线差不到半个字高**（pdf.js 的条目坐标是 `[a,b,c,d,e,f]`，e 是 x、f 是基线 y）；
 *   ② **横向挨着**——离得太远就不算同一行。加这条是因为双栏排版里左右两栏可能落在
 *      同一条基线上，只按基线分会把两栏粘成"一行"，那一行的框横跨两栏、
 *      文本也会交错（实测：真实产物里同一行内部的空隙基本是 0——pdf.js 把空格并进了
 *      条目文本——仅有的两处例外是 5.9 / 11.2 倍行高，本来就是分开的两块）。
 *
 * @param {{text:string,x:number,y:number,w:number,h:number}[]} boxes 已经换算成视口坐标的条目
 * @returns {{text:string,norm:string,squash:string,rect:{x:number,y:number,w:number,h:number}}[]}
 */
export function buildLines(boxes, { columnGap = 2 } = {}) {
  const lines = []
  let current = null

  for (const box of boxes || []) {
    const text = String(box?.text ?? '')
    if (!text.trim()) continue
    const height = Number(box.h) || 10
    const sameBaseline = current && Math.abs(current.baseline - box.y) <= height * 0.5
    // 与当前行已占的横向区间比：空隙超过 columnGap 倍行高就当另起一行
    const farApart =
      sameBaseline && box.x - current.maxX > height * columnGap
    if (!sameBaseline || farApart) {
      current = { baseline: box.y, height, maxX: -Infinity, parts: [] }
      lines.push(current)
    }
    current.parts.push(box)
    current.maxX = Math.max(current.maxX, box.x + (Number(box.w) || 0))
  }

  return lines
    .map((line) => {
      const parts = [...line.parts].sort((a, b) => a.x - b.x)
      const text = parts.map((p) => p.text).join('')
      const minX = Math.min(...parts.map((p) => p.x))
      const maxX = Math.max(...parts.map((p) => p.x + (Number(p.w) || 0)))
      const top = Math.min(...parts.map((p) => p.y - (Number(p.h) || 0)))
      const bottom = Math.max(...parts.map((p) => p.y))
      const norm = pdfNormalize(text)
      return {
        text,
        norm,
        squash: norm.replace(/ /g, ''),
        rect: { x: minX, y: top, w: Math.max(1, maxX - minX), h: Math.max(1, bottom - top) },
      }
    })
    .filter((line) => line.norm.length > 0)
}

/**
 * 把一页的所有行拼成"可搜索文本"，并记住每个字符属于哪一行；
 * 同时按几何关系把行并成**段**（鼠标扫过 PDF 时亮的是"这一段"，不是一行）。
 */
export function buildPageIndex(lines, pageNumber) {
  let flat = ''
  const owners = []
  ;(lines || []).forEach((line, index) => {
    for (const ch of line.squash) {
      flat += ch
      owners.push(index)
    }
  })
  return {
    page: pageNumber,
    lines: lines || [],
    paragraphs: buildParagraphs(lines),
    flat,
    owners,
  }
}

/**
 * 把若干行合成尽量少的方块：**同一栏、上下挨着的行并成一块**。
 *
 * 为什么要合：高亮"对上的那几行"时，如果一行画一个框，看起来是一排带缝的条；
 * 合成一块才像"这一段被框住了"。行距判断用实测值：段内基线距 14.7、字高 10.5，
 * 相邻两块之间空 4.2，而换段会空 14.8 以上——阈值取 0.9 倍字高正好卡开。
 */
export function mergeLineRects(lines) {
  const out = []
  let run = null
  for (const line of lines || []) {
    const rect = line.rect
    if (
      run &&
      sameColumn(run, rect, 0.3) &&
      rect.y - (run.y + run.h) <= Math.max(run.h, rect.h) * 0.9
    ) {
      // 四个方向都要并：列尾回到列首时（下一栏从页顶开始）后一块的 y 反而更小
      const left = Math.min(run.x, rect.x)
      const top = Math.min(run.y, rect.y)
      const right = Math.max(run.x + run.w, rect.x + rect.w)
      const bottom = Math.max(run.y + run.h, rect.y + rect.h)
      run.x = left
      run.y = top
      run.w = right - left
      run.h = bottom - top
      continue
    }
    run = { ...rect }
    out.push(run)
  }
  return out
}

/**
 * 在一页里搜一段文本（都已去空白）。命中返回它覆盖的行号区间。
 */
export function findInPage(index, needleSquash) {
  if (!index || !needleSquash) return null
  const at = index.flat.indexOf(needleSquash)
  if (at < 0) return null
  const last = Math.min(at + needleSquash.length - 1, index.owners.length - 1)
  return { at, from: index.owners[at], to: index.owners[last] }
}

/**
 * 在整个文档里找一段文本，返回 **第一个** 命中的页与要高亮的方块。
 *
 * **高亮的是"真正对上的那段文字"，不扩成整段**——这一点很关键：
 * 中文文献的取字是**按行**切块的（实测第 3 页 29 个块，每块就是一行），
 * 如果命中一行就扩成整段，那点「第 18 段 / 第 19 段 / 第 20 段」会亮同一个框，
 * 看起来就是"定位不准"。改成按命中范围高亮之后，三个段各亮各的那一行。
 *
 * 分档降级：先用整段（最准），对不上再用更短的前缀（短于 16 个字符不用，
 * 免得随便一段就把高亮打到不相干的地方）；命中后**从命中位置尽量往后延伸**，
 * 能对上多少算多少——块文本和 PDF 的行断点本来就不一定一致。
 */
export function findTextInPages(indexes, needle, { minPrefix = 16 } = {}) {
  const full = squash(needle)
  if (!full) return null
  const tries = [full]
  for (const len of [40, 24, minPrefix]) {
    if (full.length > len) tries.push(full.slice(0, len))
  }
  for (const candidate of tries) {
    for (const index of indexes || []) {
      const at = index.flat.indexOf(candidate)
      if (at < 0) continue
      // 逐字符往后延伸（candidate 是 full 的前缀，所以前面已经对上了）
      let len = candidate.length
      while (len < full.length && index.flat[at + len] === full[len]) len += 1
      const from = index.owners[at]
      const to = index.owners[Math.min(at + len - 1, index.owners.length - 1)]
      const lines = index.lines.slice(from, to + 1)
      return {
        page: index.page,
        from,
        to,
        rects: mergeLineRects(lines),
        text: lines.map((line) => line.norm).join(' '),
        matchedChars: len,
        exact: len === full.length,
      }
    }
  }
  return null
}

/** 命中点的行文本（给"这段在讲什么"用：命中的那一行 + 上一行 + 下一行）。 */
export function contextAround(index, from, to, pad = 1) {
  if (!index || from === null || from === undefined) return ''
  const lines = index.lines.slice(Math.max(0, from - pad), Math.min(index.lines.length, to + pad + 1))
  return lines.map((line) => line.norm).join(' ')
}

/**
 * 行 → **段**（论文的一整段，不是一行）。
 *
 * 为什么必须合并：鼠标扫过 PDF 时"只亮一行"看着像选错了东西——用户要的是"这一段"。
 * 合并规则是纯几何的，两条同时成立才算同一段：
 *   ① **横向重叠**（两行的 x 区间交集 ≥ 较短那行的 30%）——这样双栏排版里
 *      左右栏同一高度的两行不会被粘成一段；
 *   ② **纵向相邻**（基线间距 ≤ 1.8 倍行高）——超过就是换段了。
 * 做法是并查集：先按几何关系合并，再取连通分量，所以**不依赖行的排列顺序**
 * （双栏 PDF 的文字流顺序本来就不保证是"读完左栏再读右栏"）。
 */
export function buildParagraphs(lines, { lineGap = 1.8, overlapRatio = 0.3 } = {}) {
  const list = lines || []
  const parent = list.map((_, i) => i)
  const find = (i) => {
    let root = i
    while (parent[root] !== root) root = parent[root]
    let cur = i
    while (parent[cur] !== root) {
      const next = parent[cur]
      parent[cur] = root
      cur = next
    }
    return root
  }
  const union = (a, b) => {
    const ra = find(a)
    const rb = find(b)
    if (ra !== rb) parent[rb] = ra
  }

  for (let i = 0; i < list.length; i += 1) {
    for (let j = i + 1; j < list.length; j += 1) {
      if (sameParagraph(list[i], list[j], lineGap, overlapRatio)) union(i, j)
    }
  }

  const groups = new Map()
  list.forEach((line, i) => {
    const root = find(i)
    if (!groups.has(root)) groups.set(root, [])
    groups.get(root).push(i)
  })

  const paragraphs = [...groups.values()].map((indexes) => {
    indexes.sort((a, b) => list[a].rect.y - list[b].rect.y || list[a].rect.x - list[b].rect.x)
    const rects = indexes.map((i) => list[i].rect)
    const x = Math.min(...rects.map((r) => r.x))
    const y = Math.min(...rects.map((r) => r.y))
    const right = Math.max(...rects.map((r) => r.x + r.w))
    const bottom = Math.max(...rects.map((r) => r.y + r.h))
    return {
      lines: indexes,
      rect: { x, y, w: Math.max(2, right - x), h: Math.max(2, bottom - y) },
      text: indexes.map((i) => list[i].norm).join(' '),
      squash: indexes.map((i) => list[i].squash).join(''),
    }
  })
  // 阅读顺序：先上后下、再左后右
  paragraphs.sort((a, b) => a.rect.y - b.rect.y || a.rect.x - b.rect.x)
  return paragraphs
}

/** 一维重叠长度（两个区间）。 */
export function overlap1d(a0, a1, b0, b1) {
  return Math.max(0, Math.min(a1, b1) - Math.max(a0, b0))
}

/**
 * 两个框算不算"同一栏"：**横向**重叠 ≥ 较短那个宽度的 `ratio`。
 *
 * 光看上下位置是不够的——双栏排版里，同一高度上左右两栏都有字，
 * 拿一个右栏段落的 y 区间去比对，左栏的大标题和作者行都会被算进来（实测踩过，
 * 用户截图里就是"高亮框到左栏去了"）。x 比是决定性的那个信号：右栏 1.00、左栏 0.00。
 */
export function sameColumn(a, b, ratio = 0.3) {
  const overlap = overlap1d(a.x, a.x + a.w, b.x, b.x + b.w)
  const shorter = Math.min(a.w, b.w) || 1
  return overlap / shorter >= ratio
}

/** 两个框**竖向**有没有重叠。 */
export function overlapsVertically(a, b) {
  return overlap1d(a.y, a.y + a.h, b.y, b.y + b.h) > 0
}

function sameParagraph(a, b, lineGap, overlapRatio) {
  if (!sameColumn(a.rect, b.rect, overlapRatio)) return false
  const h = Math.max(a.rect.h, b.rect.h) || 10
  const baselineA = a.rect.y + a.rect.h
  const baselineB = b.rect.y + b.rect.h
  return Math.abs(baselineA - baselineB) <= h * lineGap
}

/** 命中点的行文本（给"这段在讲什么"用：命中的那一行 + 上一行 + 下一行）。 */
