/**
 * 校对报告导出（E11 尾）的用例。
 *
 * 分两张桌子测，因为责任不同：
 * ① **纯函数层**（`src/checkExport.js`）——序列化最会"看起来对"：少导一段、
 *    CSV 引号没转义、草稿名里的 `/` 落进文件名，这几样都不会崩、只会悄悄错；
 * ② **组件层**（`WriteView.vue`）——没有报告时不许有按钮、点按钮要真的落成文件、
 *    失败要如实提示（**不许静默**）。
 *
 * ⚠️ 判据是"导出的内容与界面所见一致"：所以这里断言的是**筛子账也在**、
 * **每条 finding 的原句 / 原因 / 判据 / 建议出处都在**、**不出现百分比**。
 */

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WriteView from '../src/views/WriteView.vue'
import { clearTasks } from '../src/stores/useTasks'
import { resetWrite } from '../src/stores/useWrite'
import {
  canExport,
  exportFilename,
  exportMimeType,
  fileStamp,
  formatStamp,
  reportToCsv,
  reportToMarkdown,
  reportToText,
} from '../src/checkExport'

// ============================================================ 夹具

const FINDING_CITE = {
  id: 'f1',
  fingerprint: 'a1',
  rule_id: 'R1',
  kind: 'missing_citation',
  severity: 'report',
  sentence: '研究表明，温度升高会加快反应速率，但选择性下降。',
  reason: '命中标记词「研究表明」，句内无引用标注（numeric）',
  suggest: { material_id: 1, page: 3, quote: '反应速率随温度升高而加快。' },
  rule_ref: '形态 §3.3 ①',
}

const FINDING_QUOTED = {
  id: 'f2',
  fingerprint: 'a2',
  rule_id: 'R4',
  kind: 'format',
  severity: 'report',
  sentence: '缺号：[2]',
  // 故意塞一个英文引号：CSV 那一列必须转义成两个引号，否则整行会被切坏
  reason: '编号从 1 到 3 之间缺 1 个号（原文写的是 "式 2"）',
  suggest: null,
  rule_ref: '形态 §3.3 ③ 引文编号连续性',
}

const FINDING_UNKNOWN = {
  id: 'f3',
  fingerprint: 'a3',
  rule_id: 'R7',
  kind: 'unknown',
  severity: 'unknown',
  sentence: '全篇既无 [n] 也无「（作者，年份）」',
  reason: '判不出引用制式时「该引未引」整族不判——不硬猜',
  suggest: null,
  rule_ref: '形态 §3.3 E2 引用制式盲区',
}

const REPORT = {
  run_id: 12,
  ruleset_version: 1,
  step: {
    lang: 'zh',
    citation_style: 'numeric',
    notes: [
      '该引未引：命中标记词 4 句——已有引用 2、含模糊限定 0、属作者自指 2，报出 0 处',
      '术语一致性：比对 2 条术语——译名分歧 1 组、正文命中 0 句，报出 0 处',
    ],
  },
  findings: [FINDING_CITE, FINDING_QUOTED, FINDING_UNKNOWN],
  summary: { reported: 2, unknown: 1 },
}

/** 界面上的 `checkStep`（`unknown` 已说成「未能识别」）。 */
const STEP = {
  lang: '中文',
  style: '顺序编码制（[n]）',
  unknownLang: false,
  unknownStyle: false,
  ledger: REPORT.step.notes,
}

/** 界面上的 `checkGroups`（顺序与后端 `KIND_ORDER` 一致）。 */
const GROUPS = [
  { kind: 'missing_citation', label: '该引未引', items: [FINDING_CITE], reported: 1, unknown: 0 },
  { kind: 'format', label: '格式自检', items: [FINDING_QUOTED], reported: 1, unknown: 0 },
  { kind: 'unknown', label: '无法判断', items: [FINDING_UNKNOWN], reported: 0, unknown: 1 },
]

const sourceNameOf = () => 'EBSCO_05-mono.pdf'

const STAMP = '2026-10-16 14:05'

function markdownOf(overrides = {}) {
  return reportToMarkdown({
    report: REPORT,
    step: STEP,
    groups: GROUPS,
    title: '开题报告',
    stamp: STAMP,
    sourceNameOf,
    ...overrides,
  })
}

// ============================================================ ① 纯函数层

describe('checkExport：报告 → Markdown', () => {
  it('⭐ 含全部条目 + 筛子账，而且不报百分比', () => {
    const md = markdownOf()

    expect(md).toContain('# 校对检查报告 · 开题报告')
    expect(md).toContain(`- 导出时间：${STAMP}`)
    expect(md).toContain('- 判语言：中文')
    expect(md).toContain('- 引用制式：顺序编码制（[n]）')
    expect(md).toContain('- 汇总：报出 2 处，另有 1 处判不出')
    expect(md).not.toContain('%')

    // ⭐ 筛子账：为什么只报这么少，必须跟着报告一起被带走
    expect(md).toContain('## 筛子账（为什么只报这么少）')
    expect(md).toContain('命中标记词 4 句')
    expect(md).toContain('术语一致性：比对 2 条术语')

    // ⭐ 全部条目：三类都导，一条不许漏
    expect(md).toContain('### 该引未引')
    expect(md).toContain('### 格式自检')
    expect(md).toContain('### 无法判断')
    expect(md).toContain(FINDING_CITE.sentence)
    expect(md).toContain(FINDING_QUOTED.sentence)
    expect(md).toContain(FINDING_UNKNOWN.sentence)

    // 每条都指得出来：原因 + 判据 + 建议引的那一条（出处只有一种写法）
    expect(md).toContain('- 原因：命中标记词「研究表明」')
    expect(md).toContain('- 判据：形态 §3.3 ①')
    expect(md).toContain(
      '- 建议引这一条：EBSCO_05-mono.pdf · 第 3 页 ·「反应速率随温度升高而加快。」',
    )

    // unknown 是"判不出"，不许被写成"待处理"
    expect(md).toContain('- 级别：判不出')
    expect(md).toContain('- 级别：待处理')

    // 报告只出结论、不替人改稿（与抽屉里的口径一致）
    expect(md).toContain('报告只出结论，不替你改稿')
  })

  it('⭐ 判不出语言 / 制式时写「未能识别」，账是空的也如实说', () => {
    const md = markdownOf({
      step: { lang: '未能识别', style: '未能识别', ledger: [] },
    })

    expect(md).toContain('- 判语言：未能识别')
    expect(md).toContain('- 引用制式：未能识别')
    expect(md).toContain('引擎这次没有给出筛子说明。')
  })

  it('没查出问题时如实写一句，不是空白一片', () => {
    const md = reportToMarkdown({
      report: { ...REPORT, findings: [], summary: { reported: 0, unknown: 0 } },
      step: STEP,
      groups: [],
      title: '开题报告',
      stamp: STAMP,
    })

    expect(md).toContain('- 汇总：报出 0 处，另有 0 处判不出')
    expect(md).toContain('这份稿子没查出问题。')
  })

  it('⭐ 分组没跟上的新条目也要导（宁可多一条「其他」，不许漏）', () => {
    const fresh = { ...FINDING_UNKNOWN, id: 'f9', kind: 'brand_new_rule', severity: 'report' }
    const md = markdownOf({
      report: { ...REPORT, findings: [...REPORT.findings, fresh] },
      groups: GROUPS, // 故意不含 brand_new_rule
    })

    expect(md).toContain('### 其他')
    expect(md).toContain(fresh.sentence)
    expect(md).toContain('（共 4 条）')
  })

  it('原句/原因里的换行与连续空白折成一行（导出的是报告，不是另一份版式）', () => {
    const md = markdownOf({
      report: {
        ...REPORT,
        findings: [{ ...FINDING_CITE, sentence: '研究表明，\n  温度升高   会加快反应速率。' }],
      },
      groups: [{ kind: 'missing_citation', label: '该引未引', items: [{ ...FINDING_CITE, sentence: '研究表明，\n  温度升高   会加快反应速率。' }] }],
    })

    expect(md).toContain('研究表明， 温度升高 会加快反应速率。')
  })
})

describe('checkExport：报告 → CSV', () => {
  it('⭐ 一行一条、引号翻倍、带 UTF-8 BOM（Excel 打开不乱码）', () => {
    const csv = reportToCsv({ report: REPORT, groups: GROUPS, sourceNameOf })

    expect(csv.startsWith('\ufeff')).toBe(true)
    expect(csv).toContain('"类型","级别","原句","原因","判据","建议引用的出处"')

    const lines = csv.replace(/^\ufeff/, '').trimEnd().split('\r\n')
    // 表头 + 3 条 finding；⚠️ 原句里有 `"` 也不许把行切坏
    expect(lines).toHaveLength(4)
    expect(lines[2]).toContain('""式 2""')
    expect(lines[1]).toContain('"待处理"')
    expect(lines[1]).toContain('"EBSCO_05-mono.pdf · 第 3 页 ·「反应速率随温度升高而加快。」"')
    expect(lines[3]).toContain('"判不出"')
  })

  it('可以不带 BOM（给"喂脚本"的用法留一条路）', () => {
    const csv = reportToCsv({ report: REPORT, groups: GROUPS, bom: false })
    expect(csv.startsWith('\ufeff')).toBe(false)
    expect(csv.startsWith('"类型"')).toBe(true)
  })
})

describe('checkExport：文件名与格式分发', () => {
  it('⭐ 文件名 = 校对检查 + 草稿名 + 时间戳；草稿名里的路径符号不落进文件名', () => {
    const at = new Date(2026, 9, 16, 14, 5)
    expect(exportFilename('开题报告/初稿:v2', 'csv', at)).toBe(
      '校对检查-开题报告-初稿-v2-20261016-1405.csv',
    )
    expect(exportFilename('   ', 'md', at)).toBe('校对检查-未命名草稿-20261016-1405.md')
    // 不认识的格式退回 md，不生成一个没扩展名的文件
    expect(exportFilename('开题报告', 'docx', at)).toBe('校对检查-开题报告-20261016-1405.md')
    expect(formatStamp(at)).toBe('2026-10-16 14:05')
    expect(fileStamp(at)).toBe('20261016-1405')
    expect(exportMimeType('csv')).toContain('text/csv')
    expect(exportMimeType('md')).toContain('text/markdown')
  })

  it('没有报告就没有可导出的东西（判的是"报告在不在"，不是"有没有查出问题"）', () => {
    expect(canExport(null)).toBe(false)
    expect(canExport(undefined)).toBe(false)
    expect(canExport('报告')).toBe(false)
    expect(canExport({ findings: [], summary: { reported: 0, unknown: 0 } })).toBe(true)
  })

  it('按格式取文本：一个入口，别让调用方自己 switch', () => {
    const options = { report: REPORT, step: STEP, groups: GROUPS, title: '开题报告', stamp: STAMP }
    expect(reportToText('md', options)).toContain('# 校对检查报告')
    expect(reportToText('csv', options)).toContain('"类型"')
    // 传了没见过的格式时按 Markdown 走（与文件名同一条兜底）
    expect(reportToText('pdf', options)).toContain('# 校对检查报告')
  })
})

// ============================================================ ② 组件层

const HEALTH = {
  status: 'ok',
  service: 'docwise-web',
  checks: { database: true, worker: true },
  queue_size: 0,
  running_task_id: null,
  auth: { demo_autologin: false, session_days: 30 },
}

const USER = { id: 1, username: 'tester', display_name: '测试用户', role: 'user' }

const DRAFT = {
  id: 1,
  title: '开题报告',
  body_md: '研究表明，温度升高会加快反应速率。\n',
  template_id: null,
  updated_at: '2026-10-16T02:00:00Z',
  citations: [],
}

const MATERIAL = {
  id: 1,
  text_quote: 'The reaction rate rises with temperature.',
  translated_quote: '反应速率随温度升高而加快。',
  page: 3,
  source_name: 'EBSCO_05-mono.pdf',
  note: null,
  task_id: 42,
  block_id: 'p2_b7',
  deleted_at: null,
  created_at: '2026-10-16T02:00:00Z',
}

function jsonOf(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

function stubFetch(report = REPORT) {
  return vi.fn(async (input, init = {}) => {
    const url = typeof input === 'string' ? input : String(input?.url ?? input)
    if (url.includes('/api/health')) return jsonOf(HEALTH)
    if (url.includes('/api/auth/me')) return jsonOf(USER)
    if (url.includes('/api/materials')) return jsonOf({ items: [MATERIAL] })
    if (url.includes('/api/drafts')) return jsonOf({ items: [DRAFT] })
    if (url.includes('/api/check')) return jsonOf(report)
    return jsonOf({})
  })
}

let blobs
let anchors

function mountWrite() {
  return mount(WriteView, { attachTo: document.body })
}

async function openAndRun(wrapper) {
  await wrapper.find('.wr-check-toggle').trigger('click')
  await wrapper.find('.wr-checkrun button').trigger('click')
  await flushPromises()
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('docwise_token', 'test-token')
  window.history.replaceState(null, '', '#/write')
  globalThis.fetch = stubFetch()
  resetWrite()
  clearTasks()

  // 下载在 happy-dom 里没有真实现：把 Blob 与 <a> 截下来，断言"落成的是哪个文件"
  blobs = []
  anchors = []
  globalThis.URL.createObjectURL = vi.fn((blob) => {
    blobs.push(blob)
    return 'blob:test'
  })
  globalThis.URL.revokeObjectURL = vi.fn()
  vi.spyOn(HTMLElement.prototype, 'click').mockImplementation(() => {})
  const createElement = document.createElement.bind(document)
  vi.spyOn(document, 'createElement').mockImplementation((tag, ...rest) => {
    const el = createElement(tag, ...rest)
    if (String(tag).toLowerCase() === 'a') anchors.push(el)
    return el
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  resetWrite()
  clearTasks()
  document.body.innerHTML = ''
})

describe('WriteView：报告导出（E11 尾）', () => {
  it('⭐ 没有报告就没有导出按钮（不是灰的，是根本不在）', async () => {
    const wrapper = mountWrite()
    await flushPromises()
    await wrapper.find('.wr-check-toggle').trigger('click')
    expect(wrapper.find('.wr-check').exists()).toBe(true)
    expect(wrapper.find('.wr-checkexport').exists()).toBe(false)
    wrapper.unmount()
  })

  it('⭐ 跑完检查就有两颗按钮，点 Markdown 真的落成文件（名字带草稿名与时间戳）', async () => {
    const wrapper = mountWrite()
    await flushPromises()
    await openAndRun(wrapper)

    const buttons = wrapper.findAll('.wr-checkexport button')
    expect(buttons.map((node) => node.attributes('data-format'))).toEqual(['md', 'csv'])

    await wrapper.find('.wr-checkexport button[data-format="md"]').trigger('click')

    expect(anchors).toHaveLength(1)
    expect(anchors[0].download).toMatch(/^校对检查-开题报告-\d{8}-\d{4}\.md$/)
    expect(blobs).toHaveLength(1)
    expect(blobs[0].type).toContain('text/markdown')
    // 导出的是这份报告本身（不是空文件、也不是一句"已导出"）
    expect(blobs[0].size).toBeGreaterThan(200)
    // 临时链用完即撤，不留悬着的 object URL
    expect(globalThis.URL.revokeObjectURL).toHaveBeenCalledWith('blob:test')
    wrapper.unmount()
  })

  it('⭐ 点 CSV 走的是 CSV（扩展名与 MIME 都对）', async () => {
    const wrapper = mountWrite()
    await flushPromises()
    await openAndRun(wrapper)

    await wrapper.find('.wr-checkexport button[data-format="csv"]').trigger('click')

    expect(anchors[0].download).toMatch(/\.csv$/)
    expect(blobs[0].type).toContain('text/csv')
    wrapper.unmount()
  })

  it('⭐ 导出失败如实提示，不许静默', async () => {
    globalThis.URL.createObjectURL = vi.fn(() => {
      throw new Error('浏览器不给下载')
    })
    const wrapper = mountWrite()
    await flushPromises()
    await openAndRun(wrapper)

    await wrapper.find('.wr-checkexport button[data-format="md"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('.wr-checkexport').exists()).toBe(true)
    expect(wrapper.text()).toContain('导出没成')
    expect(wrapper.text()).toContain('浏览器不给下载')
    wrapper.unmount()
  })

  it('导出的按钮不改稿：点完导出，正文与检查报告都没被动过', async () => {
    const wrapper = mountWrite()
    await flushPromises()
    await openAndRun(wrapper)

    const before = wrapper.find('.wr-editor').element.value
    await wrapper.find('.wr-checkexport button[data-format="md"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('.wr-editor').element.value).toBe(before)
    expect(wrapper.find('.wr-check').text()).toContain('报出 2 处')
    wrapper.unmount()
  })
})
