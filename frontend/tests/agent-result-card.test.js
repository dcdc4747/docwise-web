/**
 * 结构化工具结果的小卡片。
 *
 * 后端发来的是 **Python dict 字符串的前 400 字**（不是 JSON，还可能被截断），
 * 所以这里既测纯函数（抽得到 / 抽不到 / 截断不崩），也真的挂载一次
 * `AgentChat`，确认「返回 run_check」那一行下面出现了卡片、不认识的结果不受影响。
 */

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// TipTap/ProseMirror 需要真实 DOM 量测，happy-dom 里跑不了；单测里换成轻量替身。
vi.mock('../src/components/WriteEditor.vue', () => import('./helpers/WriteEditorStub.js'))

vi.mock('../src/auth', () => ({
  authFetch: vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      configured: false,
      key_set: false,
      server_default: false,
      providers: [],
      tier_models: {},
      model: '',
      tier: 'standard',
    }),
  })),
}))

import AgentChat from '../src/components/AgentChat.vue'
import { summarizeToolResult } from '../src/agentResult'
import { agentMessages } from '../src/stores/useAgent'

/**
 * 本地后端实跑 `draft_id=1` 得到的 excerpt（原样前 400 字，含截断）。
 * 生成方式：`str(check_pack.run_check(ctx).data)[:400]`。
 */
const REAL_DRAFT_1 = `{'draft_id': 1, 'title': '窄屏量测草稿', 'findings': [], 'summary': {'total': 0, 'by_kind': {'citation_number': 0, 'unsourced_claim': 0, 'term_inconsistent': 0, 'citation_format': 0, 'unknown': 0}}, 'terms_note': '对照了 15 条术语', 'term_rate': {'rate': None, 'total': 0, 'ok': 0, 'note': '术语一致率无法计算（正文里没有出现术语）'}, 'citation_gaps': [], 'citation_gaps_note': '未发现疑似该引未引的句子', 'truncated': 0, 'note': '草稿正文还是空的，没有可检`

/**
 * 本地后端实跑 `draft_id=2` 得到的 excerpt：3 条 findings，
 * 400 字在 `summary` 里被截断（term_rate / citation_gaps_note 都不在里面）。
 */
const REAL_DRAFT_2 = `{'draft_id': 2, 'title': '未命名草稿', 'findings': [{'kind': 'citation_number', 'level': 'warn', 'detail': '[1] —— 文献表第 1 条在正文里从没被引用过', 'rule_id': 'R3', 'sentence': '[1]'}, {'kind': 'citation_format', 'level': 'info', 'detail': '[1] math_arXiv_2609.38101v1.pdf —— 条目缺字段：author', 'rule_id': 'R5', 'sentence': '[1] math_arXiv_2609.38101v1.pdf'}, {'kind': 'unknown', 'level': 'info', 'detail': '全篇既无 \`[n]\` 也无`

/** 用户描述的那类结果：术语一致率 67%，note 里带中文引号与全角括号。 */
const RATE_67 = `{'draft_id': 8, 'title': '手性分子旋转动力学', 'findings': [{'kind': 'term_inconsistent', 'level': 'warn', 'detail': '「chiral」同时出现「手性」与「手征」', 'rule_id': 'R6', 'sentence': '手性与手征混用。'}], 'summary': {'total': 1, 'by_kind': {}}, 'terms_note': '对照了 5 条术语', 'term_rate': {'rate': 0.67, 'total': 3, 'ok': 2, 'note': '术语一致率 67%（2/3）；「chiral」同时出现「手性」与「手征」，建议统一'}, 'citation_gaps': [], 'citation_gaps_note': '有 3 句像是引述他人成果但没有引用标记', 'truncated': 0, 'note': '1 处需要看一眼'}`

describe('summarizeToolResult（纯字符串解析）', () => {
  it('真实 run_check excerpt（draft 1）：term_rate / citation_gaps_note 都抽出来', () => {
    const card = summarizeToolResult('run_check', REAL_DRAFT_1)
    expect(card.kind).toBe('check')
    expect(card.lines).toEqual(['发现 0 处'])
    expect(card.chips).toEqual([
      '术语一致率无法计算（正文里没有出现术语）',
      '未发现疑似该引未引的句子',
    ])
  })

  it('真实 run_check excerpt 被截断在 summary（draft 2）：照样数出已露出的 3 条，不崩', () => {
    const card = summarizeToolResult('run_check', REAL_DRAFT_2)
    expect(card.kind).toBe('check')
    expect(card.lines).toEqual(['发现 3 处'])
    // 截断点之前的 term_rate / citation_gaps_note 还没出现 → 不编
    expect(card.chips).toEqual([])
  })

  it('中文引号与全角括号的 note 原样抽出，并按「发现 N 处」给一行', () => {
    const card = summarizeToolResult('run_check', RATE_67)
    expect(card.lines).toEqual(['发现 1 处'])
    expect(card.chips).toEqual([
      '术语一致率 67%（2/3）；「chiral」同时出现「手性」与「手征」，建议统一',
      '有 3 句像是引述他人成果但没有引用标记',
    ])
    // 卡片最多 3 行 chip
    expect(card.chips.length).toBeLessThanOrEqual(3)
  })

  it('note 的引号被截断（没闭合）→ 不把半句话当 chip', () => {
    const excerpt = `{'draft_id': 8, 'findings': [], 'term_rate': {'rate': 0.5, 'note': '术语一致率 50%（`
    const card = summarizeToolResult('run_check', excerpt)
    expect(card.kind).toBe('check')
    expect(card.chips).toEqual([])
    expect(card.lines).toEqual(['发现 0 处'])
  })

  it('findings 数组未闭合也能数已经出现的条数，不抛异常', () => {
    const excerpt = `{'findings': [{'kind': 'citation_number', 'detail': '[1]'}, {'kind': 'term_inconsistent'`
    const card = summarizeToolResult('run_check', excerpt)
    expect(card.lines).toEqual(['发现 2 处'])
    expect(card.chips).toEqual([])
  })

  it('没有 term_rate / citation_gaps_note / findings → 返回空（不编）', () => {
    const card = summarizeToolResult('run_check', `{'draft_id': 9, 'note': '找不到这篇草稿'}`)
    expect(card).toEqual({ kind: 'check', lines: [], chips: [] })
  })

  it('term_rate 里没有 note 时，不会把顶层 note 误当成术语说明', () => {
    const excerpt = `{'draft_id': 8, 'term_rate': {'rate': 0.5, 'total': 2, 'ok': 1}, 'note': '这不是术语说明'}`
    const card = summarizeToolResult('run_check', excerpt)
    expect(card.chips).toEqual([])
  })

  it("Python repr 里的转义引号（\\'）能还原，不会把 note 截断", () => {
    const excerpt = `{'term_rate': {'rate': 1.0, 'note': '术语一致率 100%（3/3）；别名 \\'chiral\\' 没有出现'}}`
    const card = summarizeToolResult('run_check', excerpt)
    expect(card.chips).toEqual(["术语一致率 100%（3/3）；别名 'chiral' 没有出现"])
  })

  it('matrix 工具只认类型、不解析内容（不认识的就不出卡片）', () => {
    const card = summarizeToolResult('build_matrix', `{'columns': ['a'], 'rows': [{'kind': 'x'}]}`)
    expect(card).toEqual({ kind: 'matrix', lines: [], chips: [] })
  })

  it('其它工具一律 unknown：即使 excerpt 里恰好有同名字段也不抽', () => {
    const card = summarizeToolResult(
      'search_library',
      `{'term_rate': {'note': '术语一致率 67%（2/3）'}, 'citation_gaps_note': '有 3 句…'}`,
    )
    expect(card).toEqual({ kind: 'unknown', lines: [], chips: [] })
  })

  it('空输入不崩：空工具名 / 空 excerpt / null excerpt', () => {
    expect(summarizeToolResult('', '')).toEqual({ kind: 'unknown', lines: [], chips: [] })
    expect(summarizeToolResult('run_check', '')).toEqual({ kind: 'check', lines: [], chips: [] })
    expect(summarizeToolResult('run_check', null)).toEqual({ kind: 'check', lines: [], chips: [] })
  })

  it('两条 chip 文案相同时去重，只显示一条', () => {
    const excerpt = `{'term_rate': {'note': '同一句'}, 'citation_gaps_note': '同一句'}`
    const card = summarizeToolResult('run_check', excerpt)
    expect(card.chips).toEqual(['同一句'])
  })
})

describe('AgentChat 里的结果卡片', () => {
  beforeEach(() => {
    agentMessages.value.length = 0
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function pushTurn(stepNamesAndExcerpts, extra = {}) {
    const steps = []
    for (const [name, excerpt] of stepNamesAndExcerpts) {
      steps.push({ kind: 'tool_call', name, args: {} })
      steps.push({ kind: 'tool_result', name, ok: true, excerpt })
    }
    agentMessages.value.push({
      role: 'assistant',
      text: '检查完了。',
      steps,
      sources: [],
      dropped: [],
      revisions: [],
      done: false,
      ...extra,
    })
  }

  it('生成中：卡片就渲染在「返回 run_check」那一行下面（chip + 灰色小字）', async () => {
    const wrapper = mount(AgentChat, { props: { scope: {} } })
    await flushPromises()
    pushTurn([['run_check', RATE_67]])
    await flushPromises()

    const cards = wrapper.findAll('.agent-result-card')
    expect(cards).toHaveLength(1)
    expect(cards[0].findAll('.agent-result-chip').map((node) => node.text())).toEqual([
      '术语一致率 67%（2/3）；「chiral」同时出现「手性」与「手征」，建议统一',
      '有 3 句像是引述他人成果但没有引用标记',
    ])
    expect(cards[0].find('.agent-result-line').text()).toBe('发现 1 处')

    // 卡片属于 run_check 那一行，而不是另起一坨
    const line = cards[0].element.closest('li')
    expect(line).toBeTruthy()
    expect(line.textContent).toContain('返回')
    expect(line.textContent).toContain('run_check')
  })

  it('收尾后展开过程，卡片仍在；不认识的工具结果保持原样（没有卡片）', async () => {
    const wrapper = mount(AgentChat, { props: { scope: { task_id: 41 } } })
    await flushPromises()
    pushTurn([['search_library', `{'term_rate': {'note': '不该被抽'}}`]], { done: true })
    await flushPromises()

    // 不认识的结果：过程里没有卡片
    expect(wrapper.findAll('.agent-result-card')).toHaveLength(0)

    // 换成认识的 run_check，收尾后点开过程能看到卡片
    agentMessages.value.splice(0, 1, {
      role: 'assistant',
      text: '检查完了。',
      steps: [
        { kind: 'tool_call', name: 'run_check', args: {} },
        { kind: 'tool_result', name: 'run_check', ok: true, excerpt: REAL_DRAFT_1 },
      ],
      sources: [],
      dropped: [],
      revisions: [],
      done: true,
    })
    await flushPromises()
    expect(wrapper.findAll('.agent-result-card')).toHaveLength(0)
    await wrapper.find('.agent-trace-head').trigger('click')
    expect(wrapper.findAll('.agent-result-card')).toHaveLength(1)
    expect(wrapper.find('.agent-result-card').text()).toContain('未发现疑似该引未引的句子')
  })

  it('抽不到内容的 run_check（如只有 draft_id）不渲染空卡片', async () => {
    const wrapper = mount(AgentChat, { props: { scope: {} } })
    await flushPromises()
    pushTurn([['run_check', `{'draft_id': 9, 'note': '找不到这篇草稿'}`]])
    await flushPromises()
    expect(wrapper.findAll('.agent-result-card')).toHaveLength(0)
  })

  it('轨迹页同样带卡片（不是只有对话流里能看懂）', async () => {
    const wrapper = mount(AgentChat, { props: { scope: {} } })
    await flushPromises()
    pushTurn([['run_check', RATE_67]], { done: true })
    await flushPromises()

    const traceBtn = wrapper.findAll('.agent-views button').find((b) => b.text().includes('轨迹'))
    expect(traceBtn).toBeTruthy()
    await traceBtn.trigger('click')
    expect(wrapper.find('.agent-trace-view').exists()).toBe(true)
    expect(wrapper.findAll('.agent-result-card')).toHaveLength(1)
    expect(wrapper.find('.agent-result-line').text()).toBe('发现 1 处')
  })
})
