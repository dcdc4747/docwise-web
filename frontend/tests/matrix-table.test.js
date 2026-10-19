/**
 * 文献对比矩阵（`MatrixTable.vue`）的用例。
 *
 * 这个组件是纯展示：数据从 `data` prop 进来，不请求接口、不碰 store。
 * 所以这里只钉"给定数据长什么样"和"缺数据时怎么表现"，不 mock 任何接口。
 */

import { readFileSync } from 'node:fs'
import path from 'node:path'

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MatrixTable, { rowToText } from '../src/components/MatrixTable.vue'

/** 组件源码：用来钉"破折号走 --muted"这类只存在于样式里的口径。 */
const componentSource = readFileSync(
  path.resolve(process.cwd(), 'src/components/MatrixTable.vue'),
  'utf8',
)

/** `build_matrix` 的标准返回。 */
const matrix = {
  topic: '手性',
  columns: ['研究问题', '方法', '结论', '术语', '可引用句'],
  rows: [
    {
      filename: 'a.pdf',
      cells: {
        研究问题: '这篇论文研究手性分子在旋转动力学中的时间结构',
        方法: '分子动力学模拟',
        结论: '手性会带来可观测的时间结构',
        术语: '手性时间结构',
        可引用句: '手性并不是静态标签，而是随时间演化的结构。',
      },
      missing: [],
    },
    {
      filename: 'b.pdf',
      cells: { 研究问题: '另一个问题', 方法: '实验测量' },
      missing: ['结论', '术语', '可引用句'],
    },
  ],
  missing: ['c.pdf', 'd.pdf'],
}

/** 默认列在组件与后端之间是同一份口径。 */
const DEFAULT_COLUMNS = ['研究问题', '方法', '结论', '术语', '可引用句']

/** 把剪贴板换成可控实现（happy-dom 里 `clipboard` 只是原型上的 getter）。 */
function stubClipboard(writeText) {
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText },
  })
}

beforeEach(() => {
  stubClipboard(vi.fn(() => Promise.resolve()))
})

describe('MatrixTable 文献对比矩阵', () => {
  it('表头 = columns，第一列固定「文献」，列顺序与数据一致', () => {
    const wrapper = mount(MatrixTable, { props: { data: matrix } })

    const headers = wrapper.findAll('thead th')
    expect(headers[0].text()).toBe('文献')

    // 中间那几列严格按 columns 的顺序，不排序、不补列、不删列
    expect(wrapper.findAll('thead .mx-col').map((th) => th.text())).toEqual(matrix.columns)

    // 最后一列只放行内按钮，表头文字留空
    expect(headers[headers.length - 1].text()).toBe('')
    expect(wrapper.findAll('tbody .mx-row')).toHaveLength(matrix.rows.length)
  })

  it('空数据不崩：没传 data、空对象、rows 为空，都只渲染表头 + 一句空态', () => {
    for (const props of [{}, { data: {} }, { data: { rows: [] } }, { data: null }]) {
      const wrapper = mount(MatrixTable, { props })

      expect(wrapper.find('.mx-table').exists()).toBe(true)
      expect(wrapper.findAll('.mx-row')).toHaveLength(0)
      expect(wrapper.find('.mx-empty').text()).toBe('没有可对比的文献')
      expect(wrapper.find('.mx-missing').exists()).toBe(false)
    }
  })

  it('缺 columns（或 columns 为空的/不是数组）→ 用默认五列', () => {
    for (const data of [{ rows: [] }, { rows: [], columns: [] }, { rows: [], columns: 'oops' }]) {
      const wrapper = mount(MatrixTable, { props: { data } })

      expect(wrapper.findAll('thead .mx-col').map((th) => th.text())).toEqual(DEFAULT_COLUMNS)
    }
  })

  it('超过 60 字折叠：先给前 60 字 + …，点一下变完整，再点变回折叠（aria-expanded 跟着变）', async () => {
    const long = '甲'.repeat(100)
    const wrapper = mount(MatrixTable, {
      props: {
        data: {
          columns: ['研究问题'],
          rows: [{ filename: 'long.pdf', cells: { 研究问题: long } }],
        },
      },
    })

    let toggle = wrapper.find('.mx-cell-toggle')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.text()).toBe(`${'甲'.repeat(60)}…`)
    expect(Array.from(toggle.text())).toHaveLength(61)

    await toggle.trigger('click')
    toggle = wrapper.find('.mx-cell-toggle')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(toggle.text()).toBe(long)

    await toggle.trigger('click')
    toggle = wrapper.find('.mx-cell-toggle')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.text()).toBe(`${'甲'.repeat(60)}…`)
  })

  it('正好 60 字不折叠（阈值是"超过"60 字）', () => {
    const exact = '乙'.repeat(60)
    const wrapper = mount(MatrixTable, {
      props: {
        data: { columns: ['研究问题'], rows: [{ filename: 'exact.pdf', cells: { 研究问题: exact } }] },
      },
    })

    expect(wrapper.find('.mx-cell-toggle').exists()).toBe(false)
    expect(wrapper.find('.mx-cell-text').text()).toBe(exact)
  })

  it('空格子显示灰色「—」：不留白、不编内容', () => {
    const wrapper = mount(MatrixTable, {
      props: {
        data: {
          columns: ['研究问题', '方法', '结论'],
          rows: [
            { filename: 'b.pdf', cells: { 研究问题: '', 方法: null } },
            { filename: 'c.pdf', cells: {} },
          ],
        },
      },
    })

    const cells = wrapper.findAll('.mx-row .mx-cell')
    expect(cells).toHaveLength(6)
    for (const cell of cells) {
      expect(cell.text()).toBe('—')
    }
    // 破折号必须走 --muted 的灰，不是正文色
    expect(wrapper.findAll('.mx-row .mx-cell .mx-dash')).toHaveLength(6)
    const dashRule = componentSource.slice(componentSource.indexOf('.mx-dash {'))
    expect(dashRule.slice(0, 120)).toContain('var(--muted')
  })

  it('missing 的文献不占表格行，表格下方单列一行报数量与原因', () => {
    const wrapper = mount(MatrixTable, { props: { data: matrix } })

    expect(wrapper.findAll('.mx-row')).toHaveLength(2)
    const line = wrapper.find('.mx-missing')
    expect(line.exists()).toBe(true)
    expect(line.text()).toBe('另有 2 篇没有导读（不参与对比）')

    // missing 为空时整行不出现（不写"另有 0 篇"）
    const none = mount(MatrixTable, { props: { data: { ...matrix, missing: [] } } })
    expect(none.find('.mx-missing').exists()).toBe(false)
  })

  it('rowToText 输出格式：第一行文件名，之后每列一行「列名：值」，空值写 —', () => {
    expect(rowToText(matrix.rows[0], matrix.columns)).toBe(
      [
        'a.pdf',
        '研究问题：这篇论文研究手性分子在旋转动力学中的时间结构',
        '方法：分子动力学模拟',
        '结论：手性会带来可观测的时间结构',
        '术语：手性时间结构',
        '可引用句：手性并不是静态标签，而是随时间演化的结构。',
      ].join('\n'),
    )

    // 缺列 / 空值：每一列都保留，写「—」而不是消失
    expect(rowToText(matrix.rows[1], matrix.columns)).toBe(
      ['b.pdf', '研究问题：另一个问题', '方法：实验测量', '结论：—', '术语：—', '可引用句：—'].join(
        '\n',
      ),
    )

    // 不传 columns 时用默认五列（与表头同一份口径）
    expect(rowToText({ filename: 'x.pdf', cells: { 结论: '结论在这里' } })).toBe(
      ['x.pdf', '研究问题：—', '方法：—', '结论：结论在这里', '术语：—', '可引用句：—'].join('\n'),
    )

    // 数组值按顿号连起来，不丢条目
    expect(rowToText({ filename: 'y.pdf', cells: { 术语: ['甲', '乙'] } }, ['术语'])).toBe(
      'y.pdf\n术语：甲、乙',
    )
  })

  it('复制失败不静默：整段文本进 aria-live 提示', async () => {
    stubClipboard(() => Promise.reject(new Error('denied')))
    const wrapper = mount(MatrixTable, { props: { data: matrix } })

    await wrapper.find('.mx-copy').trigger('click')
    await flushPromises()

    const live = wrapper.find('.mx-live')
    expect(live.attributes('role')).toBe('status')
    expect(live.attributes('aria-live')).toBe('polite')
    expect(live.classes()).toContain('is-fail')
    expect(live.text()).toContain('复制失败')
    // 失败时把可手动复制的文本原样交出来（不是只说一句"失败了"）
    expect(live.text()).toContain(rowToText(matrix.rows[0], matrix.columns))
  })

  it('复制成功：剪贴板拿到的正是 rowToText 的文本，并给回执；每行一个按钮', async () => {
    const writeText = vi.fn(() => Promise.resolve())
    stubClipboard(writeText)
    const wrapper = mount(MatrixTable, { props: { data: matrix } })

    const buttons = wrapper.findAll('.mx-copy')
    expect(buttons).toHaveLength(matrix.rows.length)
    expect(buttons[1].text()).toBe('复制这一行')

    await buttons[1].trigger('click')
    await flushPromises()

    expect(writeText).toHaveBeenCalledTimes(1)
    expect(writeText).toHaveBeenCalledWith(rowToText(matrix.rows[1], matrix.columns))
    expect(wrapper.find('.mx-live').text()).toContain('已复制')
    expect(wrapper.find('.mx-live').classes()).not.toContain('is-fail')
  })
})
