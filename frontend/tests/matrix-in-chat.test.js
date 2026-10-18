/**
 * 矩阵结果进对话：`parseMatrix`（纯字符串解析）+ `AgentChat` 里的表格。
 *
 * 后端 `build_matrix` 的 excerpt 是 **Python `str(dict)` 的前 300/400 字**
 * （单引号、`None`、还可能被截断），所以两条底线：
 *
 * 1. **解析不出来就 `null`**——宁可不显示，也不显示半张错表；
 * 2. 解析成功但**一行都没有**时，`AgentChat` 不渲染空表（空表会被读成
 *    "这些文献都没有导读"，而实际可能只是 excerpt 被截断了）。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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
import { parseMatrix } from '../src/agentResult'
import { agentMessages } from '../src/stores/useAgent'

/**
 * 本地后端实跑 `build_matrix` 的形状（`app/agent/packs/matrix.py`：
 * 扁平行 + `file`，`columns` 里第一条就是「文献」）。
 */
const REAL_MATRIX = `{'topic': '手性', 'columns': ['文献', '研究问题', '方法', '结论', '术语', '可引用句'], 'rows': [{'task_id': 41, 'file': '手性-化学.pdf', 'research_question': '手性时间结构能否分开？', 'method': '数值模拟', 'conclusion': '手性可以分成时间与空间两部分。', 'terms': ['chirality', '手性'], 'quote': '手性可以分成时间与空间两部分。'}], 'missing': []}`

/** 有文献还没有导读：`missing` 是 `{task_id, why}` 的列表（`build_matrix` 的真实形状）。 */
const REAL_MATRIX_MISSING = `{'topic': '矩阵', 'columns': ['文献', '研究问题', '方法', '结论', '术语', '可引用句'], 'rows': [], 'missing': [{'task_id': 43, 'why': '还没有导读'}]}`

/** excerpt 被 300/400 字截断在 `conclusion` 的字符串中间（真实会发生）。 */
const TRUNCATED = `{'topic': '手性', 'columns': ['文献', '研究问题', '方法', '结论', '术语', '可引用句'], 'rows': [{'task_id': 41, 'file': '手性-化学.pdf', 'research_question': '手性时间结构能否分开？', 'method': '数值模拟', 'conclusion': '手性可以分成时间与空`

/** `MatrixTable` 认的列（表格第一列固定「文献」，所以 columns 里那条要剔掉）。 */
const TABLE_COLUMNS = ['研究问题', '方法', '结论', '术语', '可引用句']

/** AgentChat 组件源码：钉"折叠 / 可滚动"这类只存在于样式里的口径。 */
const chatSource = readFileSync(
  resolve(process.cwd(), 'src/components/AgentChat.vue'),
  'utf8',
)

/** agentResult 源码（剥掉注释），钉"不 eval、不 JSON.parse"。 */
function codeWithoutComments(rel) {
  const text = readFileSync(resolve(process.cwd(), rel), 'utf8')
  return text
    .split('\n')
    .filter((line) => {
      const trimmed = line.trim()
      return !trimmed.startsWith('*') && !trimmed.startsWith('/*') && !trimmed.startsWith('//')
    })
    .join('\n')
}

describe('parseMatrix（纯字符串解析 Python repr）', () => {
  it('真实 build_matrix excerpt：扁平行搬成 MatrixTable 的 {filename, cells}', () => {
    const data = parseMatrix(REAL_MATRIX)

    expect(data).not.toBeNull()
    expect(data.topic).toBe('手性')
    // 「文献」被剔掉：表格第一列固定是它，留着就会出两个「文献」表头
    expect(data.columns).toEqual(TABLE_COLUMNS)
    expect(data.rows).toEqual([
      {
        filename: '手性-化学.pdf',
        cells: {
          研究问题: '手性时间结构能否分开？',
          方法: '数值模拟',
          结论: '手性可以分成时间与空间两部分。',
          术语: ['chirality', '手性'],
          可引用句: '手性可以分成时间与空间两部分。',
        },
      },
    ])
    expect(data.missing).toEqual([])
  })

  it('missing 里的 {task_id, why} 原样保留（表格只用它的条数）', () => {
    const data = parseMatrix(REAL_MATRIX_MISSING)
    expect(data).not.toBeNull()
    expect(data.rows).toEqual([])
    expect(data.missing).toEqual([{ task_id: 43, why: '还没有导读' }])
  })

  it('截断 → null：字符串没闭合、列表没闭合、顶层字典没闭合都不显示半张表', () => {
    expect(parseMatrix(TRUNCATED)).toBeNull()
    expect(parseMatrix(`{'topic': '手性', 'columns': ['文献', '研究`)).toBeNull()
    // 截在行中间：rows 数组没闭合
    expect(
      parseMatrix(
        `{'topic': '手性', 'columns': ['研究问题'], 'rows': [{'filename': 'a.pdf', 'cells': {'研究问题': '半句`,
      ),
    ).toBeNull()
    // 空字符串 / 不是 repr
    expect(parseMatrix('')).toBeNull()
    expect(parseMatrix('None')).toBeNull()
    expect(parseMatrix(null)).toBeNull()
  })

  it('None 当空：topic / 格子 / missing 都不编内容', () => {
    const data = parseMatrix(
      `{'topic': None, 'columns': None, 'rows': [{'filename': 'a.pdf', 'cells': {'研究问题': None, '方法': '实验'}}], 'missing': None}`,
    )

    expect(data).not.toBeNull()
    expect(data.topic).toBe('')
    expect(data.columns).toEqual([])
    expect(data.rows).toEqual([{ filename: 'a.pdf', cells: { 研究问题: null, 方法: '实验' } }])
    expect(data.missing).toEqual([])
  })

  it('单引号 / 双引号混用（Python 按内容选引号）都能还原，含转义的单引号', () => {
    // topic 里有双引号 → repr 用单引号；格子里有单引号 → repr 用双引号
    const mixed = parseMatrix(
      `{'topic': '他说"手性"很重要', 'columns': ['研究问题'], 'rows': [{'filename': 'a.pdf', 'cells': {'研究问题': "教授说'手性'是关键"}}]}`,
    )
    expect(mixed.topic).toBe('他说"手性"很重要')
    expect(mixed.rows[0].cells.研究问题).toBe("教授说'手性'是关键")

    // 两种引号都有时，Python 会把单引号转义成 \'
    const escaped = parseMatrix(
      `{'topic': '手性', 'columns': ['研究问题'], 'rows': [{'filename': 'a.pdf', 'cells': {'研究问题': '他说 \\'手性\\' 与 "时间" 都重要'}}]}`,
    )
    expect(escaped.rows[0].cells.研究问题).toBe('他说 \'手性\' 与 "时间" 都重要')
  })

  it('rows 为空：解析成功但一行都没有（空表由 AgentChat 决定不渲染）', () => {
    const data = parseMatrix(REAL_MATRIX_MISSING)
    expect(data).not.toBeNull()
    expect(data.rows).toHaveLength(0)
  })

  it('不是矩阵结果 / 行认不出形状 → null（不拿别的工具结果凑表）', () => {
    expect(parseMatrix(`{'note': '找不到这篇草稿'}`)).toBeNull()
    expect(parseMatrix(`{'columns': ['研究问题'], 'rows': 'oops'}`)).toBeNull()
    // 既没有文件名、也没有任何一格内容：不渲染一行全是「—」的空行
    expect(
      parseMatrix(`{'columns': ['研究问题'], 'rows': [{'task_id': 1}], 'missing': []}`),
    ).toBeNull()
  })

  it('列名与后端扁平行两种形状都认，数组值（术语）原样留给 MatrixTable 用顿号连', () => {
    const fromCells = parseMatrix(
      `{'topic': '手性', 'columns': ['研究问题', '术语'], 'rows': [{'filename': 'b.pdf', 'cells': {'研究问题': '另一个问题', '术语': ['甲', '乙']}}], 'missing': []}`,
    )
    expect(fromCells.rows[0]).toEqual({
      filename: 'b.pdf',
      cells: { 研究问题: '另一个问题', 术语: ['甲', '乙'] },
    })
  })
})

describe('agentResult.js 的解析方式', () => {
  it('不 eval、不 JSON.parse（excerpt 不是 JSON，也不该被执行）', () => {
    const code = codeWithoutComments('src/agentResult.js')
    expect(code).not.toMatch(/\beval\s*\(/)
    expect(code).not.toContain('JSON.parse')
  })
})

describe('AgentChat 里的矩阵表格', () => {
  beforeEach(() => {
    agentMessages.value.length = 0
  })

  /** 造一轮回答：工具调用 + 返回（excerpt 原样给）。 */
  function pushMatrixTurn(excerpt, name = 'build_matrix', extra = {}) {
    agentMessages.value.push({
      role: 'assistant',
      text: '排好了。',
      steps: [
        { kind: 'tool_call', name, args: { topic: '手性' } },
        { kind: 'tool_result', name, ok: true, excerpt },
      ],
      sources: [],
      dropped: [],
      revisions: [],
      done: false,
      ...extra,
    })
  }

  it('「返回 build_matrix」那一行下面渲染出表格（不是把 repr 再贴一遍）', async () => {
    const wrapper = mount(AgentChat, { props: { scope: { task_id: 41 } } })
    await flushPromises()
    pushMatrixTurn(REAL_MATRIX)
    await flushPromises()

    const cards = wrapper.findAll('.agent-matrix')
    expect(cards).toHaveLength(1)
    expect(cards[0].find('.mx-table').exists()).toBe(true)
    // 宽表靠 MatrixTable 自己的横向滚动条
    expect(cards[0].find('.mx-scroll').exists()).toBe(true)

    // 表格是**那一行**的一部分，不是另起一坨
    const line = cards[0].element.closest('li')
    expect(line).toBeTruthy()
    expect(line.textContent).toContain('返回')
    expect(line.textContent).toContain('build_matrix')

    // 表头来自 columns（「文献」只出现一次：第一列）
    const headers = cards[0].findAll('thead th').map((th) => th.text())
    expect(headers[0]).toBe('文献')
    expect(cards[0].findAll('thead .mx-col').map((th) => th.text())).toEqual(TABLE_COLUMNS)

    // 行内容真的来自解析结果
    const row = cards[0].find('.mx-row')
    expect(row.find('.mx-file').text()).toBe('手性-化学.pdf')
    expect(row.text()).toContain('数值模拟')
  })

  it('空表（rows: []）不渲染——不把"这几篇都没有导读"错当成结论', async () => {
    const wrapper = mount(AgentChat, { props: { scope: {} } })
    await flushPromises()
    pushMatrixTurn(REAL_MATRIX_MISSING)
    await flushPromises()

    expect(wrapper.findAll('.agent-matrix')).toHaveLength(0)
    expect(wrapper.find('.mx-table').exists()).toBe(false)
  })

  it('截断的 excerpt 不渲染表格（那一行保持原样）', async () => {
    const wrapper = mount(AgentChat, { props: { scope: {} } })
    await flushPromises()
    pushMatrixTurn(TRUNCATED)
    await flushPromises()

    expect(wrapper.findAll('.agent-matrix')).toHaveLength(0)
  })

  it('工具名不像 matrix（如 run_check）时，即使 excerpt 长得像矩阵也不渲染', async () => {
    const wrapper = mount(AgentChat, { props: { scope: {} } })
    await flushPromises()
    pushMatrixTurn(REAL_MATRIX, 'run_check')
    await flushPromises()

    expect(wrapper.findAll('.agent-matrix')).toHaveLength(0)
  })

  it('收尾后过程收起、展开仍能看到表格；轨迹页同样能看', async () => {
    const wrapper = mount(AgentChat, { props: { scope: {} } })
    await flushPromises()
    pushMatrixTurn(REAL_MATRIX, 'build_matrix', { done: true })
    await flushPromises()

    // 收尾后过程默认收起
    expect(wrapper.findAll('.agent-matrix')).toHaveLength(0)
    await wrapper.find('.agent-trace-head').trigger('click')
    expect(wrapper.findAll('.agent-matrix')).toHaveLength(1)

    // 轨迹页也带表格（不是只有对话流里能看懂）
    const traceBtn = wrapper.findAll('.agent-views button').find((b) => b.text().includes('轨迹'))
    expect(traceBtn).toBeTruthy()
    await traceBtn.trigger('click')
    expect(wrapper.find('.agent-trace-view').exists()).toBe(true)
    expect(wrapper.findAll('.agent-matrix')).toHaveLength(1)
  })

  it('折叠与滚动：卡片最多 320px 高、可滚动；表格走组件渲染，不用 v-html', () => {
    const rule = chatSource.slice(chatSource.indexOf('.agent-matrix {'))
    expect(rule.slice(0, 220)).toContain('max-height: 320px')
    expect(rule.slice(0, 220)).toContain('overflow: auto')

    // 模板里不许用 v-html（注释里提到"不用 v-html"不算）
    expect(chatSource).not.toMatch(/v-html\s*=/)
    expect(chatSource).toContain("import MatrixTable from './MatrixTable.vue'")
    expect(chatSource).toContain('<MatrixTable :data="matrixOf(step)" />')
    // 三处过程列表（生成中 / 收尾后展开 / 轨迹页）都挂了表格
    expect(chatSource.match(/class="agent-matrix"/g)).toHaveLength(3)
  })
})
