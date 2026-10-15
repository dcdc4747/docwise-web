/**
 * 起草页（M1 起草：#/write 三栏）的用例。
 *
 * 这一包盯的是三件"做错了没人看得出来"的事：
 * ① ⭐ **点 `[1]` 回原文**：引文 → `material_id` → 素材的 `task_id`/`block_id` → 阅读区高亮那一句。
 *    这条链路走错一段，界面看起来一切正常，只是**永远跳不过去**；
 * ② **源文献已删不许做成假链接**：`[n]` 必须是灰的、不可点，并写清为什么；
 * ③ ⚠️ **正文一个字都不替用户生成**：这一页不许出现任何"生成 / 续写"入口——
 *    这条是作品红线，所以用一条**结构性断言**钉住（改了会红，而不是靠人眼）。
 */

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.vue'
import WriteView from '../src/views/WriteView.vue'
import { clearTasks } from '../src/stores/useTasks'
import { toast } from '../src/stores/useUi'
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

const TASK = {
  id: 42,
  filename: 'EBSCO_05-mono.pdf',
  status: 'completed',
  progress: 1,
  tier: 'medium',
  created_at: '2026-10-14T02:00:00Z',
  stage: null,
  eta_seconds: null,
  elapsed_seconds: 12,
  finished_at: '2026-10-14T02:10:00Z',
  last_read_page: null,
  native: false,
}

const TASK_DETAIL = {
  ...TASK,
  blocks: [
    {
      block_id: 'p2_b7',
      text: '读者信任一个答案，取决于能否跳回它出处的那句话。',
      translated: '（译文）读者信任一个答案……',
      status: 'success',
      error: null,
    },
    { block_id: 'p0_b0', text: 'first block', translated: '第一块', status: 'success', error: null },
  ],
  files_ready: { mono: true, dual: true },
  understanding_status: 'ready',
  queue_position: null,
  engine_progress: null,
}

const MATERIAL = {
  id: 1,
  text_quote: '读者信任一个答案，取决于能否跳回它出处的那句话。',
  translated_quote: '（译文）读者信任一个答案……',
  page: 3,
  source_name: 'EBSCO_05-mono.pdf',
  note: '选题依据',
  task_id: 42,
  block_id: 'p2_b7',
  deleted_at: null,
  created_at: '2026-10-14T02:00:00Z',
}

/** 源文献已删的素材：`task_id` 为 null（契约 §2.6）——回不了原文，但快照还在。 */
const DEAD_MATERIAL = {
  id: 2,
  text_quote: '（这条素材的源文献已被删除）',
  translated_quote: null,
  page: 11,
  source_name: '已删除的文献.pdf',
  note: null,
  task_id: null,
  block_id: null,
  deleted_at: null,
  created_at: '2026-10-14T02:00:00Z',
}

const CITATION = {
  id: 1,
  draft_id: 1,
  material_id: 1,
  order: 1,
  csl_json: {
    id: 'material-1',
    type: 'article-journal',
    title: 'EBSCO_05-mono.pdf',
    page: '3',
  },
  anchor: { block_id: 'p2_b7', offset: 0 },
}

const DEAD_CITATION = { ...CITATION, id: 2, material_id: 2, order: 2, anchor: { block_id: null, offset: 4 } }

function draftFixture(overrides = {}) {
  return {
    id: 1,
    title: '开题报告',
    body_md: '# 开题报告\n\n出处的意义 [1]。\n',
    template_id: null,
    updated_at: '2026-10-14T02:00:00Z',
    citations: [CITATION],
    ...overrides,
  }
}

function jsonOf(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

/**
 * 起草页要的那几个端点的假后端（**含真实的行为**：POST 会真的往列表里加）。
 * `calls` 记下每一次请求，用例靠它断言"到底打没打、带了什么"。
 */
function stubWriteFetch(options = {}) {
  const state = {
    drafts: options.drafts ? [...options.drafts] : [],
    materials: options.materials ? [...options.materials] : [],
    tasks: options.tasks || [TASK],
    detail: options.detail || TASK_DETAIL,
    nextDraftId: 90,
    nextCitationId: 50,
    failDrafts: Boolean(options.failDrafts),
    failMaterials: Boolean(options.failMaterials),
  }
  const calls = []
  const impl = vi.fn(async (input, init = {}) => {
    const url = typeof input === 'string' ? input : String(input?.url ?? input)
    const method = (init.method || 'GET').toUpperCase()
    const body = init.body ? JSON.parse(init.body) : null
    calls.push({ method, url, body })

    if (url.includes('/api/health')) return jsonOf(HEALTH)
    if (url.includes('/api/auth/me')) return jsonOf(USER)
    if (/\/files\/(mono|dual)/.test(url)) {
      return { ok: true, status: 200, arrayBuffer: async () => new ArrayBuffer(8) }
    }
    if (url.includes('/api/materials')) {
      if (state.failMaterials) return jsonOf({ detail: '素材接口还没上线' }, 404)
      return jsonOf({ items: state.materials })
    }
    if (url.includes('/api/drafts')) {
      if (state.failDrafts && method === 'GET') return jsonOf({ detail: '起草接口还没上线' }, 404)
      const citationMatch = /\/api\/drafts\/(\d+)\/citations/.exec(url)
      if (citationMatch && method === 'POST') {
        const material = state.materials.find((item) => item.id === body.material_id)
        if (!material) return jsonOf({ detail: '素材不存在' }, 404)
        const order = state.drafts.flatMap((d) => d.citations || []).length + 1
        const created = {
          id: state.nextCitationId++,
          draft_id: Number(citationMatch[1]),
          material_id: material.id,
          order,
          csl_json: { id: `material-${material.id}`, title: material.source_name, page: String(material.page) },
          anchor: body.anchor || { block_id: null, offset: 0 },
        }
        const host = state.drafts.find((d) => d.id === Number(citationMatch[1]))
        if (host) host.citations = [...(host.citations || []), created]
        return jsonOf(created, 201)
      }
      if (citationMatch && method === 'DELETE') {
        const host = state.drafts.find((d) => d.id === Number(citationMatch[1]))
        if (host) host.citations = []
        return jsonOf({ ok: true })
      }
      const idMatch = /\/api\/drafts\/(\d+)$/.exec(url)
      if (idMatch && method === 'PATCH') {
        const host = state.drafts.find((d) => d.id === Number(idMatch[1]))
        if (!host) return jsonOf({ detail: '草稿不存在' }, 404)
        if (body.title !== undefined) host.title = body.title
        if (body.body_md !== undefined) host.body_md = body.body_md
        if (body.template_id !== undefined) host.template_id = body.template_id
        host.updated_at = '2026-10-14T03:00:00Z'
        return jsonOf({ ...host })
      }
      if (method === 'POST') {
        const created = {
          id: state.nextDraftId++,
          title: body.title,
          body_md: '',
          template_id: body.template_id ?? null,
          updated_at: '2026-10-14T03:00:00Z',
          citations: [],
        }
        state.drafts = [created, ...state.drafts]
        return jsonOf(created, 201)
      }
      return jsonOf({ items: state.drafts })
    }
    if (/\/api\/tasks\/\d+\/?$/.test(url)) return jsonOf(state.detail)
    if (url.includes('/api/tasks')) return jsonOf(state.tasks)
    if (url.includes('/reading-position')) return jsonOf({ last_read_page: null })
    return jsonOf({})
  })
  return { impl, calls, state }
}

function mountWrite() {
  return mount(WriteView, { attachTo: document.body })
}

/** happy-dom 里改视口宽度：改 innerWidth 再发 resize，触发外壳的窄屏判断。 */
function setViewportWidth(width) {
  Object.defineProperty(window, 'innerWidth', { value: width, configurable: true, writable: true })
  window.dispatchEvent(new Event('resize'))
}

beforeEach(() => {
  localStorage.clear()
  window.history.replaceState(null, '', '#/')
  setViewportWidth(1440)
  globalThis.fetch = stubWriteFetch().impl
  resetWrite()
  clearTasks()
})

afterEach(() => {
  vi.restoreAllMocks()
  resetWrite()
  clearTasks()
  document.body.innerHTML = ''
})

describe('起草页：三栏骨架与红线', () => {
  it('渲染素材 ｜ 写作 ｜ 助手三栏，且页面上没有源码痕迹', async () => {
    const { impl } = stubWriteFetch({ drafts: [draftFixture()], materials: [MATERIAL] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    expect(wrapper.find('.wr-materials').exists()).toBe(true)
    expect(wrapper.find('.wr-doc').exists()).toBe(true)
    expect(wrapper.find('.wr-helper').exists()).toBe(true)
    // 三栏各有自己的头（素材 · N / 稿件标题 / 三个页签）
    expect(wrapper.find('.wr-materials .wr-colhead').text()).toContain('素材')
    expect(wrapper.findAll('.wr-helper .tabs button').map((b) => b.text())).toEqual([
      '提纲',
      '引用',
      '过程',
    ])

    const text = wrapper.text()
    for (const leak of ['function ', '=>', '{{', 'undefined']) {
      expect(text).not.toContain(leak)
    }
    wrapper.unmount()
  })

  it('⚠️ 红线：这一页不许有"生成正文"的入口（没有生成/续写/AI 写作这类动作）', async () => {
    const { impl } = stubWriteFetch({ drafts: [draftFixture()], materials: [MATERIAL] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    const labels = wrapper.findAll('button').map((b) => b.text())
    expect(labels.length).toBeGreaterThan(4)
    const banned = /生成|续写|润色|改写|一键成文|帮我写|AI\s*写/
    expect(labels.filter((label) => banned.test(label))).toEqual([])
    wrapper.unmount()
  })
})

describe('起草页：起稿四入口', () => {
  it('没有草稿时四个入口都在（空白 / 模板 / 大纲 / 上传自己的模板）', async () => {
    const { impl } = stubWriteFetch({ drafts: [], materials: [] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('先起一份稿')
    expect(text).toContain('空白文字')
    expect(text).toContain('模板…')
    expect(text).toContain('大纲')
    expect(text).toContain('上传自己的模板…')
    wrapper.unmount()
  })

  it('空白文字：POST /api/drafts 不带 template_id，建完就能写', async () => {
    const { impl, calls } = stubWriteFetch({ drafts: [], materials: [] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    await wrapper.findAll('button').find((b) => b.text() === '空白文字').trigger('click')
    await flushPromises()

    const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/api/drafts'))
    expect(post).toBeTruthy()
    expect(post.body.template_id).toBeUndefined()
    expect(wrapper.find('.wr-editor').exists()).toBe(true)
    wrapper.unmount()
  })

  it('模板：选一个内置模板后 POST 带 template_id（本期只记标识、不渲染）', async () => {
    const { impl, calls } = stubWriteFetch({ drafts: [], materials: [] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    await wrapper.findAll('button').find((b) => b.text() === '模板…').trigger('click')
    await flushPromises()
    expect(wrapper.find('.wr-tpl').exists()).toBe(true)

    await wrapper.findAll('.wr-tpl-item')[0].trigger('click')
    await flushPromises()

    const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/api/drafts'))
    expect(post.body.template_id).toBe('tpl-journal')
    // 章节目录只是**清单**，不是预填正文——正文一个字都不替用户写
    expect(wrapper.find('.wr-editor').element.value).toBe('')
    wrapper.unmount()
  })

  it('大纲：起稿时带上 outline 标识，并把助手切到「提纲」', async () => {
    const { impl, calls } = stubWriteFetch({ drafts: [], materials: [] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    await wrapper.findAll('button').find((b) => b.text() === '大纲').trigger('click')
    await flushPromises()

    const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/api/drafts'))
    expect(post.body.template_id).toBe('outline')
    expect(wrapper.find('.wr-helper .tabs button.on').text()).toBe('提纲')
    wrapper.unmount()
  })

  it('模板：**已经有一份稿时**点「模板…」也要出面板（浏览器实测抓出的回归）', async () => {
    const { impl } = stubWriteFetch({ drafts: [draftFixture()], materials: [] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    // 从顶栏「＋ 新建 → 模板…」进（这时编辑器里已经开着一份稿）
    expect(wrapper.find('.wr-editor').exists()).toBe(true)
    await wrapper.findAll('.wr-top button').find((b) => b.text().includes('新建')).trigger('click')
    await flushPromises()
    await wrapper.findAll('.wr-top .menu button').find((b) => b.text().includes('模板')).trigger('click')
    await flushPromises()

    expect(wrapper.find('.wr-tpl').exists()).toBe(true)
    expect(wrapper.findAll('.wr-tpl-item').length).toBe(2)
    wrapper.unmount()
  })

  it('上传自己的模板：.md 读进正文当起点（内容来自用户文件，模板标识记在草稿上）', async () => {
    const { impl, calls } = stubWriteFetch({ drafts: [], materials: [] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    const file = new File(['# 题目\n\n## 一、引言\n'], '我的模板.md', { type: 'text/markdown' })
    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()

    const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/api/drafts'))
    expect(post.body.template_id).toBe('upload:我的模板.md')
    expect(post.body.title).toBe('我的模板')
    const patch = calls.find((c) => c.method === 'PATCH')
    expect(patch.body.body_md).toContain('# 题目')
    wrapper.unmount()
  })

  it('上传自己的模板：.docx 明确拒绝（不假装读到了二进制包）', async () => {
    const { impl, calls } = stubWriteFetch({ drafts: [], materials: [] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    const file = new File(['PK'], '老师给的模板.docx')
    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()

    expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/api/drafts'))).toBe(false)
    // WriteView 是页内组件：toast 由外壳渲染，所以直接断言 store 里的那句话
    expect(toast.value.text).toContain('只读 .md / .txt')
    wrapper.unmount()
  })
})

describe('起草页：素材为空时的两个出口', () => {
  it('素材为空：给「去读懂一篇」+「不读文献，直接写」，且后者真的能起稿', async () => {
    const { impl, calls } = stubWriteFetch({ drafts: [], materials: [] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    expect(wrapper.text()).toContain('去读懂一篇')
    const direct = wrapper.findAll('button').find((b) => b.text() === '不读文献，直接写')
    expect(direct).toBeTruthy()

    await direct.trigger('click')
    await flushPromises()

    const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/api/drafts'))
    expect(post).toBeTruthy()
    expect(wrapper.find('.wr-editor').exists()).toBe(true)
    wrapper.unmount()
  })

  it('素材接口取不到：如实说 + 给重试，**但两个空态出口不能因此消失**（浏览器实测抓出的回归）', async () => {
    const { impl, calls } = stubWriteFetch({ drafts: [], materials: [], failMaterials: true })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    const text = wrapper.text()
    // ① 诚实说 + 为什么 + 出口（重试）
    expect(text).toContain('素材取不到')
    expect(text).toContain('写稿不受影响')
    expect(wrapper.findAll('button').some((b) => b.text() === '重试')).toBe(true)

    // ② 形态 §3.2 的两个出口**必须还在**（第一版写成 v-else-if，接口一挂就全没了）
    expect(text).toContain('去读懂一篇')
    const direct = wrapper.findAll('button').find((b) => b.text() === '不读文献，直接写')
    expect(direct).toBeTruthy()

    // ③ 而且后者仍然真能用（接口挂了也照样能起稿）
    await direct.trigger('click')
    await flushPromises()
    expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/api/drafts'))).toBe(true)
    expect(wrapper.find('.wr-editor').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('起草页：插入引文', () => {
  it('点「插入引文」→ POST citations，正文落下 [1]，引用页签同步出现', async () => {
    const { impl, calls } = stubWriteFetch({
      drafts: [draftFixture({ body_md: '', citations: [] })],
      materials: [MATERIAL],
    })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    await wrapper.findAll('button').find((b) => b.text() === '插入引文').trigger('click')
    await flushPromises()

    const post = calls.find((c) => c.method === 'POST' && c.url.includes('/citations'))
    expect(post.body).toEqual({ material_id: 1, anchor: { block_id: 'p2_b7', offset: 0 } })

    const editor = wrapper.find('.wr-editor')
    expect(editor.element.value).toContain('[1]')

    // 助手切到「引用」，那条引文带出处（第 3 页 + 「这一句的开头…」——全站硬约定两段都要有）
    expect(wrapper.find('.wr-helper .tabs button.on').text()).toBe('引用')
    const citeText = wrapper.find('.wr-helper .cite-chip').text()
    expect(citeText).toContain('第 3 页')
    expect(citeText).toContain('读者信任一个答案')
    wrapper.unmount()
  })

  it('⭐ 出处口径：素材卡的芯片也带「这一句的开头」（不是只有页码）', async () => {
    const { impl } = stubWriteFetch({ drafts: [], materials: [MATERIAL] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    // 素材卡现在是共用的 `MaterialCard`（`.mat-card`），出处口径仍要逐字满足
    const chip = wrapper.find('.mat-card .cite-chip')
    expect(chip.exists()).toBe(true)
    const text = chip.text()
    expect(text).toContain('EBSCO_05-mono.pdf')
    expect(text).toContain('第 3 页')
    expect(text).toContain('读者信任一个答案')
    // 全站硬约定：不说「第 Y 段」
    expect(text).not.toContain('段')
    wrapper.unmount()
  })

  it('没有草稿时插引文：如实提示先起一份稿，不发请求', async () => {
    const { impl, calls } = stubWriteFetch({ drafts: [], materials: [MATERIAL] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    await wrapper.findAll('button').find((b) => b.text() === '插入引文').trigger('click')
    await flushPromises()

    expect(calls.some((c) => c.method === 'POST' && c.url.includes('/citations'))).toBe(false)
    expect(toast.value.text).toContain('先起一份稿')
    wrapper.unmount()
  })

  it('清空引文要二次确认（并且说清正文里的 [n] 不会被自动删）', async () => {
    const { impl, calls } = stubWriteFetch({ drafts: [draftFixture()], materials: [MATERIAL] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    await wrapper.findAll('.wr-helper .tabs button')[1].trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((b) => b.text() === '清空引文…').trigger('click')
    await flushPromises()

    expect(wrapper.find('.wr-confirm').text()).toContain('[n]')
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)

    await wrapper.findAll('button').find((b) => b.text() === '确认清空').trigger('click')
    await flushPromises()
    expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('/citations'))).toBe(true)
    wrapper.unmount()
  })
})

describe('起草页：源文献已删的引文（死链不许做成活链）', () => {
  it('[n] 是灰的、不可点，并写清"源文献已删，仅存快照"', async () => {
    const draft = draftFixture({ citations: [CITATION, DEAD_CITATION] })
    const { impl, calls } = stubWriteFetch({ drafts: [draft], materials: [MATERIAL, DEAD_MATERIAL] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    await wrapper.findAll('.wr-helper .tabs button')[1].trigger('click')
    await flushPromises()

    const nums = wrapper.findAll('.wr-cite-no')
    expect(nums.length).toBe(2)
    expect(nums[0].attributes('disabled')).toBeUndefined()
    expect(nums[1].attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('源文献已删，仅存快照')

    // 真点它也不会跳（按钮是 disabled；就算触发也不该发跳转请求）
    await nums[1].trigger('click')
    await flushPromises()
    expect(calls.some((c) => c.url.includes('/api/tasks/42'))).toBe(false)
    wrapper.unmount()
  })
})

describe('⭐ 起草页：点 [1] 回原文并高亮（app 级端到端）', () => {
  it('预览里点 [1] → 打开原文那一篇，并高亮那一句', async () => {
    const { impl, calls } = stubWriteFetch({ drafts: [draftFixture()], materials: [MATERIAL] })
    globalThis.fetch = impl
    localStorage.setItem('docwise_token', 'test-token')
    window.history.replaceState(null, '', '#/write')

    const wrapper = mount(App, { attachTo: document.body })
    await flushPromises()

    // 冷启动直接落在起草页（起草可直达，不依赖读懂）
    expect(wrapper.find('.wr-body').exists()).toBe(true)

    // 切到预览：textarea 里的 [1] 点不了，预览里的能点
    await wrapper.findAll('.wr-doc .seg span').find((s) => s.text() === '预览').trigger('click')
    await flushPromises()
    const marker = wrapper.find('.wr-cite-inline')
    expect(marker.exists()).toBe(true)
    expect(marker.text()).toBe('[1]')

    await marker.trigger('click')
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 10))
    await flushPromises()

    // 落到了阅读工作区，并且原文里那一块被高亮（flash）
    expect(wrapper.find('.screen-reader').exists()).toBe(true)
    expect(window.location.hash).toBe('#/read/42')
    expect(calls.some((c) => c.url.includes('/api/tasks/42'))).toBe(true)
    const flashed = wrapper.find('.doc-pane p.flash')
    expect(flashed.exists()).toBe(true)
    expect(flashed.attributes('data-block-id')).toBe('p2_b7')

    wrapper.unmount()
  })
})

describe('起草页：保存', () => {
  it('改了字之后点「保存」→ PATCH 带 title 与 body_md', async () => {
    const { impl, calls } = stubWriteFetch({ drafts: [draftFixture()], materials: [] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    const editor = wrapper.find('.wr-editor')
    await editor.setValue('# 开题报告\n\n改过的一句。\n')
    await flushPromises()

    const saveBtn = wrapper.findAll('button').find((b) => b.text() === '保存')
    expect(wrapper.find('.wr-save').text()).toBe('未保存')
    await saveBtn.trigger('click')
    await flushPromises()

    const patch = calls.find((c) => c.method === 'PATCH')
    expect(patch.body.body_md).toContain('改过的一句')
    expect(patch.body.title).toBe('开题报告')
    expect(wrapper.find('.wr-save').text()).toContain('已保存')
    wrapper.unmount()
  })
})
