/**
 * 契约 mock（D2 / issue #94）的用例。
 *
 * 这一包只有一个风险点，用例就是围着它转的：**mock 写错 = 契约失效**——
 * 前后端各自"对"、合起来错，而且要到联调那天才暴露。所以这里不测"函数能跑"，
 * 测的是**四件事**：
 * ① 开关：默认关闭、只认 `'1'`、关着时 `mockResponse` 返回 null（不走 mock）；
 * ② 开关打开时，抽 3 个端点（一个数组 / 一个嵌套对象 / 一个深层结构）**逐字段**对契约；
 * ③ 未覆盖的路径**明确报错**，不许静默返回空对象；
 * ④ ⭐ **对账**：mock 支持的路径清单与 `backend/.contract/api.json` 的 `expected_new` 必须一致
 *    （后端一实现某个端点、清单动了，这边会被提醒），且**每条清单里的路由都有形状用例**。
 */

import { readFileSync } from 'node:fs'
import path from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  MOCK_FLAG_KEY,
  MOCK_ROUTES,
  isMockEnabled,
  mockFetch,
  mockResponse,
  mockRouteFor,
  resetMockState,
} from '../src/mock/contract'

const frontendDir = process.cwd()

function readManifest() {
  const candidates = [
    path.resolve(frontendDir, '../backend/.contract/api.json'),
    path.resolve(frontendDir, 'backend/.contract/api.json'),
  ]
  for (const file of candidates) {
    try {
      return JSON.parse(readFileSync(file, 'utf8'))
    } catch {
      /* 换下一个候选路径 */
    }
  }
  throw new Error('找不到 backend/.contract/api.json（应该在仓库里）')
}

/** 契约清单里的 `{param}` 与 mock 里的 `{id}` / `{task_id}` 归一化成同一种写法。 */
const normalizePath = (p) => p.split('/').map((seg) => (seg.startsWith('{') ? '{param}' : seg)).join('/')
const asKey = (method, p) => `${method} ${normalizePath(p)}`

const manifest = readManifest()
const expectedNewKeys = manifest.expected_new.map((item) => asKey(item.method, item.path))
const mockKeys = MOCK_ROUTES.map((route) => asKey(route.method, route.path))
const anchorKeys = (manifest.anchors || []).map((item) => asKey(item.method, item.path))

/**
 * ⚠️ **对账清单不能只用 `expected_new`**（集成时真踩到，CI 直接红在起草接口那条 PR 上）。
 *
 * 两条规矩本身都对，一叠加就必然漂移：
 * - **契约闸（后端进度口径）**：端点一实现，就要求把它从 `expected_new` **搬进 `anchors`**；
 * - **mock 的职责（前端离线口径）**：新增端点在**实现之后也要继续 mock** ——
 *   不然前端就失去"后端一行没写也能把界面做完"那条路。
 *
 * 于是"只用 `expected_new` 对账"，在**第一个端点被实现的那天**就会红：
 * 起草那一组（N18–N21）实现并搬进 `anchors` 之后，mock 这边就成了"多余的 8 条"。
 * 这里显式列出「**已实现但仍要 mock**」的资源前缀，对账时把这几组从 `anchors` 里补回来。
 * （新实现一组就加一个前缀；**基线端点绝不在列** —— 基线必须继续打真后端。）
 */
const IMPLEMENTED_BUT_MOCKED = ['/api/drafts']
const reconcileKeys = [
  ...expectedNewKeys,
  ...anchorKeys.filter((key) => IMPLEMENTED_BUT_MOCKED.some((prefix) => key.includes(prefix))),
]

/** 形状表：每个端点该有哪些字段（**这份表就是"契约逐字段"的落地**）。 */
const MATERIAL_KEYS = ['id', 'text_quote', 'translated_quote', 'page', 'source_name', 'note', 'task_id', 'block_id', 'deleted_at', 'created_at']
const COLLECTION_KEYS = ['id', 'name', 'parent_id', 'sort', 'doc_count', 'doc_count_deep']
const SMART_KEYS = ['id', 'name', 'query', 'count', 'builtin']
const DRAFT_KEYS = ['id', 'title', 'body_md', 'template_id', 'updated_at', 'citations']
const CITATION_KEYS = ['id', 'draft_id', 'material_id', 'order', 'csl_json', 'anchor']
const REPORT_KEYS = ['run_id', 'step', 'findings', 'summary']

const CASES = [
  { n: 'N1', method: 'GET', path: '/api/collections', keys: ['items'], itemKeys: COLLECTION_KEYS },
  { n: 'N2', method: 'POST', path: '/api/collections', body: { name: '新增集合' }, status: 201, keys: COLLECTION_KEYS },
  { n: 'N3', method: 'PATCH', path: '/api/collections/3', body: { name: '改个名' }, keys: COLLECTION_KEYS },
  { n: 'N4', method: 'DELETE', path: '/api/collections/3', keys: ['deleted', 'moved_to_parent'] },
  { n: 'N5', method: 'PUT', path: '/api/tasks/42/collections', body: { collection_ids: [1, 3] }, keys: ['collection_ids'] },
  { n: 'N6', method: 'GET', path: '/api/tags?kind=topic', keys: ['items'], itemKeys: ['id', 'name', 'kind', 'doc_count'] },
  { n: 'N7', method: 'PUT', path: '/api/tasks/42/tags', body: { tags: [{ name: 'RAG', kind: 'topic' }] }, keys: ['tags'] },
  { n: 'N9', method: 'GET', path: '/api/smart-collections', keys: ['items'], itemKeys: SMART_KEYS },
  {
    n: 'N10',
    method: 'POST',
    path: '/api/smart-collections',
    body: { name: '自定义', query: { all: [{ field: 'reading_status', op: 'eq', value: 'done' }] } },
    status: 201,
    keys: SMART_KEYS,
  },
  { n: 'N11', method: 'DELETE', path: '/api/smart-collections/4', keys: ['deleted', 'id'] },
  { n: 'N12', method: 'POST', path: '/api/materials', body: { task_id: 42, block_id: 'p2_b7' }, status: 201, keys: MATERIAL_KEYS },
  { n: 'N13', method: 'GET', path: '/api/materials?task_id=42', keys: ['items'], itemKeys: MATERIAL_KEYS },
  { n: 'N14', method: 'DELETE', path: '/api/materials/1', keys: ['deleted', 'id', 'deleted_at'] },
  {
    n: 'N15',
    method: 'POST',
    path: '/api/ask-logs',
    body: { task_id: 42, question: 'q', answer: 'a', source_block_ids: ['p2_b7'] },
    status: 201,
    keys: ['id'],
  },
  { n: 'N16', method: 'GET', path: '/api/ask-logs?task_id=42', keys: ['items'] },
  {
    n: 'N17',
    method: 'GET',
    path: '/api/memory-events',
    keys: ['items'],
    itemKeys: ['id', 'task_id', 'layer', 'stage', 'actor', 'tool', 'summary', 'payload', 'created_at'],
  },
  { n: 'N17', method: 'POST', path: '/api/memory-events', body: {}, status: 405, keys: ['detail'] },
  { n: 'N18', method: 'GET', path: '/api/drafts', keys: ['items'], itemKeys: DRAFT_KEYS },
  { n: 'N18', method: 'POST', path: '/api/drafts', body: { title: '新草稿' }, status: 201, keys: DRAFT_KEYS },
  { n: 'N19', method: 'GET', path: '/api/drafts/1', keys: DRAFT_KEYS },
  { n: 'N19', method: 'PATCH', path: '/api/drafts/1', body: { body_md: '# 改过了' }, keys: DRAFT_KEYS },
  { n: 'N19', method: 'DELETE', path: '/api/drafts/1', keys: DRAFT_KEYS },
  {
    n: 'N20',
    method: 'POST',
    path: '/api/drafts/1/citations',
    body: { material_id: 1, anchor: { block_id: 'p2_b7', offset: 3 } },
    status: 201,
    keys: CITATION_KEYS,
  },
  { n: 'N21', method: 'GET', path: '/api/drafts/1/citations', keys: ['items'], itemKeys: CITATION_KEYS },
  { n: 'N21', method: 'DELETE', path: '/api/drafts/1/citations', keys: ['deleted', 'count'] },
  { n: 'N22', method: 'POST', path: '/api/check', body: { draft_id: 1, doc_text: '研究表明，写得不错。' }, keys: REPORT_KEYS },
  { n: 'N23', method: 'GET', path: '/api/check/12', keys: REPORT_KEYS },
  { n: 'N24', method: 'GET', path: '/api/me/storage', keys: ['total_bytes', 'by_kind', 'location'], nestedKeys: { by_kind: ['uploads', 'outputs', 'backups', 'db'] } },
  { n: 'N25', method: 'GET', path: '/api/me/export?format=md', text: true },
  { n: 'N26', method: 'GET', path: '/api/me/ledger?format=json', keys: ['items'] },
  { n: 'N27', method: 'DELETE', path: '/api/me', keys: ['deleted', 'id'] },
  { n: 'N28', method: 'PATCH', path: '/api/me', body: { display_name: '新显示名' }, keys: ['id', 'username', 'display_name', 'role', 'is_active', 'created_at'] },
  {
    n: 'N29',
    method: 'GET',
    path: '/api/me/sessions',
    keys: ['items'],
    itemKeys: ['id', 'created_at', 'expires_at', 'last_seen_at', 'user_agent'],
  },
  { n: 'N29', method: 'DELETE', path: '/api/me/sessions/1', keys: ['deleted', 'id'] },
]

const request = (item) =>
  mockFetch(item.path, {
    method: item.method,
    ...(item.body ? { body: JSON.stringify(item.body) } : {}),
  })

beforeEach(() => {
  localStorage.clear()
  resetMockState()
})

afterEach(() => {
  localStorage.clear()
  resetMockState()
  vi.restoreAllMocks()
})

describe('开关', () => {
  it('默认关闭：一个开关都没设时，请求不走 mock', () => {
    expect(isMockEnabled()).toBe(false)
    expect(mockResponse('/api/collections', {})).toBeNull()
  })

  it('只认字符串 "1"（"true" / "on" 一律当关闭）', () => {
    localStorage.setItem(MOCK_FLAG_KEY, 'true')
    expect(isMockEnabled()).toBe(false)
    localStorage.setItem(MOCK_FLAG_KEY, '1')
    expect(isMockEnabled()).toBe(true)
  })

  it('开关打开：N1–N29 走 mock；基线端点（/api/tasks、/api/health）照旧放行打真后端', () => {
    localStorage.setItem(MOCK_FLAG_KEY, '1')
    expect(mockResponse('/api/collections', {})).not.toBeNull()
    expect(mockResponse('/api/tasks', {})).toBeNull()
    expect(mockResponse('/api/tasks/42/understanding', { method: 'POST' })).toBeNull()
    expect(mockResponse('/api/health', {})).toBeNull()
  })

  it('请求层真的接线了：开关打开时 authFetch("/api/collections") 由 mock 应答（不打网络）', async () => {
    localStorage.setItem(MOCK_FLAG_KEY, '1')
    localStorage.setItem('docwise_api_base', 'http://127.0.0.1:9') // 真打过去必然失败，用来证明没打
    const { authFetch } = await import('../src/auth')
    const response = await authFetch('/api/collections')
    expect(response.status).toBe(200)
    const body = await response.json()
    expect(Array.isArray(body.items)).toBe(true)
    expect(Object.keys(body.items[0]).sort()).toEqual([...COLLECTION_KEYS].sort())
  })
})

describe('⭐ 抽 3 个端点逐字段对契约', () => {
  it('数组端点：N1 集合列表（items[] 六个字段）', () => {
    const { status, body } = mockFetch('/api/collections', {})
    expect(status).toBe(200)
    expect(Object.keys(body)).toEqual(['items'])
    expect(body.items.length).toBeGreaterThan(0)
    expect(Object.keys(body.items[0]).sort()).toEqual([...COLLECTION_KEYS].sort())
    // 计数语义：子集合的文献不算在父集合里（直接成员 1 + 子集合里的 1 = deep 2）
    const parent = body.items.find((item) => item.id === 1)
    expect(parent.doc_count).toBe(1)
    expect(parent.doc_count_deep).toBe(2)
  })

  it('嵌套对象端点：N24 磁盘占用（by_kind 四个分类）', () => {
    const { status, body } = mockFetch('/api/me/storage', {})
    expect(status).toBe(200)
    expect(Object.keys(body).sort()).toEqual(['by_kind', 'location', 'total_bytes'])
    expect(Object.keys(body.by_kind).sort()).toEqual(['backups', 'db', 'outputs', 'uploads'])
    expect(typeof body.total_bytes).toBe('number')
  })

  it('深层结构：N21 引文列表（每条带 CSL-JSON 单条 item）', () => {
    const { body } = mockFetch('/api/drafts/1/citations', {})
    expect(Object.keys(body)).toEqual(['items'])
    const citation = body.items[0]
    expect(Object.keys(citation).sort()).toEqual([...CITATION_KEYS].sort())
    expect(citation.csl_json.id).toBe('material-1')
    expect(citation.csl_json.type).toBe('article-journal')
    expect(citation.anchor.block_id).toBe('p2_b7')
  })
})

describe('未覆盖的路径必须喊出来', () => {
  it('未知路径 → 抛错，并说清"要加端点先改契约"（不许静默返回空对象）', () => {
    expect(() => mockFetch('/api/not-a-real-endpoint', {})).toThrow(/没覆盖/)
    expect(() => mockFetch('/api/not-a-real-endpoint', {})).toThrow(/\/api\/not-a-real-endpoint/)
  })

  it('方法不对也算没覆盖（GET /api/me 没有这个端点）', () => {
    expect(() => mockFetch('/api/me', {})).toThrow(/没覆盖/)
  })
})

describe('⭐ 契约 ↔ mock 对账', () => {
  it('mock 支持的路径清单与契约清单一模一样（expected_new + 已实现但仍要 mock 的那几组）', () => {
    const missingInMock = reconcileKeys.filter((key) => !mockKeys.includes(key))
    const extraInMock = mockKeys.filter((key) => !reconcileKeys.includes(key))
    expect(
      { missingInMock: missingInMock.sort(), extraInMock: extraInMock.sort() },
      'mock 与 backend/.contract/api.json 漂移了：mock 写错 = 契约失效',
    ).toEqual({ missingInMock: [], extraInMock: [] })
  })

  it('N8 不在清单里（它是给基线端点加查询参数，不是新端点，也不该被 mock）', () => {
    expect(mockKeys).not.toContain('GET /api/tasks')
    expect(expectedNewKeys).not.toContain('GET /api/tasks')
  })

  it('清单里每条路由都有形状用例（新增端点忘了写用例，这里会红）', () => {
    // 用例写的是具体路径（/api/drafts/1），先反查它落在清单里的哪条模式上
    const covered = new Set()
    const dangling = []
    for (const item of CASES) {
      const route = mockRouteFor(item.method, item.path)
      if (!route) dangling.push(`${item.method} ${item.path}`)
      else covered.add(asKey(route.method, route.path))
    }
    expect(dangling.sort(), '这些用例的路径不在 mock 清单里（写错了或者清单改过）').toEqual([])
    const untested = expectedNewKeys.filter((key) => !covered.has(key))
    expect(untested.sort()).toEqual([])
  })
})

describe('每条路由都能返回形状正确的假数据', () => {
  it.each(CASES.map((item) => [`${item.n} ${item.method} ${item.path}`, item]))('%s', (_label, item) => {
    const result = request(item)

    expect(result.status).toBe(item.status ?? 200)
    if (item.text) {
      // 带文件的端点：body 是文本/字节 + contentType，不是 JSON
      expect(typeof result.body).toBe('string')
      expect(result.contentType).toBeTruthy()
      return
    }
    expect(Object.keys(result.body).sort()).toEqual([...item.keys].sort())
    if (item.itemKeys) {
      expect(Object.keys(result.body.items[0]).sort()).toEqual([...item.itemKeys].sort())
    }
    if (item.nestedKeys) {
      for (const [field, keys] of Object.entries(item.nestedKeys)) {
        expect(Object.keys(result.body[field]).sort()).toEqual([...keys].sort())
      }
    }
  })
})

describe('契约里那些"有语义"的行为，mock 也要像', () => {
  it('N11 内置智能集合不许删（400）', () => {
    expect(mockFetch('/api/smart-collections/1', { method: 'DELETE' }).status).toBe(400)
  })

  it('N3 不许把集合移进自己的后代（400 成环）', () => {
    const result = mockFetch('/api/collections/1', { method: 'PATCH', body: JSON.stringify({ parent_id: 2 }) })
    expect(result.status).toBe(400)
  })

  it('N2 同一个父集合下不许重名（400）', () => {
    const result = mockFetch('/api/collections', { method: 'POST', body: JSON.stringify({ name: '毕业论文' }) })
    expect(result.status).toBe(400)
  })

  it('N14 软删之后列表里就看不到它了（软删 7 天）', () => {
    mockFetch('/api/materials/1', { method: 'DELETE' })
    expect(mockFetch('/api/materials', {}).body.items.some((item) => item.id === 1)).toBe(false)
  })

  it('N4 只删集合、不动文献：子集合与文献都回到父集合，且 moved_to_parent 数得对', () => {
    const result = mockFetch('/api/collections/1', { method: 'DELETE' })
    expect(result.body.moved_to_parent).toBe(2) // 1 个子集合 + 1 篇直接成员
    const after = mockFetch('/api/collections', {}).body.items
    expect(after.some((item) => item.id === 1)).toBe(false)
    expect(after.find((item) => item.id === 2).parent_id).toBe(null) // 子集合上移到顶层
    expect(mockFetch('/api/tasks/42/collections', { method: 'PUT', body: JSON.stringify({ collection_ids: [3] }) }).status).toBe(200)
  })

  it('N17 的 POST 只给服务端内部用：mock 明确拒绝，而不是假装写成功', () => {
    const result = mockFetch('/api/memory-events', { method: 'POST', body: JSON.stringify({}) })
    expect(result.status).toBe(405)
    expect(result.body.detail).toContain('只给服务端内部用')
  })
})
