/**
 * 补齐三处「后端有、前端没接」的用例（2026-10-18 凌晨）：
 *
 * 1. ⭐ **参考文献（N31）**：切到「引用」页签会去排版；没有引文就不发请求（省一次网络）；
 *    引擎 503 时**把原话给用户看**（不换成"出错了"）；
 * 2. ⭐ **检查历史（N43 → N23）**：列表只带摘要、点一条取完整报告；
 * 3. ⭐ **概览四段数（N42）**：`doc_count` 一类的字段映射成组件要的键。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  bibEntries,
  bibError,
  bibSkipped,
  bibStyle,
  bibText,
  checkHistory,
  checkReport,
  drafts,
  loadBibliography,
  loadCheckHistory,
  openCheckRun,
  resetWrite,
  selectDraft,
} from '../src/stores/useWrite'
import { loadKnowledge, overview, resetKnowledge } from '../src/stores/useKnowledge'

const readSrc = (rel) => readFileSync(resolve(process.cwd(), rel), 'utf8')

const json = (status, body) => ({
  ok: status < 400,
  status,
  json: async () => body,
  text: async () => JSON.stringify(body),
})

function stubApi(handlers) {
  const calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url, init = {}) => {
      const path = String(url).split('?')[0] + (String(url).includes('?') ? '?' + String(url).split('?')[1] : '')
      calls.push({ path, method: (init.method || 'GET').toUpperCase() })
      for (const [needle, handler] of handlers) {
        if (path.startsWith(needle)) return handler(path)
      }
      return json(404, { detail: '没这条路由' })
    }),
  )
  return calls
}

/** 把草稿放进 store 再选中（`selectDraft(id)` 是按 id 找，不会自己拉）。 */
function useDraft(draft) {
  drafts.value = [draft]
  selectDraft(draft.id)
}

const DRAFT = {
  id: 7,
  title: '测试稿',
  body_md: '正文',
  citations: [
    { id: 1, order: 1, anchor: '[1]', csl_json: { id: 'm1' }, material_id: 1 },
    { id: 2, order: 2, anchor: '[2]', csl_json: { id: 'm2' }, material_id: 2 },
  ],
}

beforeEach(() => {
  resetKnowledge()
  resetWrite()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('参考文献（N31）', () => {
  it('⭐ 有引文 → 按选中样式请求，条目与跳过原因都记下来', async () => {
    stubApi([
      [
        '/api/drafts/7/bibliography',
        () =>
          json(200, {
            style: 'ieee',
            entries: ['[1] 张三. 论文. 2024.', '[2] 李四. 另一篇. 2023.'],
            skipped: [{ id: 'm3', reason: '缺作者与年份' }],
            styles: ['apa', 'ieee'],
            count: 2,
          }),
      ],
    ])
    useDraft(DRAFT)
    bibStyle.value = 'ieee'
    await loadBibliography()

    expect(bibEntries.value).toHaveLength(2)
    expect(bibSkipped.value[0]).toContain('缺作者与年份')
    expect(bibText.value).toContain('张三')
    expect(bibError.value).toBe('')
  })

  it('⭐ 编辑器没配好（503）→ 把接口原话给用户看', async () => {
    stubApi([
      [
        '/api/drafts/7/bibliography',
        () => json(503, { detail: '引擎环境没配好，参考文献不可用' }),
      ],
    ])
    useDraft(DRAFT)
    await loadBibliography()
    expect(bibError.value).toContain('引擎环境没配好')
    expect(bibEntries.value).toEqual([])
  })

  it('没有引文就不发请求（也不显示空表）', async () => {
    const calls = stubApi([])
    useDraft({ ...DRAFT, citations: [] })
    await loadBibliography()
    expect(calls.filter((c) => c.path.includes('bibliography'))).toHaveLength(0)
    expect(bibEntries.value).toEqual([])
  })
})

describe('检查历史（N43 → N23）', () => {
  it('⭐ 列表按草稿拉，只带摘要；点一条取完整报告', async () => {
    const calls = stubApi([
      [
        '/api/check',
        (path) =>
          path.includes('/api/check/9')
            ? json(200, { run_id: 9, findings: [], summary: { reported: 0, unknown: 0 } })
            : json(200, {
                items: [
                  { id: 9, draft_id: 7, created_at: '2026-10-18T00:10:00+00:00', summary: { reported: 2, unknown: 1 } },
                ],
              }),
      ],
    ])
    useDraft(DRAFT)
    await loadCheckHistory()
    expect(checkHistory.value).toHaveLength(1)
    expect(calls.some((c) => c.path.includes('draft_id=7'))).toBe(true)

    await openCheckRun(9)
    expect(checkReport.value).toEqual({ run_id: 9, findings: [], summary: { reported: 0, unknown: 0 } })
  })

  it('取历史失败 → 如实报错、列表清空（不假装有历史）', async () => {
    stubApi([['/api/check', () => json(500, { detail: '炸了' })]])
    useDraft(DRAFT)
    await loadCheckHistory()
    expect(checkHistory.value).toEqual([])
  })
})

describe('概览（N42）', () => {
  it('⭐ 字段映射成人话要用的键（tasks / blocks / materials / citations）', async () => {
    stubApi([
      [
        '/api/me/overview',
        () =>
          json(200, {
            tasks: 6,
            archived_tasks: 39,
            blocks: 412,
            materials: 9,
            drafts: 2,
            citations: 3,
            check_runs: 1,
          }),
      ],
    ])
    await loadKnowledge()
    expect(overview.value).toMatchObject({
      tasks: 6,
      archivedTasks: 39,
      blocks: 412,
      materials: 9,
      citations: 3,
    })
  })

  it('取不到就 null（底行走诚实档，不摆一排 0）', async () => {
    stubApi([['/api/me/overview', () => json(500, { detail: '炸了' })]])
    await loadKnowledge()
    expect(overview.value).toBeNull()
  })
})

describe('接线（结构断言）', () => {
  it('起草页：引用页签有参考文献块、收口抽屉有历史报告', () => {
    const view = readSrc('src/views/WriteView.vue')
    expect(view).toContain('wr-biblio')
    expect(view).toContain('bibStyleOptions')
    expect(view).toContain('wr-checkhist')
    expect(view).toContain('loadCheckHistory')
    // 切页签/开抽屉时顺手拉，不让用户多点一下
    expect(view).toContain('pickHelper')
    expect(view).toContain('openCheckDrawer')
  })

  it('集合页：智能集合能建能删（内置的不给删）', () => {
    const view = readSrc('src/views/CollectionsView.vue')
    expect(view).toContain("apiJson('/api/smart-collections'")
    expect(view).toContain('removeSmart')
    expect(view).toContain('v-if="item.builtin"')
    // 规则必须露出来（"规则即数据"）
    expect(view).toContain('ruleText(item.query)')
  })

  it('历史记录页：四段数真的传下去了', () => {
    const view = readSrc('src/views/LibraryView.vue')
    expect(view).toContain(':stats="overviewStats"')
    expect(view).toContain('/api/me/overview')
  })
})
