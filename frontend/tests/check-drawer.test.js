/**
 * 校对检查抽屉（M4）的用例。
 *
 * 这一包盯五件"做错了看不出来"的事：
 *
 * ① ⭐ **抽屉只出报告、不带"一键改好"**：形态 §3.3 ② 明写"并列摆出两处，不自动改"，
 *    所以结构性断言页面上不许出现"自动改 / 一键修 / 替你改"这类字样；
 * ② ⭐ **`unknown` 单独一栏**，不混进"该报的"里充数（判不出 ≠ 没问题）；
 * ③ ⭐ **每条 finding 都指得出处**：原句 + 原因 + 判据（`rule_ref`）+ 候选素材；
 * ④ ⭐ **不报百分比**（卡④⑧）：报告与界面都只写"报出 N 处 / 另有 M 处判不出"；
 * ⑤ 请求带的是**当前草稿的 id 与正文**（契约 N22 的入参形状）。
 */

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WriteView from '../src/views/WriteView.vue'
import { clearTasks } from '../src/stores/useTasks'
import { resetWrite } from '../src/stores/useWrite'

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

/** 一份三类都有的报告：该引未引（带候选素材）/ 格式 / 无法判断。 */
const REPORT = {
  run_id: 12,
  ruleset_version: 1,
  step: {
    lang: 'zh',
    citation_style: 'numeric',
    notes: [
      '语言：zh（中文字符 120 / 拉丁字母 0）',
      '引用制式：numeric（`[n]` 2 处 / 著者-年 0 处）',
      '该引未引：命中标记词 4 句——已有引用 2、含模糊限定 0、属作者自指 2，报出 0 处',
      '术语一致性：比对 2 条术语——译名分歧 1 组、正文命中 0 句，报出 0 处',
    ],
  },
  findings: [
    {
      id: 'f1',
      fingerprint: 'a1',
      rule_id: 'R1',
      kind: 'missing_citation',
      severity: 'report',
      sentence: '研究表明，温度升高会加快反应速率，但选择性下降。',
      reason: '命中标记词「研究表明」，句内无引用标注（numeric）',
      suggest: { material_id: 1, page: 3, quote: '反应速率随温度升高而加快。' },
      rule_ref: '形态 §3.3 ①',
    },
    {
      id: 'f2',
      fingerprint: 'a2',
      rule_id: 'R4',
      kind: 'format',
      severity: 'report',
      sentence: '缺号：[2]',
      reason: '编号从 1 到 3 之间缺 1 个号',
      suggest: null,
      rule_ref: '形态 §3.3 ③ 引文编号连续性',
    },
    {
      id: 'f3',
      fingerprint: 'a3',
      rule_id: 'R7',
      kind: 'unknown',
      severity: 'unknown',
      sentence: '全篇既无 [n] 也无「（作者，年份）」',
      reason: '判不出引用制式时「该引未引」整族不判——不硬猜',
      suggest: null,
      rule_ref: '形态 §3.3 E2 引用制式盲区',
    },
  ],
  summary: { reported: 2, unknown: 1 },
}

function jsonOf(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

function stubCheckFetch({ report = REPORT, status = 200 } = {}) {
  const calls = []
  const impl = vi.fn(async (input, init = {}) => {
    const url = typeof input === 'string' ? input : String(input?.url ?? input)
    const method = (init.method || 'GET').toUpperCase()
    calls.push({ method, url, body: init.body ? JSON.parse(init.body) : null })
    if (url.includes('/api/health')) return jsonOf(HEALTH)
    if (url.includes('/api/auth/me')) return jsonOf(USER)
    if (url.includes('/api/materials')) return jsonOf({ items: [MATERIAL] })
    if (url.includes('/api/drafts')) return jsonOf({ items: [DRAFT] })
    if (url.includes('/api/check')) {
      if (status !== 200) return jsonOf({ detail: '检查服务挂了' }, status)
      return jsonOf(report)
    }
    return jsonOf({})
  })
  return { impl, calls }
}

let fetchState

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
  fetchState = stubCheckFetch()
  globalThis.fetch = fetchState.impl
  resetWrite()
  clearTasks()
})

afterEach(() => {
  vi.restoreAllMocks()
  resetWrite()
  clearTasks()
  document.body.innerHTML = ''
})

describe('校对检查抽屉（M4 / 形态 §3.3）', () => {
  it('⭐ 抽屉里摆出「筛子账」：为什么只报这么少要看得见', async () => {
    const wrapper = mountWrite()
    // ⚠️ 先等首屏（草稿/素材）就绪：不等就点「开始检查」，此时还没有草稿 id、跑不出报告
    await flushPromises()
    await openAndRun(wrapper)
    const ledger = wrapper.find('.wr-checkledger')
    expect(ledger.exists()).toBe(true)
    expect(ledger.text()).toContain('命中标记词 4 句')
    expect(ledger.text()).toContain('报出 0 处')
    // ⭐ R6 启用后**术语那本账也要露出来**（少了它，"术语没报"就又成了黑箱）
    // 夹具与报告自洽：这份报告里没有术语类 finding，所以账写的是"报出 0 处"
    expect(ledger.text()).toContain(
      '术语一致性：比对 2 条术语——译名分歧 1 组、正文命中 0 句，报出 0 处',
    )
    // 语言/制式已经在上面两个 chip 里了，账里**不重复**它们（别把抽屉塞成一坨日志）
    expect(ledger.text()).not.toContain('语言：')
    expect(ledger.text()).not.toContain('引用制式：')
  })

  it('默认不出现；点顶栏「校对检查」才拉开（它是抽屉，不是独立页面）', async () => {
    const wrapper = mountWrite()
    await flushPromises()
    expect(wrapper.find('.wr-check').exists()).toBe(false)

    await wrapper.find('.wr-check-toggle').trigger('click')
    expect(wrapper.find('.wr-check').exists()).toBe(true)
    expect(wrapper.find('.wr-checkmask').exists()).toBe(true)
    wrapper.unmount()
  })

  it('⭐ Esc 关、点遮罩关（形态 §3.3 的两条关法）', async () => {
    const wrapper = mountWrite()
    await flushPromises()
    await wrapper.find('.wr-check-toggle').trigger('click')
    expect(wrapper.find('.wr-check').exists()).toBe(true)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(wrapper.find('.wr-check').exists()).toBe(false)

    await wrapper.find('.wr-check-toggle').trigger('click')
    await wrapper.find('.wr-checkmask').trigger('click')
    expect(wrapper.find('.wr-check').exists()).toBe(false)
    wrapper.unmount()
  })

  it('⭐ 请求带的是当前草稿的 id 与正文（契约 N22 的入参）', async () => {
    const wrapper = mountWrite()
    await flushPromises()
    await openAndRun(wrapper)

    // ⚠️ 2026-10-18：开抽屉会先 GET 一次历史（N43），所以这里要挑 **POST 那条**
    const call = fetchState.calls.find(
      (item) => item.url.includes('/api/check') && item.method === 'POST',
    )
    expect(call.method).toBe('POST')
    expect(call.body.draft_id).toBe(1)
    expect(call.body.doc_text).toContain('研究表明')
    wrapper.unmount()
  })

  it('⭐ 报告按类分组：该引未引 / 格式自检 / 无法判断 各一栏', async () => {
    const wrapper = mountWrite()
    await flushPromises()
    await openAndRun(wrapper)

    const kinds = wrapper.findAll('.wr-checkkind').map((node) => node.text())
    expect(kinds).toEqual(['该引未引', '格式自检', '无法判断'])
    wrapper.unmount()
  })

  it('⭐ 每条都指得出处：原句 + 原因 + 判据', async () => {
    const wrapper = mountWrite()
    await flushPromises()
    await openAndRun(wrapper)

    expect(wrapper.find('.wr-checkquote').text()).toContain('温度升高会加快反应速率')
    expect(wrapper.text()).toContain('命中标记词「研究表明」')
    expect(wrapper.text()).toContain('形态 §3.3 ①')
    wrapper.unmount()
  })

  it('⭐ 该引未引带候选素材：显示「第 X 页 · 哪一句」，点它回素材那一句', async () => {
    const wrapper = mountWrite()
    await flushPromises()
    await openAndRun(wrapper)

    const chip = wrapper.find('.wr-checksuggest .cite-chip')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('第 3 页')
    expect(chip.text()).toContain('EBSCO_05-mono.pdf')

    // 点它 → 走的是"回素材那一句"（jumpToSuggested → jumpToMaterial），不该抛错
    await chip.trigger('click')
    await flushPromises()
    wrapper.unmount()
  })

  it('⭐ unknown 单独一栏，且不混进"报出"的计数里', async () => {
    const wrapper = mountWrite()
    await flushPromises()
    await openAndRun(wrapper)

    const labels = wrapper.findAll('.wr-checkkind').map((node) => node.text())
    expect(labels).toContain('无法判断')
    // 汇总只写两件事，且**不出现百分比**
    const sum = wrapper.find('.wr-checksum').text()
    expect(sum).toContain('报出 2 处')
    expect(sum).toContain('1 处判不出')
    expect(sum).not.toContain('%')
    expect(wrapper.find('.wr-check').text()).not.toContain('%')
    wrapper.unmount()
  })

  it('⭐ 抽屉里不许出现"替你改"的入口（形态 §3.3 ②：不自动改）', async () => {
    const wrapper = mountWrite()
    await flushPromises()
    await openAndRun(wrapper)

    const text = wrapper.find('.wr-check').text()
    for (const word of ['自动改', '一键修', '替你改', '自动修']) {
      expect(text).not.toContain(word)
    }
    wrapper.unmount()
  })

  it('判不出语言/制式时，界面上如实说「未能识别」并解释为什么整族不判', async () => {
    const unknownStep = {
      ...REPORT,
      step: { lang: 'unknown', citation_style: 'unknown', notes: [] },
      findings: [REPORT.findings[2]],
      summary: { reported: 0, unknown: 1 },
    }
    fetchState = stubCheckFetch({ report: unknownStep })
    globalThis.fetch = fetchState.impl

    const wrapper = mountWrite()
    await flushPromises()
    await openAndRun(wrapper)

    const step = wrapper.find('.wr-checkstep').text()
    expect(step).toContain('未能识别')
    expect(wrapper.text()).toContain('整族不判')
    expect(wrapper.find('.wr-checksum').text()).toContain('报出 0 处')
    wrapper.unmount()
  })

  it('检查失败如实说，不摆一份假报告', async () => {
    fetchState = stubCheckFetch({ status: 500 })
    globalThis.fetch = fetchState.impl

    const wrapper = mountWrite()
    await flushPromises()
    await openAndRun(wrapper)

    expect(wrapper.find('.wr-checkgroup').exists()).toBe(false)
    expect(wrapper.find('.wr-checksum').exists()).toBe(false)
    expect(wrapper.find('.wr-check').text()).toContain('检查没跑成')
    wrapper.unmount()
  })

  it('没查出问题时如实写「没查出问题」，不是空白一片', async () => {
    fetchState = stubCheckFetch({
      report: { ...REPORT, findings: [], summary: { reported: 0, unknown: 0 } },
    })
    globalThis.fetch = fetchState.impl

    const wrapper = mountWrite()
    await flushPromises()
    await openAndRun(wrapper)

    expect(wrapper.find('.wr-checksum').text()).toContain('报出 0 处')
    expect(wrapper.text()).toContain('没查出问题')
    wrapper.unmount()
  })
})
