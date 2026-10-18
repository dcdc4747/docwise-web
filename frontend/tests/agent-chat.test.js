/**
 * Agent 面板（读懂侧）——两条底线：
 * 1. 没配模型时要**先说得出来**（不能让用户打完字才发现用不了）；
 * 2. 轨迹里"它查了什么"只算工具调用，**收尾那条 `final_result` 不算查**。
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
      providers: [
        { id: 'deepseek', name: 'DeepSeek', base_url: 'https://api.deepseek.com/v1' },
      ],
      tier_models: { deepseek: { standard: 'deepseek-chat' } },
      model: '',
      tier: 'standard',
    }),
  })),
}))

import AgentChat from '../src/components/AgentChat.vue'
import WriteView from '../src/views/WriteView.vue'
import {
  agentMessages,
  newThread,
  setScene,
  threadOf,
  toolStepsOf,
} from '../src/stores/useAgent'
import { body as writeBody, resetWrite } from '../src/stores/useWrite'

describe('AgentChat（读懂侧）', () => {
  beforeEach(() => {
    agentMessages.value.length = 0
  })

  // 剪贴板是全局对象：每个用例自己 stub，跑完必须还回去（别污染后面的用例）
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('没配模型时，**输入框那一行**直接说「未配置模型」（不是等打完字才 500）', async () => {
    const wrapper = mount(AgentChat, { props: { scope: { task_id: 41 } } })
    await flushPromises()
    // ⚠️ 2026-10-18：模型选择从"顶部"搬到"输入框那一行"（与主流 agent 工具一致），
    // 所以断言的目标从 `.agent-model` 改成输入行里的那个按钮。
    const modelBtn = wrapper.find('.agent-composer .agent-model-btn')
    expect(modelBtn.exists()).toBe(true)
    expect(modelBtn.text()).toContain('未配置模型')
    expect(modelBtn.classes()).toContain('warn')
  })

  it('点输入行里的模型按钮 → **只弹模型列表**（自定义配置在设置里）', async () => {
    const wrapper = mount(AgentChat, { props: { scope: {} } })
    await flushPromises()
    expect(wrapper.find('.agent-models').exists()).toBe(false)
    await wrapper.find('.agent-model-btn').trigger('click')
    expect(wrapper.find('.agent-models').exists()).toBe(true)
    expect(wrapper.find('.agent-models-more').text()).toContain('更多设置')
    // ⚠️ 这里**不该**出现接口地址 / API Key 这些字段——它们属于设置弹窗
    expect(wrapper.find('.agent-models input[type=password]').exists()).toBe(false)
  })

  it('空态给一句能照做的示例问题', async () => {
    const wrapper = mount(AgentChat, { props: { scope: {} } })
    await flushPromises()
    expect(wrapper.find('.agent-empty').text()).toContain('我库里有哪些讲手性的文献')
  })


  it('过程只在生成期间显示：完成后收起成一行，点开才看', async () => {
    const wrapper = mount(AgentChat, { props: { scope: {} } })
    await flushPromises()
    const turn = {
      role: 'assistant',
      text: '库里有 2 篇',
      thinking: '先想一下要查什么…',
      steps: [
        { kind: 'tool_call', name: 'search_library', args: { query: '手性' } },
        { kind: 'tool_result', name: 'search_library', ok: true, excerpt: 'p0_b3' },
      ],
      sources: ['p0_b3'],
      dropped: [],
      usage: { tool_calls: 1 },
      error: '',
      done: false,
    }
    agentMessages.value.push(turn)
    await flushPromises()

    // 生成中：过程（思考 + 工具）可见
    expect(wrapper.find('.agent-process').exists()).toBe(true)
    expect(wrapper.find('.agent-thinking').text()).toContain('先想一下')
    // 收尾前没有"过程 N 步"那行按钮
    expect(wrapper.find('.agent-trace-head').exists()).toBe(false)

    // 收尾：过程收起，只剩正文 + 一行可展开的入口。
    // ⚠️ 要**替换整条**而不是改原始对象：本地拿到的 	urn 不是代理，
    // 直接改它不会触发重渲染（真实路径里是 store 内部改的，所以没这问题）。
    agentMessages.value.splice(0, 1, { ...turn, done: true })
    await flushPromises()
    expect(wrapper.find('.agent-process').exists()).toBe(false)
    // 模板里插值之间会有换行，比对前先压空白
    const headText = wrapper.find('.agent-trace-head').text().replace(/\s+/g, ' ')
    expect(headText).toContain('过程 2 步')
    expect(wrapper.find('.agent-bubble.answer').text()).toContain('库里有 2 篇')

    // 点开能重新看到过程
    await wrapper.find('.agent-trace-head').trigger('click')
    expect(wrapper.find('.agent-process').exists()).toBe(true)
  })


  it('轨迹页不显示输入框（没人会跟轨迹说话）', async () => {
    const wrapper = mount(AgentChat, { props: { scope: {} } })
    await flushPromises()
    agentMessages.value.push({
      role: 'user',
      text: '这篇讲了什么',
    })
    agentMessages.value.push({
      role: 'assistant',
      text: '讲了稀疏线性系统',
      steps: [{ kind: 'tool_call', name: 'read_blocks', args: { task_id: 46 } }],
      sources: [],
      dropped: [],
      done: true,
    })
    await flushPromises()
    expect(wrapper.find('.agent-composer').exists()).toBe(true)
    const traceBtn = wrapper.findAll('.agent-views button').find((b) => b.text().includes('轨迹'))
    expect(traceBtn).toBeTruthy()
    await traceBtn.trigger('click')
    expect(wrapper.find('.agent-composer').exists()).toBe(false)
    expect(wrapper.find('.agent-trace-view').exists()).toBe(true)
  })


  it('回答带元信息行（模型 / 用时 / 步数），失败时给「重试」', async () => {
    const wrapper = mount(AgentChat, { props: { scope: { task_id: 46 } } })
    await flushPromises()
    agentMessages.value.push({ role: 'user', text: '这篇讲了什么' })
    agentMessages.value.push({
      role: 'assistant',
      text: '讲了稀疏线性系统',
      steps: [
        { kind: 'tool_call', name: 'read_blocks', args: {} },
        { kind: 'tool_result', name: 'read_blocks', ok: true, excerpt: '' },
      ],
      sources: [],
      dropped: [],
      done: true,
      elapsedMs: 8600,
      model: 'deepseek-chat',
      question: '这篇讲了什么',
    })
    agentMessages.value.push({
      role: 'assistant',
      text: '',
      steps: [],
      sources: [],
      dropped: [],
      done: true,
      error: '模型服务限流了，等一会再试。',
      question: '再问一次',
    })
    await flushPromises()

    const meta = wrapper.find('.agent-meta').text()
    expect(meta).toContain('deepseek-chat')
    expect(meta).toContain('8.6s')
    expect(meta).toContain('2 步')

    const err = wrapper.find('.agent-error')
    expect(err.exists()).toBe(true)
    expect(err.text()).toContain('限流')
    expect(err.find('button').text()).toBe('重试')
  })


  it('改写建议卡：原句划掉、改后高亮，点「采用」把这条建议抛给页面', async () => {
    const wrapper = mount(AgentChat, { props: { scope: { draft_id: 3 } } })
    await flushPromises()
    agentMessages.value.push({
      role: 'assistant',
      text: '这句可以更贴学科用语。',
      steps: [],
      sources: [],
      dropped: [],
      done: true,
      revisions: [
        {
          original: '手性可以分成时间与空间两部分。',
          revised: '手性可分解为时间与空间两个维度。',
          reason: '更贴学科用语',
        },
      ],
      notes: ['剔掉 1 条对不上原文的建议'],
    })
    await flushPromises()

    expect(wrapper.find('.agent-rev-orig').text()).toContain('时间与空间两部分')
    expect(wrapper.find('.agent-rev-new').text()).toContain('两个维度')
    expect(wrapper.find('.agent-notes').text()).toContain('剔掉 1 条')

    await wrapper.find('.agent-rev-foot .agent-rev-apply').trigger('click')
    const emitted = wrapper.emitted('apply-revision')
    expect(emitted).toBeTruthy()
    expect(emitted[0][0].revised).toContain('两个维度')
  })

  // ============================================================ 批量 / 忽略 / 状态标记
  // 说明：这三条只管「组件有没有把决定交回页面」。**正文到底改没改、能不能撤销**由
  // WriteView 的 `applyRevision` 负责（它同步回报结果，卡片据此显示已采用 / 没采用）。

  /** 塞一轮带 `revisions` 的助手消息（`done: true`，建议卡才会出）。 */
  function pushRevisions(revisions) {
    agentMessages.value.push({
      role: 'assistant',
      text: '这几句可以更贴学科用语。',
      steps: [],
      sources: [],
      dropped: [],
      done: true,
      revisions,
    })
  }

  const REVS = [
    { original: '甲句。', revised: '甲句（改）。', reason: '更像学科用语' },
    { original: '乙句。', revised: '乙句（改）。', reason: '去掉冗词' },
  ]

  it('批量采用：顶部「全部采用（N）」对每条待处理建议都发 `apply-revision`', async () => {
    const wrapper = mount(AgentChat, { props: { scope: { draft_id: 3 } } })
    await flushPromises()
    pushRevisions(REVS)
    await flushPromises()

    const all = wrapper.find('.agent-revs-all')
    expect(all.exists()).toBe(true)
    expect(all.text()).toContain('全部采用（2）')
    // 旁边还有「忽略全部」（同一行操作）
    expect(wrapper.find('.agent-revs-ignore').text()).toContain('忽略全部')

    await all.trigger('click')

    const emitted = wrapper.emitted('apply-revision')
    expect(emitted).toHaveLength(2)
    expect(emitted.map((call) => call[0].original)).toEqual(['甲句。', '乙句。'])
    // 批量信息挂在第二个参数上：页面靠 `last` 收尾（汇总提示 + 整批撤销）
    expect(emitted[0][1].batch).toEqual({ total: 2, index: 0, last: false })
    expect(emitted[1][1].batch).toEqual({ total: 2, index: 1, last: true })

    // 批量之后整组都标成已采用，顶部按钮没有可再采用的了
    expect(wrapper.findAll('.agent-rev.is-applied')).toHaveLength(2)
    expect(wrapper.find('.agent-revs-all').attributes('disabled')).toBeDefined()
  })

  it('已采用：左侧标绿、状态写「已采用」，两个按钮都禁用（不能重复采用）', async () => {
    const wrapper = mount(AgentChat, { props: { scope: { draft_id: 3 } } })
    await flushPromises()
    pushRevisions([REVS[0]])
    await flushPromises()

    const card = wrapper.find('.agent-rev')
    expect(card.classes()).not.toContain('is-applied')

    await card.find('.agent-rev-apply').trigger('click')
    expect(card.classes()).toContain('is-applied')
    expect(card.find('.agent-rev-state').text()).toBe('已采用')
    expect(card.find('.agent-rev-apply').attributes('disabled')).toBeDefined()
    expect(card.find('.agent-rev-ignore').attributes('disabled')).toBeDefined()

    // 禁用之后再点一次也不该多发一条（这条建议已经处置过了）
    await card.find('.agent-rev-apply').trigger('click')
    expect(wrapper.emitted('apply-revision')).toHaveLength(1)
  })

  it('忽略：标成已忽略，之后「全部采用」不再带上它', async () => {
    const wrapper = mount(AgentChat, { props: { scope: { draft_id: 3 } } })
    await flushPromises()
    pushRevisions([...REVS, { original: '丙句。', revised: '丙句（改）。', reason: '更短' }])
    await flushPromises()

    const cards = wrapper.findAll('.agent-rev')
    await cards[1].find('.agent-rev-ignore').trigger('click')
    expect(cards[1].classes()).toContain('is-ignored')
    expect(cards[1].find('.agent-rev-state').text()).toBe('已忽略')
    expect(wrapper.find('.agent-revs-all').text()).toContain('全部采用（2）')

    await wrapper.find('.agent-revs-all').trigger('click')
    const emitted = wrapper.emitted('apply-revision')
    expect(emitted).toHaveLength(2)
    expect(emitted.map((call) => call[0].original)).toEqual(['甲句。', '丙句。'])
    // 被忽略的那条保持灰的，没有被批量采用改写成「已采用」
    expect(cards[1].classes()).toContain('is-ignored')
    expect(wrapper.findAll('.agent-rev.is-applied')).toHaveLength(2)
  })

  it('轨迹只算工具调用：`final_result` 那条被剔掉', () => {
    const turn = {
      steps: [
        { kind: 'tool_call', name: 'search_library', args: { query: '手性' } },
        { kind: 'tool_result', name: 'search_library', ok: true, excerpt: 'p0_b3' },
        { kind: 'tool_call', name: 'final_result', args: {} },
        { kind: 'tool_result', name: 'final_result', ok: true, excerpt: 'ok' },
      ],
    }
    const steps = toolStepsOf(turn)
    expect(steps).toHaveLength(2)
    expect(steps.every((s) => s.name === 'search_library')).toBe(true)
  })

  // ============================================================ 段落级建议：折叠 / 复制
  // 后端即将支持「一段话级别」的改写建议（`original` 是一整段、含多句），
  // 卡片上不能把整段铺出来，也不能让复制失败静默。

  /** 一整段原文（> 120 字，既是长建议、也超过 3 行折叠阈值）。 */
  const LONG_ORIGINAL =
    '手性可以分成时间与空间两部分，这一句只是开头。' +
    '时间反演对称性在宏观尺度上怎么表现，取决于实验装置与测量口径，' +
    '这一段里还交代了两个可观测量的定义与取值范围。' +
    '空间反演对称性改变分子轨道的排布，进而影响反应路径的选择。' +
    '最后一句是整段的收尾，只有点开「展开全文」之后才应该看得见。'

  it('段落级长 original：默认折到 3 行，点「展开全文」才显示整段', async () => {
    const wrapper = mount(AgentChat, { props: { scope: { draft_id: 3 } } })
    await flushPromises()
    pushRevisions([
      { original: LONG_ORIGINAL, revised: '手性可分解为时间与空间两个维度。', reason: '整段更贴学科用语' },
    ])
    await flushPromises()

    const card = wrapper.find('.agent-rev')
    const orig = card.find('.agent-rev-orig')
    // 超过 120 字 → 挂上降噪用的 is-long
    expect(card.classes()).toContain('is-long')
    expect(orig.classes()).toContain('is-clamped')
    // 折起时是截断后的文本：收尾那句一定看不到
    expect(orig.text()).not.toContain('最后一句是整段的收尾')
    expect(orig.text().endsWith('…')).toBe(true)

    const expand = card.find('.agent-rev-expand')
    expect(expand.exists()).toBe(true)
    expect(expand.text()).toContain('展开')

    await expand.trigger('click')
    // 展开后：全文都在，3 行钳撤掉，按钮变成「收起」
    expect(orig.text()).toBe(LONG_ORIGINAL)
    expect(orig.classes()).not.toContain('is-clamped')
    expect(card.find('.agent-rev-expand').text()).toBe('收起')
  })

  it('「复制改后文本」把这条的 revised 写进剪贴板（内容逐字一致）', async () => {
    const writeText = vi.fn(async () => {})
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const wrapper = mount(AgentChat, { props: { scope: { draft_id: 3 } } })
    await flushPromises()
    pushRevisions([REVS[0]])
    await flushPromises()

    await wrapper.find('.agent-rev-foot .agent-rev-copy').trigger('click')
    await flushPromises()

    expect(writeText).toHaveBeenCalledTimes(1)
    expect(writeText).toHaveBeenCalledWith('甲句（改）。')
    expect(wrapper.find('.agent-rev-hint').text()).toContain('已复制')
  })

  it('「复制全部改后文本」只拼未忽略的条目（换行分隔）', async () => {
    const writeText = vi.fn(async () => {})
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const wrapper = mount(AgentChat, { props: { scope: { draft_id: 3 } } })
    await flushPromises()
    pushRevisions([
      ...REVS,
      { original: '丙句。', revised: '丙句（改）。', reason: '更短' },
    ])
    await flushPromises()

    // 忽略第二条（乙），它就不该出现在「复制全部」里
    await wrapper.findAll('.agent-rev')[1].find('.agent-rev-ignore').trigger('click')
    expect(wrapper.find('.agent-revs-copy').text()).toContain('复制全部改后文本')
    await wrapper.find('.agent-revs-copy').trigger('click')
    await flushPromises()

    expect(writeText).toHaveBeenCalledTimes(1)
    expect(writeText).toHaveBeenCalledWith('甲句（改）。\n丙句（改）。')
    expect(wrapper.find('.agent-revs-hint').text()).toContain('2 条')
  })

  it('剪贴板不给用：兜底提示「复制失败，请手动选中」（不静默）', async () => {
    const writeText = vi.fn(async () => {
      throw new Error('denied')
    })
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const wrapper = mount(AgentChat, { props: { scope: { draft_id: 3 } } })
    await flushPromises()
    pushRevisions([REVS[0]])
    await flushPromises()

    await wrapper.find('.agent-rev-foot .agent-rev-copy').trigger('click')
    await flushPromises()

    expect(writeText).toHaveBeenCalled()
    expect(wrapper.find('.agent-rev-hint').text()).toBe('复制失败，请手动选中')
    // 失败也不该把建议标成已采用 / 已忽略（复制与处置无关）
    expect(wrapper.find('.agent-rev').classes()).not.toContain('is-applied')
  })

  // ============================================================ 写作页：段落级建议真的能落进正文
  // 后端 `verify_revisions` 已按「归一化换行」比对；前端定位必须同口径，
  // 否则后端留下的建议在页面上会"原文没找到"（假失败），一个字都不敢改。

  it('写作页：段落级建议在 CRLF 稿子里能逐字替换（多句 + 换行风格不变）', async () => {
    resetWrite()
    const wrapper = mount(WriteView)
    await flushPromises()
    // 助手默认在「提纲」，切到「对话」才挂 AgentChat
    const chatTab = wrapper.findAll('.wr-helper .tabs button').find((b) => b.text() === '对话')
    await chatTab.trigger('click')
    await flushPromises()

    // 后端比对的是「归一化换行」后的正文（模型可能给 \r\n，稿子也可能是）
    const apply = (rev) => {
      let outcome = null
      wrapper.findComponent(AgentChat).vm.$emit('apply-revision', rev, {
        report: (ok) => {
          outcome = ok
        },
      })
      return outcome
    }

    // ① 一整段（多句）能被替换，插回去的文本跟随稿子的 CRLF
    writeBody.value = '开头。\r\n第一句。\r\n第二句。\r\n结尾。'
    expect(apply({ original: '第一句。\r\n第二句。', revised: '改后第一句。\n改后第二句。' })).toBe(true)
    expect(writeBody.value).toBe('开头。\r\n改后第一句。\r\n改后第二句。\r\n结尾。')

    // ② 真的对不上：一个字都不改，如实回报 false（不模糊替换）
    const before = writeBody.value
    expect(apply({ original: '稿子里没有这句。', revised: '改成这样。' })).toBe(false)
    expect(writeBody.value).toBe(before)

    wrapper.unmount()
    resetWrite()
  })

  it('每个场景一条独立对话：读懂与写作不串，切回来还在', async () => {
    setScene('read_ask')
    newThread('read_ask')
    newThread('write_compose')
    threadOf('read_ask').messages.push({ role: 'user', text: '读懂的问题' })
    threadOf('write_compose').messages.push({ role: 'user', text: '写作的问题' })

    // 当前在读懂：只看到读懂那条
    expect(agentMessages.value.map((m) => m.text)).toEqual(['读懂的问题'])

    setScene('write_compose')
    await flushPromises()
    expect(agentMessages.value.map((m) => m.text)).toEqual(['写作的问题'])

    // 切回读懂：原来那条还在（不是被清空）
    setScene('read_ask')
    await flushPromises()
    expect(agentMessages.value.map((m) => m.text)).toEqual(['读懂的问题'])
  })

  it('「新对话」只清当前场景，另一个场景的历史不动', async () => {
    setScene('read_ask')
    newThread('read_ask')
    newThread('write_compose')
    threadOf('read_ask').messages.push({ role: 'user', text: 'A' })
    threadOf('write_compose').messages.push({ role: 'user', text: 'B' })

    newThread() // 当前是 read_ask
    expect(agentMessages.value).toHaveLength(0)
    expect(threadOf('write_compose').messages.map((m) => m.text)).toEqual(['B'])
  })

  it('头部有「新对话」按钮：点一下清空当前对话', async () => {
    setScene('read_ask')
    newThread('read_ask')
    const wrapper = mount(AgentChat, { props: { scope: {} } })
    await flushPromises()
    agentMessages.value.push({ role: 'user', text: '旧问题' })
    await flushPromises()

    const btn = wrapper.find('.agent-new-thread')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    await flushPromises()
    expect(agentMessages.value).toHaveLength(0)
    expect(wrapper.find('.agent-new-thread').exists()).toBe(false)
  })
})
