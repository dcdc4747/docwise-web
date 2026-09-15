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
 * 同一行的判定：基线 y 差不到半个字高（pdf.js 的条目坐标是 `[a,b,c,d,e,f]`，
 * e 是 x、f 是基线 y）。行内按 x 从左到右拼。
 *
 * @param {{text:string,x:number,y:number,w:number,h:number}[]} boxes 已经换算成视口坐标的条目
 * @returns {{text:string,norm:string,squash:string,rect:{x:number,y:number,w:number,h:number}}[]}
 */
export function buildLines(boxes) {
  const lines = []
  let current = null

  for (const box of boxes || []) {
    const text = String(box?.text ?? '')
    if (!text.trim()) continue
    const height = Number(box.h) || 10
    // 基线 y（box.y 是基线）——同一行差不到半个字高就算一行
    if (!current || Math.abs(current.baseline - box.y) > height * 0.5) {
      current = { baseline: box.y, height, parts: [] }
      lines.push(current)
    }
    current.parts.push(box)
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
 * 把一页的所有行拼成"可搜索文本"，并记住每个字符属于哪一行。
 * 用**去空白**的串来搜：块文本的行断点不一定和渲染后的 PDF 一致，
 * 去掉空白后"跨行/跨条目有没有空格"就不再影响命中（这是实测出来的需要）。
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
  return { page: pageNumber, lines: lines || [], flat, owners }
}

/** 在一页里搜一段文本（都已去空白）。命中返回它覆盖的行号区间。 */
export function findInPage(index, needleSquash) {
  if (!index || !needleSquash) return null
  const at = index.flat.indexOf(needleSquash)
  if (at < 0) return null
  const last = Math.min(at + needleSquash.length - 1, index.owners.length - 1)
  return { from: index.owners[at], to: index.owners[last] }
}

/**
 * 在整个文档里找一段文本，返回 **第一个** 命中的页与要高亮的行。
 *
 * 分档降级：先用整段（最准），对不上再用更短的前缀——块文本是引擎从**原 PDF**
 * 抽的，行断点/连字符可能和渲染结果不同；短前缀能容忍尾部差异，
 * 但**不短于 16 个字符**，免得随便一段就把高亮打到不相干的地方。
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
      const hit = findInPage(index, candidate)
      if (hit) {
        const lines = index.lines.slice(hit.from, hit.to + 1)
        return {
          page: index.page,
          from: hit.from,
          to: hit.to,
          rects: lines.map((line) => line.rect),
          matchedChars: candidate.length,
          exact: candidate === full,
        }
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

/** 点一下落在哪一行上（坐标是缩放系数为 1 的视口坐标）。命中不到返回 -1。 */
export function hitLine(lines, x, y) {
  for (let i = 0; i < (lines || []).length; i += 1) {
    const rect = lines[i].rect
    // 上下各放宽 2 个点：行高很窄时点边上也该算中
    if (x >= rect.x - 2 && x <= rect.x + rect.w + 2 && y >= rect.y - 2 && y <= rect.y + rect.h + 2) {
      return i
    }
  }
  return -1
}
