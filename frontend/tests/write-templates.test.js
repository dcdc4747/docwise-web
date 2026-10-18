/**
 * 写作模板（结构骨架）的用例 —— 2026-10-19 用户取消"不代写"红线之后新增的那一层。
 *
 * 盯三件事：
 * ① ⭐ **骨架只给结构**：每个 section 一行 `## 标题` + 一行 `<!-- 写作提示：… -->`，
 *    除这两类行之外**没有别的文字行**——"没有一句成文的正文"这条边界靠它守着；
 * ② 三个模板都在、章节都不空、`note` 与章节标题逐条对得上（菜单上那一行不许飘）；
 * ③ 组件级：选模板**不动正文** → 出现提示条 → 点「写入骨架」才落字、`saveState` 变 dirty，
 *    并且能撤销回写入前那一版。
 *
 * 桩子照 `tests/write-view.test.js` 的 `stubWriteFetch` / `mountWrite` 抄了一个**最小版**：
 * 只伺候写作页要的那几个端点（health / me / materials / drafts）。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WriteView from '../src/views/WriteView.vue'
import { clearTasks } from '../src/stores/useTasks'
import { disposeUi, runToastUndo, toast } from '../src/stores/useUi'
import { resetWrite, saveState } from '../src/stores/useWrite'
import { buildSkeleton, templateById, WRITE_TEMPLATES } from '../src/writeTemplates'

/** 写作页的源码：只有"撤销窗口用的是哪个常量"这一条需要看源码（那个常量不从组件导出）。 */
const WRITE_SRC = readFileSync(resolve(process.cwd(), 'src/views/WriteView.vue'), 'utf8')

const HEALTH = {
  status: 'ok',
  service: 'docwise-web',
  checks: { database: true, worker: true },
  queue_size: 0,
  running_task_id: null,
  auth: { demo_autologin: false, session_days: 30 },
}

const USER = { id: 1, username: 'tester', display_name: '测试用户', role: 'user' }

function jsonOf(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data }
}

function draftFixture(overrides = {}) {
  return {
    id: 1,
    title: '开题报告',
    body_md: '# 开题报告\n\n出处的意义。\n',
    template_id: null,
    updated_at: '2026-10-19T02:00:00Z',
    citations: [],
    ...overrides,
  }
}

/**
 * 写作页要的最少几个端点的假后端（POST 会真的往列表里加一份，后面的 PATCH 才找得到它）。
 * `calls` 记下每次请求，用例靠它断言"到底打没打、带了什么"。
 */
function stubWriteFetch(options = {}) {
  const state = {
    drafts: options.drafts ? [...options.drafts] : [],
    nextDraftId: 90,
  }
  const calls = []
  const impl = vi.fn(async (input, init = {}) => {
    const url = typeof input === 'string' ? input : String(input?.url ?? input)
    const method = (init.method || 'GET').toUpperCase()
    const body = init.body ? JSON.parse(init.body) : null
    calls.push({ method, url, body })

    if (url.includes('/api/health')) return jsonOf(HEALTH)
    if (url.includes('/api/auth/me')) return jsonOf(USER)
    if (url.includes('/api/materials')) return jsonOf({ items: [] })
    if (url.includes('/api/drafts')) {
      const idMatch = /\/api\/drafts\/(\d+)$/.exec(url)
      if (idMatch && method === 'PATCH') {
        const host = state.drafts.find((item) => item.id === Number(idMatch[1]))
        if (!host) return jsonOf({ detail: '草稿不存在' }, 404)
        if (body.title !== undefined) host.title = body.title
        if (body.body_md !== undefined) host.body_md = body.body_md
        return jsonOf({ ...host })
      }
      if (method === 'POST') {
        const created = {
          id: state.nextDraftId++,
          title: body.title,
          body_md: '',
          template_id: body.template_id ?? null,
          updated_at: '2026-10-19T03:00:00Z',
          citations: [],
        }
        state.drafts = [created, ...state.drafts]
        return jsonOf(created, 201)
      }
      return jsonOf({ items: state.drafts })
    }
    if (url.includes('/api/tasks')) return jsonOf([])
    return jsonOf({})
  })
  return { impl, calls, state }
}

function mountWrite() {
  return mount(WriteView, { attachTo: document.body })
}

/** 走「模板…」打开面板，选中第 `index` 个内置模板。 */
async function pickTemplate(wrapper, index = 0) {
  await wrapper.findAll('button').find((b) => b.text() === '模板…').trigger('click')
  await flushPromises()
  const items = wrapper.findAll('.wr-tpl-item')
  expect(items.length, '模板面板里没有内置模板').toBeGreaterThan(index)
  await items[index].trigger('click')
  await flushPromises()
}

function barButton(wrapper, text) {
  return wrapper.findAll('.wr-tplbar button').find((b) => b.text().includes(text))
}

beforeEach(() => {
  localStorage.clear()
  window.history.replaceState(null, '', '#/write')
  globalThis.fetch = stubWriteFetch().impl
  resetWrite()
  clearTasks()
})

afterEach(() => {
  disposeUi()
  vi.restoreAllMocks()
  resetWrite()
  clearTasks()
  document.body.innerHTML = ''
})

describe('模板数据：三个模板都在', () => {
  it('id 就是草稿上存的三个标识（老的两个没改名），name 是中文场景名', () => {
    expect(WRITE_TEMPLATES.map((item) => item.id)).toEqual([
      'tpl-journal',
      'tpl-thesis',
      'tpl-report',
    ])
    expect(WRITE_TEMPLATES.map((item) => item.name)).toEqual([
      '期刊论文',
      '学位论文',
      '研究报告',
    ])
  })

  it('每个模板的 sections 非空，heading 与 hint 都不是空串', () => {
    for (const template of WRITE_TEMPLATES) {
      expect(template.sections.length, `${template.id} 没有章节`).toBeGreaterThan(0)
      for (const section of template.sections) {
        expect(section.heading.trim(), `${template.id} 有空标题`).not.toBe('')
        expect(section.hint.trim(), `${template.id} 的「${section.heading}」没有提示`).not.toBe('')
      }
    }
  })

  it('note（菜单上那一行）与章节标题逐条对得上——不许飘', () => {
    for (const template of WRITE_TEMPLATES) {
      for (const section of template.sections) {
        expect(template.note, `${template.id} 的 note 里缺「${section.heading}」`).toContain(
          section.heading,
        )
      }
    }
  })

  it('templateById：认识就给整份，不认识返回 null（不编一个空模板）', () => {
    expect(templateById('tpl-thesis').name).toBe('学位论文')
    expect(templateById('tpl-report').sections.length).toBeGreaterThan(0)
    expect(templateById('tpl-nope')).toBeNull()
    expect(templateById(undefined)).toBeNull()
  })
})

describe('buildSkeleton：只给结构，不给正文', () => {
  it('每个 section 都输出 ## 标题 与 <!-- 写作提示', () => {
    for (const template of WRITE_TEMPLATES) {
      const out = buildSkeleton(template.id)
      for (const section of template.sections) {
        expect(out, `${template.id} 缺「${section.heading}」`).toContain(`## ${section.heading}`)
      }
      const hints = out.match(/<!-- 写作提示/g) || []
      expect(hints.length, `${template.id} 的提示行数与章节数对不上`).toBe(
        template.sections.length,
      )
    }
  })

  it('⭐ 除标题行与提示行外没有别的文字行（一份骨架里一句成文的正文都没有）', () => {
    for (const template of WRITE_TEMPLATES) {
      const lines = buildSkeleton(template.id)
        .split('\n')
        .filter((line) => line.trim())
      const strays = lines.filter(
        (line) => !line.startsWith('## ') && !line.startsWith('<!-- 写作提示'),
      )
      expect(strays, `${template.id} 的骨架里混进了正文：\n${strays.join('\n')}`).toEqual([])
    }
  })

  it('给了 title 就以 # 起头（且压成一行）；没给就不硬造一行标题', () => {
    const withTitle = buildSkeleton('tpl-report', { title: '  2026 年\n校园阅读 报告 ' })
    // 标题只能是一行：换行会把它拆成两行 markdown，第二行就不是标题了
    expect(withTitle.split('\n')[0]).toBe('# 2026 年 校园阅读 报告')
    expect(buildSkeleton('tpl-report').startsWith('## 问题')).toBe(true)
  })

  it('不认识的 id 返回空串（宁可什么都没有，也不编一份骨架出来）', () => {
    expect(buildSkeleton('tpl-nope')).toBe('')
    expect(buildSkeleton('')).toBe('')
  })
})

describe('写作页：选模板 → 提示条 → 写入骨架', () => {
  it('选模板**不动正文**，只出现提示条（模板名 + 写入骨架 / 取消）', async () => {
    const { impl, calls } = stubWriteFetch({ drafts: [] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    await pickTemplate(wrapper, 0)

    // 老行为保留：模板标识仍然记在草稿上（契约 §2.7）
    const post = calls.find((c) => c.method === 'POST' && c.url.endsWith('/api/drafts'))
    expect(post.body.template_id).toBe('tpl-journal')
    // 正文一个字都没动
    expect(wrapper.find('.wr-editor').element.value).toBe('')

    const bar = wrapper.find('.wr-tplbar')
    expect(bar.exists()).toBe(true)
    expect(bar.text()).toContain('模板：期刊论文')
    expect(bar.text()).toContain('写入骨架')
    expect(bar.text()).toContain('取消')
    wrapper.unmount()
  })

  it('⭐ 点「写入骨架」：textarea 里出现每个章节的标题与提示，saveState 变 dirty', async () => {
    const { impl } = stubWriteFetch({ drafts: [] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    await pickTemplate(wrapper, 0)
    await barButton(wrapper, '写入骨架').trigger('click')
    await flushPromises()

    const text = wrapper.find('.wr-editor').element.value
    for (const section of templateById('tpl-journal').sections) {
      expect(text, `正文里缺「${section.heading}」`).toContain(`## ${section.heading}`)
    }
    expect(text).toContain('<!-- 写作提示')
    // "未命名草稿"是占位名：不许被当成 # 一级标题写进正文
    expect(text.startsWith('## 题名')).toBe(true)
    // 标脏（存不存由用户按「保存」决定，这里不偷偷存库）
    expect(saveState.value).toBe('dirty')
    // 给了一次撤销（全站同一个提示条）
    expect(toast.value.undoLabel).toBe('撤销')
    expect(toast.value.text).toContain('骨架')
    // 一次性动作：写完提示条收起，避免手滑再写一遍
    expect(wrapper.find('.wr-tplbar').exists()).toBe(false)
    wrapper.unmount()
  })

  it('正文非空时**追加**在末尾，并先空一行（不覆盖已经写下的字）', async () => {
    const { impl } = stubWriteFetch({ drafts: [] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    await pickTemplate(wrapper, 0)
    // 选了模板之后用户又写了一句（提示条还在，骨架还没写）
    await wrapper.find('.wr-editor').setValue('先写的这一句。')
    await flushPromises()

    await barButton(wrapper, '写入骨架').trigger('click')
    await flushPromises()

    const text = wrapper.find('.wr-editor').element.value
    expect(text.startsWith('先写的这一句。\n\n## 题名')).toBe(true)
    wrapper.unmount()
  })

  it('撤销：正文退回写入前那一版（窗口用现成的 WRITE_UNDO_MS）', async () => {
    const { impl } = stubWriteFetch({ drafts: [] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    await pickTemplate(wrapper, 0)
    await wrapper.find('.wr-editor').setValue('先写的这一句。')
    await flushPromises()

    await barButton(wrapper, '写入骨架').trigger('click')
    await flushPromises()
    expect(wrapper.find('.wr-editor').element.value).toContain('## 题名')

    runToastUndo()
    await flushPromises()
    expect(wrapper.find('.wr-editor').element.value).toBe('先写的这一句。')

    // 撤销窗口不能另造一个数：写入骨架与"AI 整段写进正文"共用一个常量
    const undoAt = WRITE_SRC.indexOf('revertSkeleton(before)')
    expect(undoAt).toBeGreaterThan(-1)
    expect(WRITE_SRC.indexOf('WRITE_UNDO_MS', undoAt)).toBeGreaterThan(-1)
    wrapper.unmount()
  })

  it('「取消」只是不写骨架：提示条收起，正文一个字都不动', async () => {
    const { impl } = stubWriteFetch({ drafts: [] })
    globalThis.fetch = impl
    const wrapper = mountWrite()
    await flushPromises()

    await pickTemplate(wrapper, 0)
    await wrapper.find('.wr-editor').setValue('先写的这一句。')
    await flushPromises()

    await barButton(wrapper, '取消').trigger('click')
    await flushPromises()

    expect(wrapper.find('.wr-tplbar').exists()).toBe(false)
    expect(wrapper.find('.wr-editor').element.value).toBe('先写的这一句。')
    wrapper.unmount()
  })
})
