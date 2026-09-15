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
const FAKE_PAGES = {
  dual: [
    {
      n: 1,
      items: [{ str: 'first block', x: 10, y: 100, w: 66 }],
    },
    {
      n: 2,
      items: [
        { str: 'third block', x: 10, y: 100, w: 66 },
        { str: 'second block', x: 10, y: 80, w: 72 },
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

function fakeDocument(tag) {
  const pages = FAKE_PAGES[tag] || FAKE_PAGES.dual
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

/** reader-top 里的下拉菜单没有 id，靠"触发按钮的文字"找它。 */
function menuWrapByButton(wrapper, text) {
  return wrapper
    .findAll('.reader-top .menu-wrap')
    .find((m) => m.find('button.btn').exists() && m.find('button.btn').text() === text)
}

/** 打开一篇论文的阅读工作区：完成态点卡片按钮，进行中点任务条上的文件名。 */
async function openReader(wrapper, label) {
  const btn = buttonByText(wrapper, label)
  expect(btn, `没找到「${label}」入口`).toBeTruthy()
  await btn.trigger('click')
  await flushPromises()
}

describe('App.vue 页面渲染', () => {
  let wrapper = null

  beforeEach(() => {
    localStorage.clear()
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

  // ======================================================== 屏 ①：L1 空库

  it('L1 空库：hero 三枚可点描边按钮 + 原型 upload-card（drop / seg），且不出网格', async () => {
    globalThis.fetch = stubFetch({ tasks: [] })
    wrapper = mountApp()
    await flushPromises()

    // 结构照原型：#screen-lib-empty → .topbar + .lib-wrap(.hero + .card.upload-card)
    expect(wrapper.find('.topbar').exists()).toBe(true)
    expect(wrapper.find('.lib-wrap .hero').exists()).toBe(true)
    expect(wrapper.find('.hero h1').text()).toBe('把文献读懂')
    expect(wrapper.find('.hero .tagline').exists()).toBe(true)
    expect(wrapper.findAll('.pills button.pill').length).toBe(3)
    expect(wrapper.findAll('.pills button.pill').every((b) => b.attributes('disabled') === undefined)).toBe(true)

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
    expect(segText).toContain('精档 · 最准')
    expect(upload.find('.tier-note').exists()).toBe(true)
    expect(upload.text()).not.toContain('慢档')

    // 空库不出论文网格与标题行
    expect(wrapper.find('.grid3').exists()).toBe(false)
    expect(wrapper.find('.title-row').exists()).toBe(false)

    for (const leak of SOURCE_LEAKS) {
      expect(wrapper.text()).not.toContain(leak)
    }
    for (const legacy of FORBIDDEN_LEGACY) {
      expect(wrapper.html()).not.toContain(legacy)
    }
  })

  it('L1 空库：三枚标签点了要说话（当前没有可读论文时不许装作打开了）', async () => {
    globalThis.fetch = stubFetch({ tasks: [] })
    wrapper = mountApp()
    await flushPromises()

    const drop = wrapper.find('.upload-card .drop')
    expect(drop.classes()).not.toContain('drop-over')

    await wrapper.findAll('.pills button.pill')[0].trigger('click')
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
    expect(wrapper.find('.title-row h2').text()).toBe('我的论文（3 篇）')
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
    expect(buttonByText(top, '⤓ 下载译稿 ▾')).toBeTruthy()
    expect(buttonByText(top, '🔍 搜索')).toBeTruthy()
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
    expect(wrapper.find('.assist .composer textarea').exists()).toBe(true)
    expect(wrapper.find('.assist .composer button.btn.primary').text()).toBe('↑')

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

  it('「⋯」菜单照原型是单层级 6 项；下载入口只有一个「下载译稿 ▾」两项', async () => {
    const { task, detail } = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    const more = menuWrapByButton(wrapper, '⋯')
    expect(more, 'reader-top 里没有 ⋯ 菜单').toBeTruthy()
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

    const dl = menuWrapByButton(wrapper, '⤓ 下载译稿 ▾')
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

  it('出处一律说人话：显示「第 X 页 · 第 Y 段」而不是块编号，且段号按页内重算 + 点击必闪烁', async () => {
    const { task, detail } = completedFixture()
    const answer = {
      answer: '按原文所述，这条结论有两条局限。',
      source_block_ids: ['p1_b2'],
      mode: 'full',
    }
    globalThis.fetch = stubFetch({ tasks: [task], detail, ask: answer })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    // 快捷提问 chips 只放"导读与术语都没答"的问题
    const chip = buttonByText(wrapper, '局限与不足')
    expect(chip).toBeTruthy()
    expect(wrapper.find('.chips-hint').text()).toContain('导读')

    await chip.trigger('click')
    await flushPromises()

    const text = wrapper.text()
    // p1_b2 的全局块序是 2，但它是**第 2 页的第 1 段**——直接把 b 当段号就会显示"第 3 段"
    expect(text).toContain('第 2 页 · 第 1 段')
    expect(text).not.toContain('p1_b2') // 块编号只留在 title 里，不出现在界面文本

    // 问答线程的结构：.turn > .bubble-q + .bubble-a(.srcs > .src-tag) + .a-tools
    const turn = wrapper.find('.assist .turn')
    expect(turn.exists()).toBe(true)
    expect(turn.find('.bubble-q').text()).toBe('这项研究有什么局限？')
    expect(turn.find('.bubble-a').exists()).toBe(true)
    const srcTag = turn.find('.srcs .src-tag')
    expect(srcTag.exists()).toBe(true)
    expect(srcTag.text()).toBe('第 2 页 · 第 1 段 ▸')
    expect(srcTag.attributes('title')).toBe('原文块 p1_b2')
    expect(turn.findAll('.a-tools button').map((b) => b.text())).toEqual(['复制答案', '展开原文'])

    // P0 的"信任签名"：点出处 → 目标段滚入视口中部 + 高亮脉冲一次
    await srcTag.trigger('click')
    await flushPromises()
    const target = wrapper.find('.doc-pane p#p1_b2')
    expect(target.exists()).toBe(true)
    expect(target.classes()).toContain('flash')
    expect(target.classes()).toContain('anchor')

    for (const leak of SOURCE_LEAKS) {
      expect(wrapper.text()).not.toContain(leak)
    }
  })

  it('PDF 模式：点出处 → 在 PDF 文字层里定位到那一段并高亮；点 PDF 的段落 → 就这段提问', async () => {
    const { task, detail } = completedFixture()
    const answer = { answer: '按原文所述。', source_block_ids: ['p1_b2'], mode: 'full' }
    globalThis.fetch = stubFetch({ tasks: [task], detail, ask: answer })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    // 切到「双语 PDF」（渲染方式菜单：.reader-top 里那颗 chip，不是 .btn）
    const modeWrap = wrapper
      .findAll('.reader-top .menu-wrap')
      .find((m) => m.text().includes('段落精读'))
    expect(modeWrap, 'reader-top 里没有渲染方式菜单').toBeTruthy()
    await modeWrap.find('.chip').trigger('click')
    const dual = modeWrap.findAll('.menu button').find((b) => b.text().includes('双语'))
    expect(dual, '渲染方式菜单里没有双语 PDF').toBeTruthy()
    await dual.trigger('click')
    await flushPromises()

    // 左栏是 pdf.js 的视图（有文字层），不再是 iframe
    expect(wrapper.find('.doc-pane .pdf-pane').exists()).toBe(true)
    expect(wrapper.find('.doc-pane iframe').exists()).toBe(false)
    expect(wrapper.findAll('.pdf-page').length).toBe(2)

    // 点一条出处（p1_b2 的块文本是 third block，在第 2 页）→ 高亮框画出来
    await buttonByText(wrapper, '局限与不足').trigger('click')
    await flushPromises()
    await wrapper.find('.assist .srcs .src-tag').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.pdf-hl').length).toBe(1)
    expect(wrapper.text()).toContain('已在 PDF 里定位到 第 2 页 · 第 1 段')

    // 点 PDF 里的某一行 → 浮出「就这段提问」→ 带着这一段去提问
    const pageTwo = wrapper.find('.pdf-page[data-page="2"]')
    await pageTwo.trigger('click', { clientX: 15, clientY: 95 })
    const chip = wrapper.find('.pdf-chip')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toBe('就这段提问')
    await chip.trigger('click')
    await flushPromises()

    const turn = wrapper.findAll('.assist .turn').at(-1)
    expect(turn.find('.bubble-q').text()).toBe('就这段提问：third block')
    // 能对上块就用块编号当锚点（提问锚点与出处同一坐标系）
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/ask'),
      expect.objectContaining({ body: expect.stringContaining('"focus_block_ids":["p1_b2"]') }),
    )
  })

  it('纯中文稿对不上块文本时：只翻页，绝不假高亮（如实说为什么）', async () => {
    const { task, detail } = completedFixture()
    // 出处指向第 2 页的块；纯中文稿里是中文译文，块里存的是英文原文 → 本来就对不上
    const answer = { answer: '按原文所述。', source_block_ids: ['p1_b2'], mode: 'full' }
    globalThis.fetch = stubFetch({ tasks: [task], detail, ask: answer })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    const modeWrap = wrapper
      .findAll('.reader-top .menu-wrap')
      .find((m) => m.text().includes('段落精读'))
    await modeWrap.find('.chip').trigger('click')
    await modeWrap.findAll('.menu button').find((b) => b.text().includes('纯中文')).trigger('click')
    await flushPromises()

    expect(wrapper.find('.pdf-pane').exists()).toBe(true)
    await buttonByText(wrapper, '局限与不足').trigger('click')
    await flushPromises()
    await wrapper.find('.assist .srcs .src-tag').trigger('click')
    await flushPromises()

    // 一个高亮框都不许画
    expect(wrapper.findAll('.pdf-hl').length).toBe(0)
    expect(wrapper.find('.assist .honest').text()).toContain('没能在这份 PDF 的文字层里对上')
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
    expect(traceBtn.text()).toBe('看原文（第 1 页 · 第 1 段）▸')
    expect(traceBtn.attributes('disabled')).toBeUndefined()

    // 无出处：置灰、disabled、没有箭头，并有一句说明
    const deadBtn = cards[3].find('.ops button.dead')
    expect(deadBtn.exists()).toBe(true)
    expect(deadBtn.text()).toBe('无单一段落出处')
    expect(deadBtn.attributes('disabled')).toBeDefined()
    expect(deadBtn.text()).not.toContain('▸')
    expect(cards[3].find('.dead-note').text()).toContain('由全文综合而成')

    // 每条要点都有「就这条追问」
    expect(cards[0].find('.ops button:nth-child(2)').text()).toBe('就这条追问')

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

    // 命中 → 回填「已定位 · 第 X 页 · 第 Y 段」+ 跳过去闪烁
    await hitBtn.trigger('click')
    await flushPromises()
    expect(terms[0].find('.ops button').text()).toBe('已定位 · 第 1 页 · 第 1 段')
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

  it('手机端：段落视图（段 N + 跨页分隔条）+ 底部抽屉三档 + 点段号浮出「就这段提问」', async () => {
    const { task, detail } = completedFixture()
    globalThis.fetch = stubFetch({ tasks: [task], detail })
    setViewportWidth(420)
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    // 手机主视图 = 按块重排的段落视图（不是桌面那套 .page/.cols）
    expect(wrapper.find('.doc-pane').exists()).toBe(false)
    const mobile = wrapper.find('.mobile-reader')
    expect(mobile.exists()).toBe(true)
    expect(mobile.find('.ptop .fname').text()).toBe('paper.pdf')
    expect(mobile.find('.progress-line .pl-bar').exists()).toBe(true)
    expect(mobile.find('.reader-ctrls').text()).toContain('字号')
    expect(mobile.find('.pdoc').exists()).toBe(true)

    // 窄屏上桌面的那条 reader-top / 细进度条整条不渲染——原型的手机屏只有 .ptop，
    // 两条顶栏叠在一起会把首屏挤掉一百多像素（这是照原型比对时抓出来的偏差）
    expect(wrapper.find('.reader-top').exists()).toBe(false)
    expect(wrapper.find('.thin-bar').exists()).toBe(false)
    // 但下载与 ⋯ 一个都不能少：它们跟着搬到手机顶栏上（入口名字不变）
    expect(mobile.findAll('.ptop .menu-wrap').length).toBe(2)
    const mobileMore = mobile
      .findAll('.ptop .menu-wrap')
      .find((m) => m.find('button').text() === '⋯')
    expect(mobileMore.findAll('.menu button').map((b) => b.text())).toEqual([
      '文档信息',
      '重试翻译（本档）',
      '换档位重译…',
      '详情',
      '问题反馈…',
      '删除…',
    ])
    const mobileDl = mobile
      .findAll('.ptop .menu-wrap')
      .find((m) => m.find('button').text() === '⤓')
    expect(mobileDl.findAll('.menu button').map((b) => b.text())).toEqual(['下载双语稿', '下载纯中文稿'])

    // 手机上的「原版」真的能看图：切到 pdf.js 视图（同一份产物，不是另做一套渲染），再切回段落视图
    // 按钮名写的是它真打开的那一份（外文文献默认双语稿；写「原版」会让人以为看到英文原稿）
    const toPdf = wrapper.findAll('.ptop button').find((b) => b.text() === '双语稿')
    expect(toPdf, '手机顶栏没有"看 PDF"的入口').toBeTruthy()
    await toPdf.trigger('click')
    await flushPromises()
    expect(wrapper.find('.mobile-reader .pdoc').exists()).toBe(false)
    expect(wrapper.find('.mobile-reader .pdoc-pdf .pdf-pane').exists()).toBe(true)
    await wrapper.findAll('.ptop button').find((b) => b.text() === '段落').trigger('click')
    await flushPromises()
    expect(wrapper.find('.mobile-reader .pdoc').exists()).toBe(true)

    // 段号写「段 N」，跨页处插页分隔条——让「第 X 页 · 第 Y 段」在手机上找得到
    expect(wrapper.findAll('.pdoc .pg .seg-no').map((s) => s.text())).toEqual(['段 1', '段 2', '段 1'])
    expect(wrapper.find('.pdoc .pg-sep').text()).toBe('第 2 页')

    // 助手变底部抽屉，默认 peek 档
    const sheet = wrapper.find('.sheet')
    expect(sheet.exists()).toBe(true)
    expect(sheet.classes()).toContain('peek')
    expect(sheet.find('.grip').exists()).toBe(true)
    expect(sheet.find('.peek-summary').text()).toContain('点段落浮出')
    expect(sheet.find('.composer textarea').exists()).toBe(true)

    // grip 循环三档：peek → half（无档位类）→ full → peek
    await sheet.find('.grip').trigger('click')
    expect(wrapper.find('.sheet').classes()).not.toContain('peek')
    expect(wrapper.find('.sheet').classes()).not.toContain('full')
    expect(wrapper.find('.sheet .grip span').text()).toBe('上拖到近全屏')
    await wrapper.find('.sheet .grip').trigger('click')
    expect(wrapper.find('.sheet').classes()).toContain('full')
    expect(wrapper.find('.sheet .grip span').text()).toBe('下拖回到半屏')
    await wrapper.find('.sheet .grip').trigger('click')
    expect(wrapper.find('.sheet').classes()).toContain('peek')

    // 触发热区只有段号本身：点段号 → 浮出「就这段提问」
    const segBtn = wrapper.find('.pdoc .seg-btn')
    expect(segBtn.exists()).toBe(true)
    await segBtn.trigger('click')
    const chip = wrapper.find('.pg-chip')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toBe('就这段提问')

    // 点它 → 抽屉升到半屏 + 带着这一段去提问
    await chip.trigger('click')
    await flushPromises()
    expect(wrapper.find('.sheet').classes()).not.toContain('peek')
    expect(wrapper.find('.turn .bubble-q').text()).toContain('就这段提问')

    for (const leak of SOURCE_LEAKS) {
      expect(wrapper.text()).not.toContain(leak)
    }
    for (const legacy of FORBIDDEN_LEGACY) {
      expect(wrapper.html()).not.toContain(legacy)
    }
  })

  // ======================================================== 兜底：失败态与可撤销

  it('问答失败态：人话 + 保留问题原文 + 重试按钮', async () => {
    const { task, detail } = completedFixture()
    globalThis.fetch = vi.fn(async (input, init = {}) => {
      const url = typeof input === 'string' ? input : String(input?.url ?? input)
      if (url.includes('/ask')) return { ok: false, status: 503, json: async () => ({ detail: '服务繁忙' }) }
      return stubFetch({ tasks: [task], detail })(input, init)
    })
    wrapper = mountApp()
    await flushPromises()
    await buttonByText(wrapper, '继续读').trigger('click')
    await flushPromises()

    await buttonByText(wrapper, '主要结果').trigger('click')
    await flushPromises()

    const fail = wrapper.find('.assist .fail-card')
    expect(fail.exists()).toBe(true)
    expect(fail.text()).toContain('没答出来，通常是网络或服务繁忙')
    expect(fail.text()).toContain('你的问题已保留：「主要结果是什么？」')
    expect(fail.find('button.btn.primary').text()).toBe('重试')
    // 问题气泡还在（不静默吞掉用户的问题）
    expect(wrapper.find('.assist .turn .bubble-q').text()).toBe('主要结果是什么？')
  })

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
})
