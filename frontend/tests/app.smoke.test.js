/**
 * App.vue 渲染与形态冒烟测试。
 *
 * 存在的两条理由：
 * ① **F 批的真实事故**：模板里把函数当值插值（少写一对括号），Vue 会 `String(fn)`
 *    把整个函数源码印在页面上——而 `vite build` 一声不吭，最后是用户截图发现的。
 * ② **形态那次"货不对板"**：只改颜色、把旧结构留在原地，也能过很松的断言。
 *    所以下面的断言**直接锁原型的结构类名**（`frontend/prototype/product-form.html`），
 *    并明确断言旧结构类名不得再出现——结构退化会红，而不是靠人眼发现。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from '../src/App.vue'

/**
 * pdf.js 在 happy-dom 里画不了 canvas（没有 2d 上下文），所以把加载层换掉，
 * 换成"能拿到文字层"的假文档——**定位与命中这一层才是要测的东西**，
 * 而它们全都建立在文字层坐标上，跟真不真画没关系。
 *
 * 假文档按取回来的字节打标签（mono / dual）：纯中文稿里**故意不含**块文本，
 * 用来验证"对不上时只翻页、不假高亮"这条硬约束。
 */
const DEFAULT_FAKE_PAGES = {
  dual: [
    {
      n: 1,
      items: [{ str: 'first block', x: 10, y: 100, w: 66 }],
    },
    {
      n: 2,
      // 段按阅读顺序（先上后下）排：y 小的在上面，所以 para 0 = third block
      items: [
        { str: 'third block', x: 10, y: 80, w: 66 },
        { str: 'second block', x: 10, y: 100, w: 72 },
      ],
    },
  ],
  mono: [
    {
      n: 1,
      items: [{ str: '这是中文译稿的一段，和块里的英文原文对不上', x: 10, y: 100, w: 300 }],
    },
  ],
}

/** 个别用例要换一套假页（比如验证"纯中文稿靠双语稿对齐"）。 */
let FAKE_PAGES = DEFAULT_FAKE_PAGES

function fakeDocument(tag) {
  const pages = (FAKE_PAGES[tag] || FAKE_PAGES.dual)
  return {
    numPages: pages.length,
    destroy() {},
    async getPage(n) {
      const page = pages.find((p) => p.n === n) || pages[0]
      return {
        getViewport: ({ scale }) => ({ width: 600 * scale, height: 800 * scale, scale, transform: [] }),
        async getTextContent() {
          return {
            items: page.items.map((it) => ({
              str: it.str,
              // pdf.js 的文本矩阵：[a,b,c,d,e,f]，e=x、f=基线 y
              transform: [10, 0, 0, 10, it.x, it.y],
              width: it.w,
              height: 10,
            })),
          }
        },
        async render() {
          return { promise: Promise.resolve() }
        },
        cleanup() {},
      }
    },
  }
}

vi.mock('../src/pdfLoader', () => {
  const pdfjs = { Util: { transform: (_viewport, item) => item } }
  return {
    loadPdfjs: async () => pdfjs,
    itemBox: (lib, viewport, item) => {
      const m = item.transform
      return {
        text: item.str,
        x: m[4],
        y: m[5],
        w: (item.width || 0) * (viewport.scale || 1),
        h: Math.hypot(m[2], m[3]) || 10,
      }
    },
    openPdfDocument: async ({ getBytes }) => {
      const bytes = await getBytes()
      return { doc: fakeDocument(new TextDecoder().decode(bytes)), pdfjs }
    },
  }
})

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
  id: 7,
  filename: 'paper.pdf',
  status: 'in_progress',
  progress: 0.4,
  tier: 'medium',
  created_at: '2026-09-10T12:00:00',
  stage: 'translating',
  eta_seconds: 25,
  elapsed_seconds: 12,
  started_at: '2026-09-10T12:00:10',
  finished_at: null,
  last_read_page: null,
  native: false,
}

const TASK_DETAIL = {
  ...TASK,
  error_message: null,
  translated_path: null,
  dual_translated_path: null,
  blocks: [],
  files_ready: { mono: false, dual: false },
  understanding_status: 'pending',
  queue_position: null,
  engine_progress: { done: 2, total: 5, percent: 0.4, rate: 1.72, eta_seconds: 25 },
}

/** 页面文本里不该出现的东西：函数源码 / 模板语法 / 序列化对象。 */
const SOURCE_LEAKS = ['function ', '=>', 'ref(', 'computed(', '{{', 'undefined']

/**
 * 旧结构类名——形态改造后 L1/L2 里一个都不该再出现。
 * 这条断言就是"只改颜色不改结构"那道坎：上一轮正是这样被判货不对板的。
 */
const FORBIDDEN_LEGACY = [
  'reader-card',
  'workbench-head',
  'workbench-actions',
  'workbench-msg',
  'reader-doc',
  'reader-assist',
  'ask-panel',
  'ask-chips',
  'ask-src-tag',
  'paragraph-row',
  'paragraph-translate',
  'result-toolbar',
  'task-list',
  'task-row',
]

function jsonOf(data) {
  return { ok: true, status: 200, json: async () => data }
}

/**
 * 读一份 `src/` 下的源码（按"判据"钉源码的用例才需要）。
 * ⚠️ 不用 `new URL(..., import.meta.url)`：happy-dom 环境里 `import.meta.url` 不是 `file:` URL，会直接抛。
 * vitest 的 cwd 就是 `frontend/`，所以从 `src/` 起拼即可。
 */
function srcText(rel) {
  return readFileSync(resolve(process.cwd(), 'src', rel), 'utf8')
}

function stubFetch(options = {}) {
  const tasks = options.tasks || [TASK]
  const detail = options.detail || TASK_DETAIL
  const understanding =
    options.understanding || { status: 'pending', guide: null, terms: [], error: null }
  const ask = options.ask || { answer: '（答案）', source_block_ids: [], mode: 'full' }
  return vi.fn(async (input, init = {}) => {
    const url = typeof input === 'string' ? input : String(input?.url ?? input)
    const method = (init.method || 'GET').toUpperCase()
    if (url.includes('/api/health')) return jsonOf(HEALTH)
    if (url.includes('/api/auth/me')) return jsonOf(USER)
    if (url.includes('/api/auth/ticket') && method === 'POST') return jsonOf({ ticket: 't' })
    // PDF 字节：pdf.js 那条路是"取回 ArrayBuffer 一次性喂进去"（不走 ?ticket=，票据会中途过期）
    if (/\/files\/(mono|dual)/.test(url)) {
      const tag = url.includes('/dual') ? 'dual' : 'mono'
      return {
        ok: true,
        status: 200,
        arrayBuffer: async () => new TextEncoder().encode(tag).buffer,
      }
    }
    if (url.includes('/understanding')) return jsonOf(understanding)
    if (url.includes('/ask')) return jsonOf(ask)
    if (url.includes('/reading-position')) return jsonOf({ last_read_page: 1 })
    if (/\/api\/tasks\/\d+\/?$/.test(url)) return jsonOf(detail)
    if (url.includes('/api/tasks')) return jsonOf(tasks)
    return jsonOf({})
  })
}

/** 一篇已经翻完、带三块的论文（段号必须按页内重算：p1_b2 是第 2 页第 1 段）。 */
function completedFixture(overrides = {}) {
  const finished = new Date(Date.now() - 60_000).toISOString()
  const task = {
    ...TASK,
    status: 'completed',
    progress: 1,
    stage: null,
    eta_seconds: null,
    finished_at: finished,
    last_read_page: 2,
    ...overrides.task,
  }
  const detail = {
    ...TASK_DETAIL,
    ...task,
    engine_progress: null,
    files_ready: { mono: true, dual: true },
    blocks: [
      { block_id: 'p0_b0', text: 'first block', translated: '第一块', status: 'success', error: null },
      { block_id: 'p0_b1', text: 'second block', translated: '第二块', status: 'success', error: null },
      { block_id: 'p1_b2', text: 'third block', translated: '第三块', status: 'success', error: null },
    ],
    ...overrides.detail,
  }
  return { task, detail }
}

function mountApp() {
  return mount(App, { attachTo: document.body })
}

/** happy-dom 里改视口宽度：改 innerWidth 再发 resize，触发 App 的窄屏判断。 */
function setViewportWidth(width) {
  Object.defineProperty(window, 'innerWidth', { value: width, configurable: true, writable: true })
  window.dispatchEvent(new Event('resize'))
}

function buttonByText(wrapper, text) {
  return wrapper.findAll('button').find((b) => b.text().includes(text))
}

/**
 * reader-top 里的下拉菜单没有 id，靠"触发按钮"找它。
 * ⚠️ R3（图标体系）之后这两颗触发按钮是**图标按钮**（没有可见文字），
 * 所以改用 `title` 定位 —— 用文本找会在图标化之后一律落空。
 */
function menuWrapByTitle(wrapper, title) {
  return wrapper
    .findAll('.reader-top .menu-wrap')
    .find((m) => m.find('button.btn').exists() && m.find('button.btn').attributes('title') === title)
}

/**
 * 打开一篇论文的阅读工作区：完成态点卡片按钮，进行中点任务条上的文件名。
 *
 * ⚠️ 2026-10-18：问答页签有两种模式（`agent` 会自己查库 / `direct` 只读这一篇），默认 agent。
 * **这批用例断言的是老问答的界面与行为**，所以默认显式切到 direct ——
 * 免得"界面默认值一变、一堆无关断言跟着红"。写 agent 用例时传 `{ askMode: 'agent' }`。
 */
async function openReader(wrapper, label, { askMode = 'direct' } = {}) {
  const btn = buttonByText(wrapper, label)
  expect(btn, `没找到「${label}」入口`).toBeTruthy()
  await btn.trigger('click')
  await flushPromises()
  if (askMode === 'direct') {
    const modeBtn = wrapper
      .findAll('.ask-mode button')
      .find((b) => b.text().includes('只读这一篇'))
    if (modeBtn) {
      await modeBtn.trigger('click')
      await flushPromises()
    }
  }
}

describe('App.vue 页面渲染', () => {
  let wrapper = null

  beforeEach(() => {
    localStorage.clear()
    // 地址也要清干净（M0 加了哈希路由之后）：每个用例从库页开始，
    // 而且**必须走 replaceState**——直接赋 #/ 会真的发一次 hashchange，
    // 通知到上一个还没卸载干净的监听方，串成"单跑能过、一起跑就红"的假故障
    window.history.replaceState(null, '', '#/')
    // 功能测试默认"已登录"：直接放一张令牌，App 挂载时会用它 restoreSession
    localStorage.setItem('docwise_token', 'test-token')
    setViewportWidth(1440)
    globalThis.fetch = stubFetch()
  })

  afterEach(() => {
    // 一定要卸载：否则上一个用例挂载的组件还在跑（轮询/请求回调），
    // 会串到下个用例里，造成"单跑能过、一起跑就红"的假故障
    wrapper?.unmount()
    wrapper = null
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('未登录时渲染登录页，且页面文本里没有源码痕迹', async () => {
    localStorage.clear()
    wrapper = mountApp()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('登录')
    for (const leak of SOURCE_LEAKS) {
      expect(text).not.toContain(leak)
    }
  })

  // ======================================================== M0：哈希路由接线

  it('路由：进阅读区会写地址；按那个地址挂载会直接回到那一篇（刷新不丢页）', async () => {
    // 这一步的主要收益就是"刷新 / 从主屏进来还在原来那一篇"，
    // 所以必须验**两段**：① 进去时地址被写上；② 拿那个地址冷启动能落回同一篇。
    const fx = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [fx.task], detail: fx.detail })
    wrapper = mountApp()
    await flushPromises()

    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()
    expect(wrapper.find('.screen-reader').exists()).toBe(true)
    expect(window.location.hash).toBe(`#/read/${fx.task.id}`)

    // 模拟刷新：卸载后带着同一个地址重新挂载（不清地址，正好是"刷新"的语义）
    wrapper.unmount()
    wrapper = mountApp()
    await flushPromises()
    expect(wrapper.find('.screen-reader').exists()).toBe(true)
    expect(wrapper.text()).toContain(fx.task.filename)
  })

  it('路由：点「← 我的论文」回库页，地址也回到 #/', async () => {
    const fx = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [fx.task], detail: fx.detail })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    await buttonByText(wrapper, '← 我的论文').trigger('click')
    await flushPromises()
    expect(window.location.hash).toBe('#/')
    expect(wrapper.find('.lib-wrap').exists()).toBe(true)
  })

  it('路由：未知地址落到库页，不白屏也不印源码', async () => {
    const fx = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [fx.task], detail: fx.detail })
    window.history.replaceState(null, '', '#/garbage')
    wrapper = mountApp()
    await flushPromises()

    expect(wrapper.find('.lib-wrap').exists()).toBe(true)
    const text = wrapper.text()
    for (const leak of SOURCE_LEAKS) {
      expect(text).not.toContain(leak)
    }
  })

  // ======================================================== 屏 ①：L1 空库

  it('L1 空库：历史记录页给上传卡 + 真空态，**不出 hero**、不出网格', async () => {
    globalThis.fetch = stubFetch({ tasks: [] })
    wrapper = mountApp()
    await flushPromises()

    // ⚠️ 2026-10-17：hero（"把文献读懂" + 三枚示例）**搬去了「读懂」页**。
    //    历史记录页在空库时只做一件有用的事：摆出上传卡 + 说清"还没有文献"。
    expect(wrapper.find('.topbar').exists()).toBe(true)
    expect(wrapper.find('.hero').exists()).toBe(false)
    expect(wrapper.find('.upload-card').exists()).toBe(true)
    expect(wrapper.find('.grid3').exists()).toBe(false)
    expect(wrapper.text()).toContain('还没有文献')

    // 上传卡：.card.upload-card > .drop + 档位 .seg（**不再是 n-radio-group / n-upload-dragger**）
    const upload = wrapper.find('.card.upload-card')
    expect(upload.exists()).toBe(true)
    expect(upload.find('.drop').exists()).toBe(true)
    expect(upload.find('.drop .big').text()).toBe('点击或拖拽 PDF 到此处')
    expect(upload.find('.drop-hint').exists()).toBe(true)
    expect(upload.find('input[type="file"]').exists()).toBe(false) // 文件框是隐藏的，不在卡里

    // 档位只有一个写法（形态硬约定）
    const segText = upload.findAll('.seg span').map((s) => s.text())
    expect(segText).toContain('快档 · 最快')
    expect(segText).toContain('中档 · 平衡')
    // 精档**不可选**：registry 里它一直映射到中档引擎，摆出来就是骗人（见 App.vue 的注释）
    expect(segText).not.toContain('精档 · 最准')
    expect(segText.join('')).not.toContain('精档')
    expect(upload.find('.tier-note').exists()).toBe(true)
    expect(upload.text()).toContain('精档（多一道审校的那一档）还没做')
    expect(upload.text()).not.toContain('多一道审校，适合定稿引用')
    expect(upload.text()).not.toContain('慢档')

    // 空库不出论文网格；标题行**在**（2026-10-17 起历史记录页一直有标题行，
    // 只是标题文案是「我的文献」，不带篇数）
    expect(wrapper.find('.grid3').exists()).toBe(false)
    expect(wrapper.find('.title-row h2').text()).toBe('我的文献')

    for (const leak of SOURCE_LEAKS) {
      expect(wrapper.text()).not.toContain(leak)
    }
    for (const legacy of FORBIDDEN_LEGACY) {
      expect(wrapper.html()).not.toContain(legacy)
    }
  })

  it('读懂页（#/read）：hero 三枚可点描边按钮在，且点了要说话（没有可读论文时不许装作打开了）', async () => {
    globalThis.fetch = stubFetch({ tasks: [] })
    // 「读懂」工作台 = `#/read`（历史记录仍是 `#/`）
    window.history.replaceState(null, '', '#/read')
    wrapper = mountApp()
    await flushPromises()

    expect(wrapper.find('.rh-hero h1').text()).toBe('把文献读懂')
    expect(wrapper.findAll('.rh-pills button.pill').length).toBe(3)
    expect(
      wrapper.findAll('.rh-pills button.pill').every((b) => b.attributes('disabled') === undefined),
    ).toBe(true)

    const drop = wrapper.find('.upload-card .drop')
    expect(drop.classes()).not.toContain('drop-over')

    await wrapper.findAll('.rh-pills button.pill')[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.toast.show').exists()).toBe(true)
    expect(wrapper.text()).toContain('还没有可读的论文')
    // 光弹一句话不够：落点要指到上传卡上（点亮一下），否则用户点了觉得没反应
    expect(drop.classes()).toContain('drop-over')
    // 页面不许跳到阅读工作区（没有论文就别假装打开了示例）
    expect(wrapper.find('.screen-reader').exists()).toBe(false)
  })

  it('空库态上传卡里：选「中文文献」后翻译档位消失（中文文献不翻译）', async () => {
    globalThis.fetch = stubFetch({ tasks: [] })
    wrapper = mountApp()
    await flushPromises()

    expect(wrapper.text()).toContain('文献语言')
    expect(wrapper.text()).toContain('翻译档位')

    const zh = wrapper.findAll('.seg span').find((s) => s.text() === '中文文献')
    expect(zh, '上传区没有"中文文献"选项').toBeTruthy()
    await zh.trigger('click')
    await flushPromises()

    const text = wrapper.text()
    expect(text).not.toContain('翻译档位')
    expect(text).toContain('中文文献不翻译')
  })

  // ======================================================== 屏 ②：L1 有历史

  it('L1 有历史：标题行 + 进行中任务条 + 完成横幅 + 卡片网格（不出 hero）', async () => {
    const running = { ...TASK, tier: 'medium' }
    const done = {
      ...TASK,
      id: 9,
      status: 'completed',
      progress: 1,
      finished_at: new Date(Date.now() - 3 * 60 * 1000).toISOString(),
      last_read_page: 5,
      elapsed_seconds: 372,
    }
    const failed = { ...TASK, id: 10, status: 'failed', finished_at: null, elapsed_seconds: 30 }
    globalThis.fetch = stubFetch({ tasks: [running, done, failed], detail: TASK_DETAIL })

    wrapper = mountApp()
    await flushPromises()

    // 有历史就不出 hero
    expect(wrapper.find('.hero').exists()).toBe(false)

    // 标题行：篇数 + 唯一上传入口
    expect(wrapper.find('.title-row h2').text()).toBe('我的文献 · 3 篇')
    expect(buttonByText(wrapper, '＋ 上传 PDF')).toBeTruthy()

    // 进行中任务条：3 段信息 + 进度条 + 取消 / 详情
    const bar = wrapper.find('.card.running')
    expect(bar.exists()).toBe(true)
    expect(bar.find('.name').text()).toBe('paper.pdf')
    expect(bar.find('.bar > i').exists()).toBe(true)
    expect(bar.text()).toContain('正在翻译')
    expect(bar.text()).toContain('引擎自报还需约 25 秒')
    expect(bar.text()).toContain('已用 12 秒')

    // 完成横幅：变绿 + 下一步动作（最多一条）
    const banner = wrapper.find('.card.taskbar-ok')
    expect(banner.exists()).toBe(true)
    expect(banner.find('.ok-text').text()).toBe('翻译完成')
    expect(buttonByText(banner, '开始阅读')).toBeTruthy()
    expect(buttonByText(banner, '关闭')).toBeTruthy()

    // 卡片网格：跑着的那篇走任务条，不进网格
    const cards = wrapper.findAll('.grid3 .card.paper-card')
    expect(cards.length).toBe(2)
    const doneCard = cards.find((c) => c.text().includes('paper.pdf') && c.text().includes('已完成'))
    expect(doneCard).toBeTruthy()
    expect(doneCard.find('.meta').text()).toContain('中档 · 平衡')
    expect(doneCard.find('.lastpos').text()).toContain('上次读到第 5 页')
    expect(buttonByText(doneCard, '继续读')).toBeTruthy()

    // 失败卡的唯一下一步是重新翻译，且技术细节不糊在卡片上
    const failedCard = cards.find((c) => c.text().includes('失败'))
    expect(failedCard.find('.meta').text()).toBe('翻译引擎出错，重新翻译通常可解决')
    expect(failedCard.find('.chip.fail').exists()).toBe(true)
    const retry = buttonByText(failedCard, '重新翻译')
    expect(retry).toBeTruthy()
    expect(retry.classes()).toContain('primary')

    expect(wrapper.find('.footline').exists()).toBe(true)
    for (const legacy of FORBIDDEN_LEGACY) {
      expect(wrapper.html()).not.toContain(legacy)
    }
  })

  // ======================================================== 屏 ③④⑤：L2 三副页签

  it('L2 阅读工作区：reader-top / 细进度条 / 长条 / 两栏，且进度写人话不印源码', async () => {
    const { task, detail } = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    wrapper = mountApp()
    await flushPromises()

    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    // 原型 L2 的骨架：reader-top → thin-bar → note-line → reader-body(doc-pane + assist)
    expect(wrapper.find('.screen-reader').exists()).toBe(true)
    const top = wrapper.find('.reader-top')
    expect(top.exists()).toBe(true)
    expect(top.find('.fname').text()).toBe('paper.pdf')
    expect(top.text()).toContain('中档 · 平衡')
    expect(buttonByText(top, '← 我的论文')).toBeTruthy()
    expect(buttonByText(top, '下载译稿')).toBeTruthy()
    expect(buttonByText(top, '搜索')).toBeTruthy()
    expect(wrapper.find('.thin-bar').exists()).toBe(true)
    expect(wrapper.find('.thin-bar > i').exists()).toBe(true)
    expect(wrapper.find('.note-line').exists()).toBe(true)
    // 没有话要说的时候必须**真的是空的**：原型靠 `.note-line:not(:empty)` 决定要不要那条分隔线，
    // 里面留一个空 <span> 就会永远多出一条空横线（照原型并排比对时抓出来的偏差）
    expect(wrapper.find('.note-line').element.children.length).toBe(0)
    expect(wrapper.find('.note-line').text()).toBe('')

    // 左栏：段落精读 = .doc-pane > .page > .cols > p（锚点是我们自己的 DOM）
    const pane = wrapper.find('.doc-pane')
    expect(pane.exists()).toBe(true)
    expect(wrapper.findAll('.doc-pane .page').length).toBe(2) // 两块分属两页
    expect(wrapper.findAll('.doc-pane .page .cols p').length).toBe(3)
    expect(wrapper.find('.doc-pane .page h3').text()).toBe('paper') // 标题取文件名，去掉 .pdf
    expect(wrapper.find('.doc-pane .page .authors').exists()).toBe(true)

    // 右栏：三个副页签 + 吸底输入框
    const tabs = wrapper.findAll('.assist .tabs button')
    expect(tabs.map((t) => t.text())).toEqual(['问答', '导读', '术语'])
    expect(tabs[0].classes()).toContain('on')
    expect(wrapper.find('.assist .tabbody').exists()).toBe(true)
    // ⚠️ 2026-10-18：输入框归 agent 组件自己管（.agent-composer），
    // 模型选择也搬进这一行（和主流 agent 工具一致，不占消息区顶部）
    expect(wrapper.find('.assist .agent-composer textarea').exists()).toBe(true)
    expect(wrapper.find('.assist .agent-composer .agent-model-btn').exists()).toBe(true)
    expect(wrapper.find('.assist .agent-composer button.btn.primary').text()).toBe('↑')

    // 完成后的页数胶囊说总页数（引擎没在跑就不编进度）
    expect(top.text()).toContain('共 2 页')

    // 阅读位置记忆：R-15 —— 回到上次位置并 toast
    expect(wrapper.find('.toast.show').exists()).toBe(true)
    expect(wrapper.text()).toContain('已回到第 2 页')

    for (const leak of SOURCE_LEAKS) {
      expect(wrapper.text()).not.toContain(leak)
    }
    for (const legacy of FORBIDDEN_LEGACY) {
      expect(wrapper.html()).not.toContain(legacy)
    }
  })

  it('打开正在翻译的论文：进度区显示人话（页进度 / 已用 / 剩余），不印函数源码', async () => {
    wrapper = mountApp()
    await flushPromises()

    // 进行中的任务走任务条（不进卡片网格），点文件名进阅读工作区
    await wrapper.find('.card.running .name-link').trigger('click')
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('正在翻译')
    expect(text).toContain('第 2/5 页')
    expect(text).toContain('已用 12 秒')
    expect(text).toContain('引擎自报还需约 25 秒')

    // 进度条必须还在（这个坑真踩过：没数字就不画 → 用户看到"进度条没了"）
    expect(wrapper.find('.thin-bar').exists()).toBe(true)
    expect(wrapper.find('.thin-bar > i').exists()).toBe(true)
    expect(wrapper.find('.thin-bar').classes()).not.toContain('striped')

    for (const leak of SOURCE_LEAKS) {
      expect(text).not.toContain(leak)
    }
  })

  it('引擎还没报进度时：说"还在准备"，进度条画流动条纹而不是假的百分比', async () => {
    const noEngine = { ...TASK_DETAIL, engine_progress: null, eta_seconds: null }
    globalThis.fetch = stubFetch({ detail: noEngine })
    wrapper = mountApp()
    await flushPromises()

    await wrapper.find('.card.running .name-link').trigger('click')
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('正在翻译 · 引擎还没报进度')
    expect(text).not.toContain('第 2/5 页')
    expect(text).not.toContain('引擎自报还需')

    // 没拿到数字时进度条也要在，而且画的是"不确定"的流动条纹
    const bar = wrapper.find('.thin-bar')
    expect(bar.exists()).toBe(true)
    expect(bar.classes()).toContain('striped')
    expect(bar.find('i').attributes('style')).toContain('width: 100%')

    for (const leak of SOURCE_LEAKS) {
      expect(text).not.toContain(leak)
    }
  })

  it('「更多」菜单照原型是单层级 6 项；下载入口只有一个「下载译稿 ▾」两项', async () => {
    const { task, detail } = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    const more = menuWrapByTitle(wrapper, '更多')
    expect(more, 'reader-top 里没有「更多」菜单').toBeTruthy()
    const items = more.findAll('.menu button').map((b) => b.text())
    expect(items).toEqual([
      '文档信息',
      '重试翻译（本档）',
      '换档位重译…',
      '详情',
      '问题反馈…',
      '删除…',
    ])
    // 危险项标红；且任意两项不共享动词（不许出现两个"重新翻译"）
    expect(more.find('.menu button.danger').text()).toBe('删除…')
    expect(items.filter((t) => t.includes('重新翻译')).length).toBe(0)

    const dl = menuWrapByTitle(wrapper, '下载译稿')
    expect(dl, 'reader-top 里没有「下载译稿」菜单').toBeTruthy()
    expect(dl.findAll('.menu button').map((b) => b.text())).toEqual(['下载双语稿', '下载纯中文稿'])

    // 菜单互斥且点外关闭
    expect(more.find('.menu').classes()).not.toContain('open')
    await more.find('button.btn').trigger('click')
    expect(more.find('.menu').classes()).toContain('open')
    expect(dl.find('.menu').classes()).not.toContain('open')
    await dl.find('button.btn').trigger('click')
    expect(more.find('.menu').classes()).not.toContain('open')
    expect(dl.find('.menu').classes()).toContain('open')
    await wrapper.find('.dw').trigger('click')
    expect(dl.find('.menu').classes()).not.toContain('open')
  })

  // ======================================================== M0：R3 图标体系 + emoji 清理

  it('R3：会渲染成 emoji 的字符一个都不上屏，换上来的是 sprite 里的真图标', async () => {
    const { task, detail } = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    // ① U+1F50D 搜索 / U+2913 下载 / U+22EF 更多 / U+1F4AC 信息泡 —— 它们在 Windows 上会变彩色，
    //    正是"廉价感"的来源；样式与模板里都不许再出现
    const html = wrapper.html()
    for (const ch of ['🔍', '⤓', '⋯', '💬']) {
      expect(html, `渲染出的 HTML 里仍有 ${ch}`).not.toContain(ch)
    }

    // ② 换上来的是 index.html 里 inline 的 sprite（35 个 <symbol id="i-…">）真引用
    const uses = wrapper.findAll('svg use').map((u) => u.attributes('href'))
    expect(uses.length, '一个 <use> 都没有——图标没接上').toBeGreaterThan(0)
    expect(uses.every((h) => /^#i-[\w-]+$/.test(h))).toBe(true)
    expect(uses).toContain('#i-search')
    expect(uses).toContain('#i-download')
    expect(uses).toContain('#i-more')
    // 划词浮标与 PDF 浮标上那颗信息点：原来靠 style.css 的 content:"💬" 画出来。
    // 它们只在"有选区 / 点了 PDF 段"时才渲染，所以这里按**源码**钉住接线；
    // CSS 那一侧（content: 不许再有 emoji）由下一条用例钉。
    expect(srcText('views/ReadView.vue')).toContain('href="#i-info"')
    expect(srcText('components/PdfPane.vue')).toContain('href="#i-info"')

    for (const leak of SOURCE_LEAKS) {
      expect(wrapper.text()).not.toContain(leak)
    }
  })

  it('R3：style.css 的 content: 里不许再有会渲染成 emoji 的字符（.selchip / .pdf-chip 那两处真会上屏）', () => {
    const css = srcText('style.css')
    const declared = [...css.matchAll(/content:\s*"([^"]*)"/g)].map((m) => m[1])
    expect(declared.length, '一条 content: 都没扫到，判据本身失效了').toBeGreaterThan(0)
    // 会渲染成彩色 emoji 的区段：杂项符号与表情（U+2600–27BF）、杂项符号与箭头字母
    //（U+2B00–2BFF）、表情符号主区与补充区（U+1F000–1FAFF）、变体选择符（U+FE0F）
    const emojiLike = /[\u2600-\u27BF\u2B00-\u2BFF\u{1F000}-\u{1FAFF}\uFE0F]/u
    for (const value of declared) {
      expect(
        emojiLike.test(value),
        `style.css 的 content: 里有会渲染成 emoji 的字符：${JSON.stringify(value)}`,
      ).toBe(false)
    }
  })

  /**
   * 取某条规则**所在的最近一个 `@media` 段**（找不到就返回空串）。
   * 用来断言"这条规则必须写在窄档里"——只看规则文本会漏掉"写在媒体查询外"这种回归。
   * ⚠️ 本文件里的媒体块内部没有行首右括号，所以按 `\n}` 找块尾够用。
   */
  function mediaOf(css, index) {
    const at = css.slice(0, index).lastIndexOf('@media')
    if (at === -1) return ''
    const close = css.indexOf('\n}', css.indexOf('{', at))
    return css.slice(at, close === -1 ? undefined : close)
  }

  it('窄屏：<860px 左栏收成 58px（形态 v2 §3 第 106 行）——否则 390px 下内容列只剩 ~130px', () => {
    const css = srcText('style.css')
    const rule = /\.dw \.rail\s*\{[^}]*flex-basis:\s*var\(--rail-w-min\)[^}]*\}/.exec(css)
    expect(rule, '找不到"左栏收成 58px"这条规则').toBeTruthy()
    expect(mediaOf(css, rule.index)).toMatch(/max-width:\s*859px/)
  })

  it('窄屏：会话 / 台账表自己滚，不许把整页撑宽（表里有不可断行的时间戳）', () => {
    const css = srcText('style.css')
    const rule = /\.dw \.me-table\s*\{[^}]*overflow-x:\s*auto[^}]*\}/.exec(css)
    expect(rule, '表格没有横向滚动容器').toBeTruthy()
    expect(mediaOf(css, rule.index)).toMatch(/max-width:\s*859px/)
  })

  it('窄屏：手机顶栏按钮抬到触控下限 44px（原来约 20px，拇指点不中）', () => {
    const css = srcText('style.css')
    const rule = /\.dw \.ptop \.btn\s*\{[^}]*min-height:\s*44px[^}]*\}/.exec(css)
    expect(rule, '手机顶栏没有 44px 触控高度').toBeTruthy()
    expect(mediaOf(css, rule.index)).toMatch(/max-width:\s*1023px/)
  })

  it('窄屏：底部抽屉让开 iPhone 安全区（原来贴屏幕底，抓手压在 home indicator 上）', () => {
    const css = srcText('style.css')
    const rule = /\.dw \.sheet\s*\{[^}]*env\(safe-area-inset-bottom[^}]*\}/.exec(css)
    expect(rule, '抽屉没有安全区内边距').toBeTruthy()
    expect(mediaOf(css, rule.index)).toMatch(/max-width:\s*1023px/)
  })



  it('导读：相邻两行的出处合并成**一个**（同一句被换行切断，不该显示成两个出处）', async () => {
    const { task, detail } = completedFixture()
    // 真实情况：中文文献的块按行切，模型把"上一行 + 下一行"当两个块报回来
    const understanding = {
      status: 'ready',
      guide: {
        research_question: { text: '研究问题在这两行里。', source_block_ids: ['p0_b0', 'p0_b1'] },
      },
      terms: [],
      error: null,
    }
    globalThis.fetch = stubFetch({ tasks: [task], detail, understanding })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()
    // 点开「导读」页签才会去取理解层（惰性）
    await wrapper.findAll('.assist .tabs button')[1].trigger('click')
    await flushPromises()

    const trace = wrapper
      .findAll('.guide-card .ops button')
      .filter((b) => b.text().includes('看原文'))
    expect(trace.length, '相邻两行被拆成了两个出处').toBe(1)
    // 标签用**合并后的整句**开头，点一次高亮完整句
    expect(trace[0].text()).toBe('看原文（第 1 页 ·「first block…」）▸')
    expect(trace[0].attributes('title')).toBe('原文块 p0_b0 + p0_b1')
  })

  it('段落精读：点正文那一段本身就亮，不是只有「看原文」才亮；再点一次取消', async () => {
    const { task, detail } = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    const para = () => wrapper.find('.doc-pane p#p0_b0')
    expect(para().classes()).not.toContain('sel')

    await para().trigger('click')
    expect(para().classes()).toContain('sel')
    expect(wrapper.find('.doc-pane .selchip').exists()).toBe(true)

    // 同一段再点一次 = 取消选中
    await para().trigger('click')
    expect(para().classes()).not.toContain('sel')
    expect(wrapper.find('.doc-pane .selchip').exists()).toBe(false)

    // 点另一段：选中态跟着换过去，不会两段同时亮
    await wrapper.find('.doc-pane p#p0_b1').trigger('click')
    expect(wrapper.find('.doc-pane p#p0_b1').classes()).toContain('sel')
    expect(para().classes()).not.toContain('sel')
  })



  it('导读：有出处的写完坐标可点，无出处的置灰不可点并说明为什么（死链不许做成活链样式）', async () => {
    const { task, detail } = completedFixture()
    const understanding = {
      status: 'ready',
      guide: {
        research_question: { text: '理解损失发生在哪一步。', source_block_ids: ['p0_b0'] },
        method: { text: '30 名被试各读两篇。', source_block_ids: ['p0_b1'] },
        conclusion: { text: '读者要能跳回出处。', source_block_ids: ['p1_b2'] },
        innovation: { text: '把提问锚点与答案出处放进同一坐标系。', source_block_ids: [] },
        contribution: { text: '给出可测指标。', source_block_ids: ['p9_b99'] },
      },
      terms: [],
      error: null,
    }
    globalThis.fetch = stubFetch({ tasks: [task], detail, understanding })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    await wrapper.findAll('.assist .tabs button')[1].trigger('click')
    await flushPromises()

    const cards = wrapper.findAll('.assist .guide-card')
    expect(cards.length).toBe(5)
    expect(cards.map((c) => c.find('.k').text())).toEqual([
      '研究问题',
      '方法',
      '结论',
      '创新点',
      '核心贡献',
    ])

    // 有出处：坐标在点之前就显示（来自后端真数据 source_block_ids），且可点、带箭头
    const traceBtn = cards[0].find('.ops button')
    expect(traceBtn.text()).toBe('看原文（第 1 页 ·「first block」）▸')
    expect(traceBtn.attributes('disabled')).toBeUndefined()

    // 无出处：置灰、disabled、没有箭头，并有一句说明
    const deadBtn = cards[3].find('.ops button.dead')
    expect(deadBtn.exists()).toBe(true)
    expect(deadBtn.text()).toBe('无单一段落出处')
    expect(deadBtn.attributes('disabled')).toBeDefined()
    expect(deadBtn.text()).not.toContain('▸')
    expect(cards[3].find('.dead-note').text()).toContain('由全文综合而成')

    // 每条要点都有「就这条追问」（⚠️ 按**文字**找，不按位置——`.ops` 里后来又加了
    // 「存素材」，按 `nth-child` 找会随按钮增减而错位）
    const askButtons = cards[0].findAll('.ops button').filter((b) => b.text() === '就这条追问')
    expect(askButtons).toHaveLength(1)

    // ⭐ 同一条规矩也要管住「存素材」：**没有出处 / 定位不到出处时一个都不给**
    // （死链不许做成活链样式——存一个不存在的块编号只会 404）
    expect(cards[3].findAll('.mat-save')).toHaveLength(0) // 无单一段落出处
    expect(cards[4].findAll('.mat-save')).toHaveLength(0) // 有出处但定位不到
    expect(cards[0].findAll('.mat-save')).toHaveLength(1) // 有出处、定位得到 → 给

    // 点了有出处的：跳过去并闪烁
    await traceBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.doc-pane p#p0_b0').classes()).toContain('flash')

    // 块编号推导不出位置 → 写「位置待定」，绝不裸露编号
    const pending = cards[4].find('.ops button')
    expect(pending.text()).toBe('看原文（位置待定）▸')

    // 定位不到时说实话（原型 .honest 那条）
    await pending.trigger('click')
    await flushPromises()
    const honest = wrapper.find('.assist .honest')
    expect(honest.exists()).toBe(true)
    expect(honest.text()).toContain('宁可不给，也不假高亮')

    expect(wrapper.text()).not.toContain('p9_b99')
    for (const leak of SOURCE_LEAKS) {
      expect(wrapper.text()).not.toContain(leak)
    }
  })

  it('术语：按钮先只写「在原文中定位」，**命中后才回填坐标**，未命中直说没找到', async () => {
    const { task, detail } = completedFixture()
    const understanding = {
      status: 'ready',
      guide: null,
      terms: [
        { term: 'first', cn: '第一块', definition: '能在正文里找到的术语。' },
        { term: 'phrase-only-in-figures', cn: '只在图表里', definition: '正文里找不到的术语。' },
      ],
      error: null,
    }
    globalThis.fetch = stubFetch({ tasks: [task], detail, understanding })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    await wrapper.findAll('.assist .tabs button')[2].trigger('click')
    await flushPromises()

    const terms = wrapper.findAll('.assist .termlist .term')
    expect(terms.length).toBe(2)
    expect(terms[0].find('b').text()).toBe('first')
    expect(terms[0].find('.cn').text()).toBe('第一块')
    expect(terms[0].find('.def').exists()).toBe(true)

    // **不许预填坐标**：点之前只有一个动词，没有任何页/段
    const hitBtn = terms[0].find('.ops button')
    expect(hitBtn.text()).toBe('在原文中定位')
    expect(hitBtn.text()).not.toContain('第')

    // 命中 → 回填「已定位 · 第 X 页 ·「…」」+ 跳过去闪烁
    await hitBtn.trigger('click')
    await flushPromises()
    expect(terms[0].find('.ops button').text()).toBe('已定位 · 第 1 页 ·「first block」')
    expect(wrapper.find('.doc-pane p#p0_b0').classes()).toContain('flash')

    // 未命中 → 直说（别装）
    const missBtn = terms[1].find('.ops button')
    await missBtn.trigger('click')
    await flushPromises()
    expect(terms[1].find('.ops button').text()).toBe('没找到，可能在图/表里')

    for (const leak of SOURCE_LEAKS) {
      expect(wrapper.text()).not.toContain(leak)
    }
  })

  it('块级译文缺失时诚实提示（别让「纯中文」显示着英文）', async () => {
    const { task, detail } = completedFixture()
    const rawDetail = {
      ...detail,
      // 真实库就是这样：text 有、translated 全是空（实测 1510 个块无一例外）
      blocks: [
        { block_id: 'p0_b0', text: 'first block', translated: null, status: 'success', error: null },
        { block_id: 'p0_b1', text: 'second block', translated: '', status: 'success', error: null },
      ],
    }
    globalThis.fetch = stubFetch({ tasks: [task], detail: rawDetail })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '开始阅读').trigger('click')
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('暂无「块级」译文')
    // 段落仍然渲染（回退显示原文），不是空白页；且**同一段英文不许显示两遍**
    expect(wrapper.findAll('.doc-pane .page .cols p').length).toBe(2)
    expect(text).toContain('first block')
    expect(wrapper.findAll('.doc-pane p .en').length).toBe(0)

    for (const leak of SOURCE_LEAKS) {
      expect(text).not.toContain(leak)
    }
  })

  it('块分级：标题 / 图注 在段落精读里各有自己的类', async () => {
    // 判据在服务端（backend/app/blocktypes.py），前端只负责按 type 上样式。
    // 这里锁的是"类型真的走到了 DOM 上"——判错是"标题被当正文"这种一眼可见、
    // 但没人会逐块核对的问题。
    const { task, detail } = completedFixture({
      detail: {
        blocks: [
          { block_id: 'p0_b0', text: 'Solving Linear Systems', translated: '求解线性方程组', status: 'success', error: null, type: 'title' },
          { block_id: 'p0_b1', text: '1 Introduction', translated: '1 引言', status: 'success', error: null, type: 'heading' },
          { block_id: 'p0_b2', text: 'Figure 1: The algorithm.', translated: '图 1：算法。', status: 'success', error: null, type: 'caption' },
          { block_id: 'p0_b3', text: 'We give an algorithm.', translated: '我们给出一个算法。', status: 'success', error: null, type: 'body' },
        ],
      },
    })
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    expect(wrapper.find('.cols p.pg-title').exists()).toBe(true)
    expect(wrapper.find('.cols p.pg-heading').exists()).toBe(true)
    expect(wrapper.find('.cols p.pg-caption').exists()).toBe(true)
    expect(wrapper.find('.cols p.pg-body').exists()).toBe(true)
  })

  it('块没有 type 字段时按正文渲染，不留空类', async () => {
    const { task, detail } = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    expect(wrapper.findAll('.cols p.pg-body').length).toBe(3)
    expect(wrapper.find('.cols p.pg-undefined').exists()).toBe(false)
  })

  it('目录：把标题变成可点的跳转，点一条滚到那一段并高亮', async () => {
    // 判据仍然只在服务端（块分级给 type）；前端只做两件事：**列出来**、**跳过去**。
    // 跳转复用出处那套 traceTo（滚到那一段 + 高亮脉冲），不另立一套定位机制。
    const { task, detail } = completedFixture({
      detail: {
        blocks: [
          { block_id: 'p0_b0', text: 'Solving Linear Systems', translated: '求解线性方程组', status: 'success', error: null, type: 'title' },
          { block_id: 'p0_b1', text: '1 Introduction', translated: '1 引言', status: 'success', error: null, type: 'heading' },
          { block_id: 'p0_b2', text: 'We give an algorithm.', translated: '我们给出一个算法。', status: 'success', error: null, type: 'body' },
          { block_id: 'p1_b0', text: '2 Methods', translated: '2 方法', status: 'success', error: null, type: 'heading' },
          { block_id: 'p1_b1', text: '3 Results', translated: '3 结果', status: 'success', error: null, type: 'heading' },
        ],
      },
    })
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    // 默认收起：只占一行，正文不被顶开
    expect(wrapper.find('.doc-pane .toc').exists()).toBe(true)
    expect(wrapper.find('.doc-pane .toc-list').exists()).toBe(false)
    expect(wrapper.find('.doc-pane .toc-head').text()).toContain('4 节')

    await wrapper.find('.doc-pane .toc-head').trigger('click')
    const items = wrapper.findAll('.doc-pane .toc-item')
    expect(items.length).toBe(4)
    // 目录用中文译文（有译文时），并标出在第几页
    expect(items[1].text()).toContain('1 引言')
    expect(items[1].text()).toContain('第 1 页')

    await items[3].trigger('click')
    await flushPromises()
    expect(wrapper.find('.doc-pane .toc-list').exists()).toBe(false) // 跳完就收起
    const flashed = wrapper.find('.doc-pane p.flash')
    expect(flashed.exists()).toBe(true)
    expect(flashed.attributes('data-block-id')).toBe('p1_b1')
  })

  it('目录：标题太少或没有标题时整条不渲染（不硬造）', async () => {
    // 只有一两个标题的文献摆个「目录」是噪音；老任务 / 扫描件一条标题都没有，更不能编。
    const few = completedFixture({
      detail: {
        blocks: [
          { block_id: 'p0_b0', text: '1 Introduction', translated: '1 引言', status: 'success', error: null, type: 'heading' },
          { block_id: 'p0_b1', text: 'Body text.', translated: '正文。', status: 'success', error: null, type: 'body' },
        ],
      },
    })
    globalThis.fetch = stubFetch({ tasks: [few.task], detail: few.detail })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()
    expect(wrapper.find('.toc').exists()).toBe(false)

    const none = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [none.task], detail: none.detail })
    // 重挂之前**必须先卸载**上一个实例：M0 加了哈希路由之后，两个活着的实例会抢同一个
    // `window.location.hash`（一个改地址、另一个的路由订阅跟着响应），断言就会打到别人身上。
    // 以前没这要求只是因为那时没人碰 window.location。
    wrapper.unmount()
    // 卸载**不会**把地址还原：上一个实例进阅读区时把 hash 写成了 `#/read/7`，
    // 而新实例挂载后会按地址"回到原页"（这正是 M0 路由要的行为）。
    // 所以重挂之前要把地址退回库页，否则第二个实例一上来就渲染成阅读页。
    window.history.replaceState(null, '', '#/')
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()
    expect(wrapper.find('.toc').exists()).toBe(false)
  })

  it('扫描件：段落视图如实说明「文字是 OCR 认的、可能有错字」', async () => {
    // 这份文献没有文字层，块里的字是本地 OCR 认出来的。不说这一句，
    // 用户会把 OCR 的错字当成原文的错——诚实性是硬约束。
    const { task, detail } = completedFixture({ detail: { text_source: 'ocr' } })
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    const note = wrapper.find('.doc-pane .doc-note')
    expect(note.exists()).toBe(true)
    expect(note.text()).toContain('扫描件')
    expect(note.text()).toContain('OCR')
    expect(note.text()).toContain('错字')
  })

  it('非扫描件不该出现 OCR 提示（别把提示当装饰挂着）', async () => {
    const { task, detail } = completedFixture({ detail: { text_source: 'text-layer' } })
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('文字由本地 OCR 识别')
  })

  it('中文文献：说"原文"、只给一份下载，不提供中英对照', async () => {
    const finished = new Date(Date.now() - 60_000).toISOString()
    const nativeTask = {
      ...TASK,
      status: 'completed',
      progress: 1,
      stage: null,
      eta_seconds: null,
      finished_at: finished,
      native: true,
      source_lang: 'zh',
      target_lang: 'zh',
      last_read_page: null,
    }
    const nativeDetail = {
      ...TASK_DETAIL,
      ...nativeTask,
      blocks: [
        { block_id: 'p0_b0', text: '中文原文第一段。', translated: null, status: 'success', error: null },
      ],
      // 中文文献只有一份产物（原稿），没有双语稿
      files_ready: { mono: true, dual: false },
      engine_progress: null,
    }
    globalThis.fetch = stubFetch({ tasks: [nativeTask], detail: nativeDetail })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '开始阅读').trigger('click')
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('中文文献 · 不翻译')
    expect(text).toContain('下载译稿')
    // 中文文献没有"中英对照"这回事，也不该出现双语入口
    expect(text).not.toContain('中英对照')
    expect(text).not.toContain('下载双语稿')
    expect(text).toContain('下载原稿 PDF')
    // 不翻译 ≠ 缺译文，所以这里**不该**出现"块级译文"那条缺口提示
    expect(text).not.toContain('暂无「块级」译文')

    for (const leak of SOURCE_LEAKS) {
      expect(text).not.toContain(leak)
    }
  })

  it('两级结构：打开一篇进 L2，点「← 我的论文」回 L1 库页', async () => {
    const { task, detail } = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    wrapper = mountApp()
    await flushPromises()

    expect(wrapper.find('.paper-card').exists()).toBe(true)
    expect(wrapper.find('.screen-reader').exists()).toBe(false)

    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    expect(wrapper.find('.screen-reader').exists()).toBe(true)
    expect(wrapper.find('.paper-card').exists()).toBe(false)

    await buttonByText(wrapper, '← 我的论文').trigger('click')
    await flushPromises()

    expect(wrapper.find('.paper-card').exists()).toBe(true)
    expect(wrapper.find('.screen-reader').exists()).toBe(false)
    for (const leak of SOURCE_LEAKS) {
      expect(wrapper.text()).not.toContain(leak)
    }
  })

  // ======================================================== 屏 ⑥：手机端（抽屉三档）


  // ======================================================== 兜底：失败态与可撤销



  it('关闭完成提示后给可撤销的 toast（不假装撤销删除这种不可逆动作）', async () => {
    const { task, detail } = completedFixture({ task: { last_read_page: null } })
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    wrapper = mountApp()
    await flushPromises()

    const banner = wrapper.find('.card.taskbar-ok')
    expect(banner.exists()).toBe(true)
    await buttonByText(banner, '关闭').trigger('click')
    await flushPromises()

    expect(wrapper.find('.card.taskbar-ok').exists()).toBe(false)
    const toast = wrapper.find('.toast.show')
    expect(toast.exists()).toBe(true)
    expect(toast.text()).toContain('已收起完成提示')

    await toast.find('button').trigger('click')
    await flushPromises()
    expect(wrapper.find('.card.taskbar-ok').exists()).toBe(true)
  })

  // ============================================================ 左栏（M0 第 6 步 / R4）
  //
  // `tests/rail.test.js` 盯的是**组件自己的形状与样式**；这里盯的是**挂进外壳之后**才成立的四条：
  // 开局是展开的、点按钮与 `Ctrl+B` 都能收、刷新后仍是收起态、左栏项点了真的会切页。
  // 之所以要这一层：收起态是"外壳的状态 + 布局类名"合起来才生效的，只测组件会漏掉漏挂 class 这类错。

  it('左栏：开局是展开态（260px），点收起按钮落到 58px 的 rail-min', async () => {
    wrapper = mountApp()
    await flushPromises()

    const layout = wrapper.find('.dw-layout')
    expect(layout.exists()).toBe(true)
    expect(wrapper.find('.rail').exists()).toBe(true)
    expect(layout.classes()).not.toContain('rail-min')

    await wrapper.find('.rail-toggle').trigger('click')
    await flushPromises()

    // 类名落在 `.dw-layout` 上——整个左栏的宽度与内容一起变，不是左栏自己缩
    expect(wrapper.find('.dw-layout').classes()).toContain('rail-min')
  })

  it('左栏：Ctrl+B 与点按钮等效（并且拦掉浏览器的默认行为）', async () => {
    wrapper = mountApp()
    await flushPromises()

    const event = new KeyboardEvent('keydown', { key: 'b', ctrlKey: true, cancelable: true })
    window.dispatchEvent(event)
    await flushPromises()

    expect(wrapper.find('.dw-layout').classes()).toContain('rail-min')
    // 不 preventDefault 的话浏览器会去开书签侧栏、焦点也丢了
    expect(event.defaultPrevented).toBe(true)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', ctrlKey: true, cancelable: true }))
    await flushPromises()
    expect(wrapper.find('.dw-layout').classes()).not.toContain('rail-min')
  })

  it('左栏：收起后重新挂载（= 刷新页面）仍是收起态，且用的是存下来的那份偏好', async () => {
    wrapper = mountApp()
    await flushPromises()
    await wrapper.find('.rail-toggle').trigger('click')
    await flushPromises()
    expect(localStorage.getItem('dw_rail_min')).toBe('1')

    // 模拟刷新：卸载再挂一次，地址与令牌都还在
    wrapper.unmount()
    wrapper = mountApp()
    await flushPromises()

    expect(wrapper.find('.dw-layout').classes()).toContain('rail-min')
    expect(wrapper.find('.rail-toggle').attributes('aria-label')).toContain('展开左栏')
  })

  it('左栏：选中态跟着地址走——历史记录亮「全部文献」，阅读区亮「读懂」', async () => {
    const { task, detail } = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    wrapper = mountApp()
    await flushPromises()

    // ⚠️ 2026-10-17：读懂工作台与历史记录**拆开**了。
    // 库页（我有什么）亮下段的「全部文献」；点进「读懂」才亮上段那个动词。
    const readItem = () => wrapper.findAll('button.rail-item').find((b) => b.text() === '读懂')
    const allItem = () => wrapper.findAll('button.rail-item').find((b) => b.text() === '全部文献')
    expect(allItem().classes()).toContain('on')
    expect(readItem().classes()).not.toContain('on')

    // 进阅读区：地址变成 #/read/:id，但仍在「读懂」这个模块里，选中态不该跳走
    await openReader(wrapper, '开始阅读')
    expect(wrapper.find('.screen-reader').exists()).toBe(true)
    expect(readItem().classes()).toContain('on')
  })

  it('左栏：点「写作」进写作页（M3 已接上），地址落到 #/write 且「写作」高亮', async () => {
    const { task, detail } = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    // 从 `#/read/:id` 出发，才看得出"地址真的被挪过去了"（本来就在 `#/` 的话不写也是对的）
    window.history.replaceState(null, '', `#/read/${task.id}`)
    wrapper = mountApp()
    await flushPromises()
    expect(window.location.hash).toBe(`#/read/${task.id}`)

    await wrapper.findAll('button.rail-item').find((b) => b.text() === '写作').trigger('click')
    await flushPromises()

    expect(window.location.hash).toBe('#/write')
    expect(wrapper.find('.wr-body').exists()).toBe(true)
    expect(wrapper.find('.screen-reader').exists()).toBe(false)
    const writeItem = () => wrapper.findAll('button.rail-item').find((b) => b.text() === '写作')
    expect(writeItem().classes()).toContain('on')
  })

  it('⭐ 左栏：点「记忆」真能打开记忆页（M7 做出来了，不再是"还没做"那条路）', async () => {
    const { task, detail } = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    window.history.replaceState(null, '', `#/read/${task.id}`)
    wrapper = mountApp()
    await flushPromises()

    await wrapper.findAll('button.rail-item').find((b) => b.text() === '记忆').trigger('click')
    await flushPromises()

    // 地址进到 `#/memory`，屏也真的换成记忆页（**不是**弹一句"还没做"再回库页）
    expect(window.location.hash).toBe('#/memory')
    expect(wrapper.find('.mem').exists()).toBe(true)
    expect(wrapper.find('.lib-wrap').exists()).toBe(false)
  })

  it('⭐ 直接输地址进 #/memory 也要真渲染记忆页（"地址变了、屏没变"是踩过的坑）', async () => {
    // ⚠️ 这条是实拍抓出来的：左栏点进去正常，但在地址栏直接输 `#/memory` 时
    // 只有 `hashchange` → `syncFromRoute()`；那里**少一条 memory 分支**就会
    // "地址对了、屏还是库页"。单测当时没覆盖这条路，所以红是后来补的。
    const { task, detail } = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    window.history.replaceState(null, '', '#/memory')
    wrapper = mountApp()
    await flushPromises()

    expect(wrapper.find('.mem').exists()).toBe(true)
    expect(wrapper.find('.lib-wrap').exists()).toBe(false)
  })

  it('左栏：每一项都点得动（R4 判据①），且不许把地址写到不知道的地方去', async () => {
    wrapper = mountApp()
    await flushPromises()

    const keys = wrapper.findAll('button.rail-item')
    expect(keys).toHaveLength(12)

    for (const item of keys) {
      await item.trigger('click')
      await flushPromises()
      // 路由表里只有这几个 name，落在别的上面说明拼地址时写错了
      expect(
        [
          '#/read/',
          '#/read',
          '#/collections',
          '#/tags',
          '#/trash',
          '#/write',
          '#/memory',
          '#/process',
          '#/me',
          '#/admin',
          '#/',
        ],
      ).toContain(
        [
          '#/read/',
          '#/read',
          '#/collections',
          '#/tags',
          '#/trash',
          '#/write',
          '#/memory',
          '#/process',
          '#/me',
          '#/admin',
          '#/',
        ].find((h) => window.location.hash.startsWith(h)),
      )
    }
  })

  // ============================================================ R6 手机端底部标签栏
  //
  // 形态 v2 §2.3：手机档（**<720px**）把左栏换成**底部标签栏 5 个** ——
  // **库 / 写作 / 检查 / 记忆 / 我的**（命名口径：桌面叫「校对」、手机显示「检查」；
  // 第一个叫「库」不叫「读懂」）。
  // ⚠️ 阈值：标签栏按文档那一档 **<720**，而 `stores/useUi.js` 的 `isNarrow` 是 **<1024** ——
  // 两者不一致是**已知问题**（由外壳负责人拍板），本卡按文档实现、**不动 `isNarrow`**，
  // 所以下面有一条"900px 宽不该出标签栏"的用例把这个边界钉住。

  it('R6：手机档（<720）出底部标签栏，恰好 5 个，名字逐字照形态 §2.3', async () => {
    const { task, detail } = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    setViewportWidth(390)
    wrapper = mountApp()
    await flushPromises()

    const tabbar = wrapper.find('.tabbar')
    expect(tabbar.exists()).toBe(true)
    expect(tabbar.attributes('aria-label')).toBe('底部导航')
    expect(tabbar.findAll('button.tabbar-item')).toHaveLength(5)
    // ⚠️ 逐字对文档：第一个是「库」不是「读懂」；桌面叫「校对」、这里显示「检查」
    expect(tabbar.findAll('.tabbar-lbl').map((n) => n.text())).toEqual([
      '库',
      '写作',
      '检查',
      '记忆',
      '我的',
    ])
    // 当前所在模块要亮着（开局在库页 → 第一个亮）
    expect(tabbar.findAll('button.tabbar-item')[0].classes()).toContain('on')
  })

  it('R6：≥720 不渲染标签栏（手机档以形态文档的 <720 为准，不是 isNarrow 的 1024）', async () => {
    const { task, detail } = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    // 900px 属于"左栏收成 58px 图标态"那一档，底部标签栏还不该出现
    setViewportWidth(900)
    wrapper = mountApp()
    await flushPromises()

    expect(wrapper.find('.tabbar').exists()).toBe(false)
    // 反向对照：抽屉/左栏那些窄屏档位仍按 `isNarrow`（<1024）走，没被本卡改动
    expect(wrapper.find('.dw-layout').exists()).toBe(true)
  })

  it('R6：标签栏固定在视口底、不被 100dvh 布局吃掉，且内容与抽屉都让位（含安全区）', async () => {
    const { task, detail } = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    setViewportWidth(390)
    wrapper = mountApp()
    await flushPromises()

    // ① 结构：挂载点在 `.dw-layout`（`100dvh` + `overflow:hidden`）**之外** ——
    //    放进去会被裁掉；留在外面又必须 fixed，否则排到 100dvh 之后（屏幕外）
    expect(wrapper.find('.dw-layout .tabbar').exists()).toBe(false)
    expect(wrapper.find('.dw > .tabbar').exists()).toBe(true)
    // ② 根上有 has-tabbar：内容列据此让出等高下边距（**JS 决定"有没有"，CSS 只管几何**）
    expect(wrapper.find('.dw').classes()).toContain('has-tabbar')

    // ③ 样式：fixed 贴底 + 三处让位都算了安全区 + 触控热区 ≥44px
    const css = srcText('style.css')
    const section = css.slice(css.indexOf('[R6] 手机端底部标签栏'))
    expect(section.length).toBeGreaterThan(0)
    expect(section).toMatch(/\.dw \.tabbar \{[^}]*position: fixed/)
    expect(section).toMatch(/env\(safe-area-inset-bottom, 0px\)/)
    expect(section).toMatch(
      /\.dw\.has-tabbar \.dw-main \{[^}]*padding-bottom: calc\(var\(--tabbar-h\)/,
    )
    expect(section).toMatch(/\.dw\.has-tabbar \.sheet \{[^}]*bottom: calc\(var\(--tabbar-h\)/)
    expect(section).toMatch(/\.dw \.tabbar-item \{[^}]*min-height: 44px/)
  })

  it('R6：点「检查」真切页（进写作页并当场拉开检查抽屉），点「我的」进个人中心', async () => {
    const { task, detail } = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    setViewportWidth(390)
    wrapper = mountApp()
    await flushPromises()

    const tabByLabel = (label) =>
      wrapper.findAll('button.tabbar-item').find((b) => b.text().includes(label))

    // 形态 §3.3：校对是**写作页里的抽屉**、不是独立页面 —— 所以一条用例同时验两件事
    await tabByLabel('检查').trigger('click')
    await flushPromises()
    expect(wrapper.find('.screen-write').exists()).toBe(true)
    expect(wrapper.find('.wr-check').exists()).toBe(true)
    // 亮的是「检查」不是「写作」（两者都在写作页，靠抽屉开没开来分辨）
    expect(tabByLabel('检查').classes()).toContain('on')

    await tabByLabel('我的').trigger('click')
    await flushPromises()
    expect(window.location.hash).toBe('#/me')
    expect(wrapper.find('.screen-me').exists()).toBe(true)
    expect(tabByLabel('我的').classes()).toContain('on')
  })

  // ============================================================ R7 左栏账号区
  //
  // 形态 v2 §1.2 布局图第 60 行：`│ 小研 ›   │  ← 账号区（点进个人中心，进入后高亮）`；
  // M0 判据原文：「**账号区点进个人中心且进入后高亮**」。
  // 这一卡之前是**空插槽**（`<template #account />`），所以桌面端一直只能从顶栏账号菜单进个人中心。

  it('R7：账号区露出现在是谁，而且是**原生可点**的（键盘可达，不许 div+@click）', async () => {
    setViewportWidth(1440)
    wrapper = mountApp()
    await flushPromises()

    const account = wrapper.find('button.rail-account')
    expect(account.exists()).toBe(true)
    expect(account.element.tagName).toBe('BUTTON')
    expect(account.attributes('type')).toBe('button')
    // 显示的是外壳那份 `accountLabel`（`tester（普通用户）`），**不是**另拼一套名字
    expect(account.text()).toContain('tester')
    // 首字头像：收起态就靠它（`.rail-lbl` 会被既有的 `.rail-min .rail-lbl` 藏掉）
    expect(account.find('.rail-av').text()).toBe('t')
    // 还没进个人中心 → 不该亮
    expect(account.classes()).not.toContain('on')
  })

  it('R7：点账号区进 `#/me`，到了那里要**亮**（与左栏同一套选中态，且读屏也知道是当前页）', async () => {
    setViewportWidth(1440)
    wrapper = mountApp()
    await flushPromises()

    await wrapper.find('button.rail-account').trigger('click')
    await flushPromises()

    expect(window.location.hash).toBe('#/me')
    expect(wrapper.find('.screen-me').exists()).toBe(true)
    const account = wrapper.find('button.rail-account')
    expect(account.classes()).toContain('on')
    expect(account.attributes('aria-current')).toBe('page')
  })

  it('R7：账号区不借 `.rail-item` 类名，且收起态只留首字头像（靠既有 `.rail-min .rail-lbl`）', () => {
    const rail = srcText('components/AppRail.vue')
    const accountSrc = srcText('components/RailAccount.vue')
    const css = srcText('style.css')
    const section = css.slice(css.indexOf('[R7] 左栏账号区'))

    // ⚠️ 借用 `.rail-item` 会把那条「恰好 12 个」的用例数成 13
    expect(accountSrc).not.toMatch(/class="rail-item/)
    // 座位还在（R4 留的具名插槽），只是外壳把它填上了
    expect(rail).toContain('<slot name="account" />')
    expect(srcText('App.vue')).toMatch(/<RailAccount[\s\S]*?:label="accountLabel"/)
    // 与 `.rail-item` 同一套交互，一个都不能少
    expect(section).toMatch(/\.dw \.rail-account \{[^}]*display: flex/)
    expect(section).toMatch(/\.dw \.rail-account\.on \{/)
    expect(section).toMatch(/\.dw \.rail-account:focus-visible \{/)
    // 收起态：只藏名字（`.rail-lbl` 走既有规则）、留头像；`›` 也藏
    expect(section).toMatch(/\.dw \.rail-min \.rail-account \.rail-arrow \{ display: none; \}/)
    expect(section).toMatch(/\.dw \.rail-av \{[^}]*width: 22px/)
  })

  it('R9：字体栈与两个渲染开关只挂 `.dw`，且是 style.css 的最后一段', () => {
    const css = srcText('style.css')
    const at = css.indexOf('[R9] 字体栈与渲染开关')
    expect(at, 'style.css 里没有 [R9] 那一段').toBeGreaterThan(-1)

    const section = css.slice(at)
    // ① 位置：契约 §4.3 第 5 条要求字体栈"最后一步"做（字体一改，字宽/换行/截断全变，
    //    提前放会污染前面每一步的逐屏比对）——这一段之后不许再有别的卡片的段。
    expect(section.match(/\[[A-Z]\d+\] /g)).toEqual(['[R9] '])
    // ②～⑤ 都对着**去掉注释**的代码断言：注释里会举例写 `.dw { font: … }`，
    //    不剥掉的话"不许写 font 简写"那条会被自己的注释绊倒（踩过一次）。
    //    ⚠️ R9 的标记本身就在注释里（`/* === [R9] … === */`），切片之后没有配对的 `/*`，
    //       所以先切掉"从标记到第一个 `*/`"这一截，再剥掉后面可能出现的整段注释。
    const code = section.replace(/^[\s\S]*?\*\//, '').replace(/\/\*[\s\S]*?\*\//g, '')
    // ② 字体栈：四档顺序照设计规范，一个都不能少
    expect(code).toMatch(
      /--font-sans:\s*[\s\S]*?system-ui,[\s\S]*?-apple-system,[\s\S]*?"PingFang SC",[\s\S]*?"Microsoft YaHei",[\s\S]*?"Noto Sans CJK SC",[\s\S]*?sans-serif;/,
    )
    expect(code).toMatch(/\.dw\s*\{[^}]*font-family:\s*var\(--font-sans\)/)
    // ③ 只换字体：不许顺手写 `font` 简写（字号 / 行高留在上面的段里，改了会有跳变）
    expect(code).not.toMatch(/\bfont:\s/)

    // ④ 两个渲染开关都在
    expect(code).toMatch(/-webkit-font-smoothing:\s*antialiased/)
    expect(code).toMatch(/text-rendering:\s*optimizeLegibility/)

    // ⑤ ⚠️ 不许污染登录页 / 管理后台：这一段里每个选择器都必须以 `.dw` 开头。
    const selectors = [...code.matchAll(/([^{}]+)\{/g)].map((m) => m[1].trim())
    expect(selectors.length).toBeGreaterThan(0)
    expect(selectors.filter((sel) => !sel.startsWith('.dw'))).toEqual([])
  })
})
