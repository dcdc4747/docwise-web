/**
 * 知识库重构（2026-10-17）的用例。
 *
 * 这次改的是**信息架构**，不是配色，所以要钉的不是"长什么样"，而是**几件容易改回去的事**：
 *
 * 1. ⭐ **「读懂」和「历史记录」必须是两个去处**（以前都进库页，于是"点读懂看到的是清单"）；
 * 2. ⭐ **开工页常驻**（上传 / 示例 / 继续读 / 最近三篇），不再绑"库空了"；
 * 3. ⭐ **集合 / 标签 是真页面**（后端 N1–N6 一直活着，此前点了只弹"还没做"）；
 * 4. ⭐ **拿掉"点了只弹还没做"的入口**（草稿 / 引用搬去起草页）；
 * 5. ⭐ **归集要认得当前归属**（N5 是全量替换，不知道归属就发请求 = 悄悄抹掉别人的集合）。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { parseHash, ROUTES } from '../src/router'
import {
  collectionNameOf,
  collections,
  errors,
  loadKnowledge,
  mapCollection,
  mapSmart,
  mapTag,
  resetKnowledge,
  smartCollections,
  tags,
} from '../src/stores/useKnowledge'

const readSrc = (rel) => readFileSync(resolve(process.cwd(), rel), 'utf8')

const json = (status, body) => ({
  ok: status < 400,
  status,
  json: async () => body,
  text: async () => JSON.stringify(body),
})

/** 极简后端：三张表；可单独让某一条挂掉（验"各自容错"）。 */
function stubApi({ collections: c = [], tags: t = [], smart: s = [], fail = [] } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url) => {
      const path = String(url).split('?')[0]
      if (path.endsWith('/api/collections')) {
        if (fail.includes('collections')) return json(500, { detail: '集合挂了' })
        return json(200, { items: c })
      }
      if (path.endsWith('/api/tags')) {
        if (fail.includes('tags')) return json(500, { detail: '标签挂了' })
        return json(200, { items: t })
      }
      if (path.endsWith('/api/smart-collections')) {
        if (fail.includes('smart')) return json(500, { detail: '智能集合挂了' })
        return json(200, { items: s })
      }
      return json(404, { detail: '没这条路由' })
    }),
  )
}

beforeEach(() => {
  resetKnowledge()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('字段映射（照接口，不照文档猜）', () => {
  it('集合：`doc_count` → `count`，`parent_id` → `parentId`', () => {
    expect(mapCollection({ id: 1, name: '化学组', parent_id: null, doc_count: 3 })).toEqual({
      id: 1,
      name: '化学组',
      parentId: null,
      count: 3,
    })
  })

  it('标签：`doc_count` → `count`，保住 kind', () => {
    expect(mapTag({ id: 2, name: '方法', kind: 'method', doc_count: 1 })).toEqual({
      id: 2,
      name: '方法',
      kind: 'method',
      count: 1,
    })
  })

  it('智能集合：`count` 原样、规则 `query` 与 `builtin` 保住（规则即数据）', () => {
    const query = { all: [{ field: 'reading_status', op: 'eq', value: 'todo' }] }
    expect(mapSmart({ id: 3, name: '待读', query, count: 6, builtin: true })).toMatchObject({
      name: '待读',
      count: 6,
      builtin: true,
    })
    expect(mapSmart({ id: 3, name: '待读', query, count: 6 }).query).toEqual(query)
  })

  it('没计数就算 null（不编 0）', () => {
    expect(mapCollection({ id: 1, name: 'x' }).count).toBeNull()
  })

  it('按 id 找集合名（"当前筛选：集合 X"这种人话要用）', () => {
    collections.value = [{ id: 7, name: '毕业论文' }]
    expect(collectionNameOf(7)).toBe('毕业论文')
    expect(collectionNameOf('7')).toBe('毕业论文')
    expect(collectionNameOf('')).toBe('')
  })
})

describe('loadKnowledge：三样各自容错', () => {
  it('三样都拉到了', async () => {
    stubApi({
      collections: [{ id: 1, name: '化学组', doc_count: 1 }],
      tags: [{ id: 1, name: '方法', kind: 'topic', doc_count: 1 }],
      smart: [{ id: 1, name: '待读', query: {}, count: 6, builtin: true }],
    })
    await loadKnowledge()
    expect(collections.value).toHaveLength(1)
    expect(tags.value).toHaveLength(1)
    expect(smartCollections.value).toHaveLength(1)
    // ⚠️ 2026-10-18：`loadKnowledge` 现在多拉一条概览（N42），所以 `errors` 多了 `overview`
    expect(errors.value).toMatchObject({ collections: '', tags: '', smart: '' })
  })

  it('⭐ 一个挂了不影响另外两个（用户最少还看得见另外两行）', async () => {
    stubApi({
      collections: [{ id: 1, name: '化学组', doc_count: 1 }],
      smart: [{ id: 1, name: '待读', query: {}, count: 6 }],
      fail: ['tags'],
    })
    await loadKnowledge()
    expect(collections.value).toHaveLength(1)
    expect(smartCollections.value).toHaveLength(1)
    expect(tags.value).toEqual([])
    expect(errors.value.tags).toContain('标签列表暂时取不到')
    expect(errors.value.tags).toContain('标签挂了')
  })

  it('没数据就是空数组（不编默认集合）', async () => {
    stubApi({})
    await loadKnowledge()
    expect(collections.value).toEqual([])
    expect(tags.value).toEqual([])
    expect(smartCollections.value).toEqual([])
  })
})

describe('路由：读懂 / 历史记录 / 集合 / 标签 各自有地址', () => {
  it('⭐ 四个地址都能被认出来，且互不抢（`/read` 不许抢 `/read/12`）', () => {
    expect(parseHash('#/').name).toBe('library')
    expect(parseHash('#/read').name).toBe('readHome')
    expect(parseHash('#/read/12').name).toBe('read')
    expect(parseHash('#/read/12').params.taskId).toBe(12)
    expect(parseHash('#/collections').name).toBe('collections')
    expect(parseHash('#/tags').name).toBe('tags')
  })

  it('路由表里确实有四条（防止有人把手写的地址删掉）', () => {
    expect(ROUTES.readHome).toBe('/read')
    expect(ROUTES.collections).toBe('/collections')
    expect(ROUTES.tags).toBe('/tags')
    expect(ROUTES.library).toBe('/')
  })
})

describe('左栏与外壳接线（结构断言）', () => {
  it('⭐ 草稿 / 引用 从历史记录那组拿掉了（它们是写作资产，入口在起草页）', () => {
    const rail = readSrc('src/components/AppRail.vue')
    expect(rail).not.toContain("key: 'lib-drafts'")
    expect(rail).not.toContain("key: 'lib-refs'")
    expect(rail).toContain("key: 'lib-unfiled'")
    expect(rail).toContain('历史记录')
    expect(rail).not.toContain('我的库</div>')
  })

  it('⭐「读懂」与「全部文献」去的是**不同**的地方', () => {
    const app = readSrc('src/App.vue')
    expect(app).toContain("read: { go: { name: 'readHome' } }")
    expect(app).toContain("'lib-all': { go: { name: 'library' }")
    expect(app).toContain("'lib-collections': { go: { name: 'collections' } }")
    expect(app).toContain("'lib-tags': { go: { name: 'tags' } }")
    expect(app).toContain("'lib-unfiled': { go: { name: 'library' }, filter: { unfiled: 1 } }")
    // 不再有"点了只弹一句还没做"的入口
    expect(app).not.toContain("'lib-collections': { note:")
    expect(app).not.toContain("'lib-tags': { note:")
  })

  it('⭐ 开工页常驻：上传 / 示例 / 继续读 / 最近三篇，一个都不少', () => {
    const view = readSrc('src/views/ReadHomeView.vue')
    expect(view).toContain('把文献读懂')
    expect(view).toContain("openExample('guide')")
    expect(view).toContain('继续读')
    expect(view).toContain('rh-recent-grid')
    expect(view).toContain('upload-card')
    // 它不自己取数（数据来自 store，避免两份口径）
    expect(view).not.toContain("apiJson('/api/tasks")
  })

  it('⭐ 集合页：建 / 改名 / 删 都真发请求，且删除要说清"文献不删"', () => {
    const view = readSrc('src/views/CollectionsView.vue')
    expect(view).toContain("apiJson('/api/collections'")
    expect(view).toContain('method: \'PATCH\'')
    expect(view).toContain("method: 'DELETE'")
    expect(view).toContain('未归类')
    expect(view).toContain('里面的文献还在')
  })

  it('⭐ 标签页：点一个标签就按它筛（N8 的 tag[]）', () => {
    const view = readSrc('src/views/TagsView.vue')
    expect(view).toContain('loadTasksAndSync({ tag: [item.name] })')
    // ⚠️ 2026-10-18：贴标签已经能做了（历史记录卡片上的「＋ 标签」），
    // 这条文案随之改成「贴标签去卡片上，改名/删除还没有」
    expect(view).toContain('贴标签')
    expect(view).toContain('改名 / 删除标签暂时没有')
  })

  it('⭐ 历史记录页：筛选条接真选项 + 归集认得当前归属', () => {
    const view = readSrc('src/views/LibraryView.vue')
    expect(view).toContain(':collections="collections"')
    expect(view).toContain(':tags="tags"')
    expect(view).toContain(':smart-collections="smartCollections"')
    expect(view).toContain('assignCollection')
    expect(view).toContain('/collections`')
    // N5 是全量替换：多个集合时禁用下拉，宁可少给一个操作
    expect(view).toContain('.length > 1')
  })
})
