/**
 * 契约 mock —— **后端一行没写时，前端也能把版式和交互做完**（D2 / issue #94）。
 *
 * 为什么有这个文件：前后端开发时互不依赖，靠的是「契约 + mock」这一对。
 * 契约（`docs/契约_接口_v1_20261014.md`）冻住接口形状；mock 让前端立刻能跑起来。
 * **没有 mock，"契约先行"就是一句空话**——前端只能干等后端。
 *
 * 三条纪律（写在最前面，因为它就是这个文件唯一的风险点）：
 * ① ⚠️ **形状必须与契约逐字段一致**——**mock 写错 = 契约失效**，两边一起错还看不出来。
 *    `tests/contract-mock.test.js` 里有一张"每个端点该有哪些字段"的表，逐条盯着；
 * ② ⚠️ **只 mock 新增的 N1–N29，外加两处"给基线端点追加的东西"**（契约 §2.2 的 N8 查询参数、
 *    §2.8 的 N30 字段）：基线那 25 个端点已经能用真的，整个 mock 掉只会掩盖真实问题——
 *    所以这两处都**只在"确实是新增的那部分"时才拦**（见 `MOCK_DELTAS`）。
 * ③ ⚠️ **mock 由写契约的人维护，使用方不许各自改**。发现 mock 与契约不一致 →
 *    在 issue #94 下评论，**别改 mock 去迁就自己的代码**（那样两边都错）。
 *
 * 开关：`localStorage.docwise_mock === '1'`（**默认关闭**——不然会有人拿假数据当真的调试）。
 * 打开后走 `mockResponse()`：**是 N1–N29（或 N8 / N30 两处追加）的请求**返回假数据，
 * **其余（基线端点）原样放行**（基线端点必须继续打真后端，否则整个应用没法用）。
 *
 * ⚠️ 契约没写形状、这里替它定的收口（都只是"最省事的合理取值"，契约一改这里就跟着改）：
 * - `N4.moved_to_parent`：被上移到父集合的条目数（直接文献 + 子集合），契约只给了字段名；
 * - `N14 / N21 / N27 / N29` 的 DELETE：`200 {deleted: true, ...}`（契约只写了 200）；
 * - `N19` 的 DELETE：返回被删掉的那条 `Draft`（契约这一行写的是 `200 Draft`）；
 * - `N21` 的 DELETE：清空该草稿的引文（契约没写删哪一条）；
 * - `N26.ledger` 的 json 形状：`{items}`，与 N17 同源同形状（契约只写了"同源导出"）；
 * - `N28` 的响应：`user` 对象 6 字段（与 `/api/auth/me` 的**基线 6 字段**一致——
 *   N30 追加的 `last_login_at` **没有**顺手加到 N28 上，契约只说了 `/api/auth/me` 那一处）；
 * - `N29` 的会话对象：`auth_sessions` 表里除 `token_hash` 之外的列；
 * - `N22/N23` 的报告内容：**固定示例**（契约冻的是形状，不是结论——报告结论得由真后端算）；
 * - `N8` 的筛选语义：多个参数**取交集（AND）**；`collection_id` 按**直接成员**算（与集合计数
 *   同一条语义：子集合的文献不算在父集合里）；`tag[]` / `tag` 两种写法都收，多值也取交集；
 *   `smart_id` 直接套那条智能集合的 `query` 规则；查不到的 id → **空数组**（契约没定义错误）。
 */

/** 开关的 localStorage 键（值是字符串 `'1'`，别的值一律当关闭）。 */
export const MOCK_FLAG_KEY = 'docwise_mock'

/**
 * ⭐ mock 支持的 (method, path) 清单 —— **与 `backend/.contract/api.json` 的 `expected_new` 对账**
 * （`tests/contract-mock.test.js` 里那条用例就是干这个的）。
 *
 * 对账的意义：后端一实现某个端点、把清单动一下，**mock 侧会被提醒**——
 * 不然 mock 会继续"对"，而真接口已经变了。
 *
 * 路径参数写成 `{名字}`；对账时双方都把 `{任意名}` 归一化成 `{param}`（改名不算新增端点）。
 * ⚠️ **N8 / N30 不在表里的原因**：它们是给基线端点**追加**查询参数 / 响应字段，
 * **不是新端点**、也不该出现在 `expected_new` 里——单独放 `MOCK_DELTAS`（见下）。
 * ⚠️ **N17 只有 GET 是真的给前端用的**（POST 是服务端内部埋点，见 `memory-events` 那条处理）。
 */

/** N31 支持的样式 key（与后端 `routers/bibliography.py` 的白名单一致：多了会 400）。 */
const BIB_STYLES = ['apa', 'ieee', 'gb-t-7714-2015-numeric', 'gb-t-7714-2015-author-date']

export const MOCK_ROUTES = [
  { n: 'N1', method: 'GET', path: '/api/collections' },
  { n: 'N2', method: 'POST', path: '/api/collections' },
  { n: 'N3', method: 'PATCH', path: '/api/collections/{id}' },
  { n: 'N4', method: 'DELETE', path: '/api/collections/{id}' },
  { n: 'N5', method: 'PUT', path: '/api/tasks/{task_id}/collections' },
  { n: 'N6', method: 'GET', path: '/api/tags' },
  { n: 'N7', method: 'PUT', path: '/api/tasks/{task_id}/tags' },
  { n: 'N9', method: 'GET', path: '/api/smart-collections' },
  { n: 'N10', method: 'POST', path: '/api/smart-collections' },
  { n: 'N11', method: 'DELETE', path: '/api/smart-collections/{id}' },
  { n: 'N12', method: 'POST', path: '/api/materials' },
  { n: 'N13', method: 'GET', path: '/api/materials' },
  { n: 'N14', method: 'DELETE', path: '/api/materials/{id}' },
  { n: 'N15', method: 'POST', path: '/api/ask-logs' },
  { n: 'N16', method: 'GET', path: '/api/ask-logs' },
  { n: 'N17', method: 'GET', path: '/api/memory-events' },
  { n: 'N17', method: 'POST', path: '/api/memory-events' },
  { n: 'N18', method: 'GET', path: '/api/drafts' },
  { n: 'N18', method: 'POST', path: '/api/drafts' },
  { n: 'N19', method: 'GET', path: '/api/drafts/{id}' },
  { n: 'N19', method: 'PATCH', path: '/api/drafts/{id}' },
  { n: 'N19', method: 'DELETE', path: '/api/drafts/{id}' },
  { n: 'N20', method: 'POST', path: '/api/drafts/{id}/citations' },
  { n: 'N21', method: 'GET', path: '/api/drafts/{id}/citations' },
  { n: 'N21', method: 'DELETE', path: '/api/drafts/{id}/citations' },
  { n: 'N31', method: 'GET', path: '/api/drafts/{id}/bibliography' },
  // 埋点 1（契约 §2.9–§2.10 / N33–N34）：译文改动与块曝光
  { n: 'N33', method: 'POST', path: '/api/block-edits' },
  { n: 'N33', method: 'GET', path: '/api/block-edits' },
  { n: 'N34', method: 'POST', path: '/api/block-exposures' },
  // 记忆（M7，契约外的新东西 · §2.10 / N35–N39）：用法偏好
  { n: 'N35', method: 'GET', path: '/api/memories' },
  { n: 'N36', method: 'POST', path: '/api/memories' },
  { n: 'N37', method: 'PATCH', path: '/api/memories/{id}' },
  { n: 'N38', method: 'DELETE', path: '/api/memories/{id}' },
  { n: 'N39', method: 'GET', path: '/api/memories/resolve' },
  { n: 'N22', method: 'POST', path: '/api/check' },
  { n: 'N23', method: 'GET', path: '/api/check/{run_id}' },
  { n: 'N24', method: 'GET', path: '/api/me/storage' },
  { n: 'N25', method: 'GET', path: '/api/me/export' },
  { n: 'N26', method: 'GET', path: '/api/me/ledger' },
  { n: 'N27', method: 'DELETE', path: '/api/me' },
  { n: 'N28', method: 'PATCH', path: '/api/me' },
  { n: 'N29', method: 'GET', path: '/api/me/sessions' },
  { n: 'N29', method: 'DELETE', path: '/api/me/sessions/{id}' },
  { n: 'N42', method: 'GET', path: '/api/me/overview' },
  { n: 'N43', method: 'GET', path: '/api/check' },
  { n: 'N40', method: 'GET', path: '/api/me/preferences' },
  { n: 'N41', method: 'PUT', path: '/api/me/preferences' },
]

/**
 * ⚠️ **两处"给基线端点追加的东西"**（N8 / N30）——**不是新端点**，
 * 所以不放进 `MOCK_ROUTES`：放进去那条对账用例会红（它们在 `expected_new` 里没有，
 * 而它们**本来就不该有**）。
 *
 * 拦的条件也不一样，因为基线端点得继续能用：
 * - **N8**：只有**带了 N8 的查询参数**时才拦——不带参数原样放行打真后端，列表照旧是真的；
 * - **N30**：`/api/auth/me` 只要走 mock 就拦——因为"追加字段"这件事真后端还没做，
 *   放行的话个人中心拿不到 `last_login_at`，这个 mock 就白搭了。
 */
export const MOCK_DELTAS = [
  {
    n: 'N8',
    method: 'GET',
    path: '/api/tasks',
    note: '基线端点追加查询参数；不带参数时放行打真后端',
  },
  {
    n: 'N30',
    method: 'GET',
    path: '/api/auth/me',
    note: '基线响应追加 last_login_at；既有 6 字段逐字不动',
  },
]

// ---------------------------------------------------------------------------
// 假数据（**明显是假的**，不伪装成真内容；形状照契约）
// ---------------------------------------------------------------------------

const SEED_AT = '2026-10-14T02:00:00Z'
/** N30 追加的"上次登录"：给一个值，好让 ① 块的"上次登录"有东西可显示（真后端可能是 null）。 */
const SEED_LAST_LOGIN = '2026-10-13T09:12:00Z'

/** 一个空 ZIP 的字节（只有 EOCD：22 字节）——**结构合法、能被解开、里面是空的**。
 *  为什么不用一段随便的字符串：那会给出一个"打不开的文件"，比给空包更糟。 */
const EMPTY_ZIP = '\u0050\u004b\u0005\u0006' + '\u0000'.repeat(18)

function seed() {
  return {
    user: {
      id: 1,
      username: 'demo',
      display_name: '演示账号',
      role: 'admin',
      is_active: true,
      created_at: SEED_AT,
    },
    // N30：`/api/auth/me` 追加的字段。**故意不塞进 `user` 对象**——N28（PATCH /api/me）
    // 的响应形状没被 N30 改，仍是 6 字段；塞进去会让 N28 悄悄多一个字段。
    last_login_at: SEED_LAST_LOGIN,
    // 两篇文献：既是智能集合算 count 的对象，也是 N8（基线 `/api/tasks` 加参数）的筛选对象。
    // 前 16 个字段＝契约 §1.4 的"列表项"，后两个（reading_status / tags）是 mock 内部用的。
    tasks: [
      {
        id: 42,
        filename: 'EBSCO_05-mono.pdf',
        status: 'completed',
        progress: 1,
        tier: 'fast',
        source_lang: 'en',
        target_lang: 'zh',
        native: false,
        created_at: SEED_AT,
        stage: null,
        eta_seconds: null,
        elapsed_seconds: 41.2,
        started_at: SEED_AT,
        finished_at: SEED_AT,
        last_read_page: 3,
        text_source: 'text-layer',
        reading_status: 'todo',
        tags: ['RAG'],
      },
      {
        id: 43,
        filename: 'Nature_2024_review.pdf',
        status: 'completed',
        progress: 1,
        tier: 'medium',
        source_lang: 'en',
        target_lang: 'zh',
        native: false,
        created_at: SEED_AT,
        stage: null,
        eta_seconds: null,
        elapsed_seconds: 128.7,
        started_at: SEED_AT,
        finished_at: SEED_AT,
        last_read_page: null,
        text_source: 'ocr',
        reading_status: 'reading',
        tags: ['双盲实验'],
      },
    ],
    collections: [
      { id: 1, name: '毕业论文', parent_id: null, sort: 0 },
      { id: 2, name: '文献综述', parent_id: 1, sort: 0 },
      { id: 3, name: '方法对比', parent_id: null, sort: 1 },
    ],
    task_collections: { 42: [1], 43: [2] },
    tags: [
      { id: 1, name: 'RAG', kind: 'topic' },
      { id: 2, name: '双盲实验', kind: 'method' },
      { id: 3, name: '待复现', kind: 'status' },
    ],
    task_tags: { 42: [{ name: 'RAG', kind: 'topic' }], 43: [{ name: '双盲实验', kind: 'method' }] },
    smart_collections: [
      { id: 1, name: '待读', query: { all: [{ field: 'reading_status', op: 'eq', value: 'todo' }] }, builtin: true },
      { id: 2, name: '在读', query: { all: [{ field: 'reading_status', op: 'eq', value: 'reading' }] }, builtin: true },
      { id: 3, name: '已读', query: { all: [{ field: 'reading_status', op: 'eq', value: 'done' }] }, builtin: true },
      { id: 4, name: '扫描件', query: { all: [{ field: 'text_source', op: 'eq', value: 'ocr' }] }, builtin: false },
    ],
    materials: [
      {
        id: 1,
        text_quote: '（mock 原文）读者信任一个答案，取决于能否跳回它出处的那句话。',
        translated_quote: 'Readers trust an answer when they can jump back to the sentence it came from.',
        page: 3,
        source_name: 'EBSCO_05-mono.pdf',
        note: '选题依据',
        task_id: 42,
        block_id: 'p2_b7',
        deleted_at: null,
        created_at: SEED_AT,
      },
      {
        id: 2,
        text_quote: '（mock 原文）这条素材卡的源文献已被删除，只剩快照。',
        translated_quote: null,
        page: 11,
        source_name: '已删除的文献.pdf',
        note: null,
        task_id: null,
        block_id: null,
        deleted_at: null,
        created_at: SEED_AT,
      },
    ],
    ask_logs: [
      {
        id: 1,
        task_id: 42,
        question: '这篇的方法和基线比强在哪？',
        answer: '（mock 回答）强在把译文与原文段落对齐，答案可以跳回原句。',
        source_block_ids: ['p2_b7'],
        created_at: SEED_AT,
      },
    ],
    memory_events: [
      {
        id: 1,
        task_id: 42,
        layer: 'L0',
        stage: 'translate',
        actor: 'api',
        tool: 'engine',
        summary: '正文发往模型 API 翻译（mock）',
        payload: { blocks: 42 },
        created_at: SEED_AT,
      },
      {
        id: 2,
        task_id: 42,
        layer: 'L0',
        stage: 'extract',
        actor: 'local',
        tool: 'engine',
        summary: '本地取字（mock）',
        payload: { blocks: 42, text_source: 'text-layer' },
        created_at: SEED_AT,
      },
    ],
    drafts: [
      {
        id: 1,
        title: '开题报告（mock）',
        body_md: '# 开题报告\n\n（mock 正文）[1] 说明了出处的意义。\n',
        template_id: null,
        created_at: SEED_AT,
        updated_at: SEED_AT,
      },
    ],
    citations: [
      {
        id: 1,
        draft_id: 1,
        material_id: 1,
        order: 1,
        csl_json: {
          id: 'material-1',
          type: 'article-journal',
          title: 'EBSCO_05-mono.pdf',
          'container-title': 'EBSCO_05-mono.pdf',
          page: '3',
          issued: { 'date-parts': [[2026]] },
        },
        anchor: { block_id: 'p2_b7', offset: 12 },
        created_at: SEED_AT,
      },
    ],
    check_runs: {
      12: {
        run_id: 12,
        step: { lang: 'zh', citation_style: 'numeric' },
        findings: [
          {
            id: 'f1',
            kind: 'missing_citation',
            severity: 'report',
            sentence: '（mock）研究表明，出处锚点显著提升阅读效率。',
            reason: '命中词：研究表明；前方 8 字内无豁免词',
            suggest: { material_id: 1, page: 3, quote: '（mock）读者信任一个答案…' },
            rule_ref: '§3.3 ②A 类',
          },
          {
            id: 'f2',
            kind: 'format',
            severity: 'unknown',
            sentence: '（mock）参考文献区只有 3 条。',
            reason: '未能识别引用制式（稿件未含版式信息）',
            suggest: null,
            rule_ref: '§2.7 未知档',
          },
        ],
        summary: { reported: 1, unknown: 1 },
      },
    },
    sessions: [
      { id: 1, created_at: SEED_AT, expires_at: '2026-11-13T02:00:00Z', last_seen_at: SEED_AT, user_agent: 'Chrome / Windows（mock）' },
      { id: 2, created_at: SEED_AT, expires_at: '2026-11-13T02:00:00Z', last_seen_at: SEED_AT, user_agent: 'Safari / iPhone（mock）' },
    ],
    // 埋点 1（N33 / N34）：译文改动与块曝光。⚠️ 曝光**按 (task, block, session) 去重**
    // —— mock 也照契约 §2.10 的唯一键做幂等，别让离线开发看到"重复上报长新行"。
    block_edits: [],
    block_exposures: [],
    // 记忆（M7 · N35–N39）：用法偏好。⚠️ 默认**空**——界面要如实显示"还没有记忆"，不许编
    memories: [],
    // 偏好（F · N40/N41）：整包键值。⚠️ 默认**空**——空包是"没存过"，前端靠它决定要不要迁移本机那份
    prefs: {},
    next_id: { collections: 4, smart_collections: 5, materials: 3, ask_logs: 2, drafts: 2, citations: 2, check_runs: 13, block_edits: 1, block_exposures: 1, memories: 1 },
  }
}

let state = seed()

/** 把假数据恢复到初始状态（单测之间互不影响；手动调试也能用）。 */
export function resetMockState() {
  state = seed()
}

/** 开关是否打开（**只认字符串 `'1'`**，`'true'` / `'on'` 一律当关闭）。 */
export function isMockEnabled() {
  try {
    return localStorage.getItem(MOCK_FLAG_KEY) === '1'
  } catch {
    // 隐私模式 / 非浏览器环境：没有 localStorage 就当关闭
    return false
  }
}

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------

function ok(body, status = 200, extra = {}) {
  return { status, body, ...extra }
}

function fail(status, detail) {
  return { status, body: { detail } }
}

/** `{param}` 段按"任意一段"匹配；其余段必须逐字相同。 */
function matchPath(pattern, path) {
  const want = pattern.split('/')
  const got = path.split('/')
  if (want.length !== got.length) return null
  const params = {}
  for (let i = 0; i < want.length; i += 1) {
    if (want[i].startsWith('{')) {
      if (!got[i]) return null
      params[want[i].slice(1, -1)] = decodeURIComponent(got[i])
      continue
    }
    if (want[i] !== got[i]) return null
  }
  return params
}

function methodOf(options) {
  return String((options && options.method) || 'GET').toUpperCase()
}

function stripTrailingSlash(path) {
  return path.length > 1 && path.endsWith('/') ? path.slice(0, -1) : path
}

/** 收 `/api/x?y=1` 与绝对地址两种写法（`apiUrl()` 拼出来的可能是绝对的）。 */
function parseTarget(target) {
  const raw = String(target || '')
  const url = new URL(raw, 'http://mock.local')
  return { path: stripTrailingSlash(url.pathname), query: url.searchParams }
}

function parseBody(options) {
  const body = options && options.body
  if (typeof body !== 'string') return {} // FormData / undefined（基线端点的上传）都当空
  try {
    const parsed = JSON.parse(body)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function intOf(value) {
  // ⚠️ 别直接 Number()：`Number(null) === 0`，会把"没传这个参数"当成"传了 0"，
  // 于是"没筛集合"变成"筛集合 0"，列表直接空掉（踩过一次）。
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isInteger(n) ? n : null
}

// ---------------------------------------------------------------------------
// 集合计数：`doc_count` 只数直接成员；`doc_count_deep` 含子集合
// ⚠️ 语义定死（契约 §2.1 / 数据模型 §2.1）：**子集合的文献不算在父集合里**
// ---------------------------------------------------------------------------

function directCount(collectionId) {
  return Object.values(state.task_collections).filter((ids) => ids.includes(collectionId)).length
}

function childIds(collectionId) {
  return state.collections.filter((item) => item.parent_id === collectionId).map((item) => item.id)
}

function deepCount(collectionId) {
  return directCount(collectionId) + childIds(collectionId).reduce((sum, id) => sum + deepCount(id), 0)
}

function collectionView(collection) {
  return {
    id: collection.id,
    name: collection.name,
    parent_id: collection.parent_id,
    sort: collection.sort,
    doc_count: directCount(collection.id),
    doc_count_deep: deepCount(collection.id),
  }
}

function descendantIds(collectionId) {
  return childIds(collectionId).flatMap((id) => [id, ...descendantIds(id)])
}

// ---------------------------------------------------------------------------
// 智能集合：`query` 是数据不是代码 —— 这里真的按规则算 count（在本地的假数据上）
// ---------------------------------------------------------------------------

const QUERY_FIELDS = ['reading_status', 'tag', 'collection', 'native', 'text_source']
const QUERY_OPS = ['eq', 'in', 'not_in']

function taskValue(task, field) {
  if (field === 'tag') return task.tags || []
  if (field === 'collection') return state.task_collections[task.id] || []
  return task[field]
}

function matchCondition(task, condition) {
  const actual = taskValue(task, condition.field)
  const expected = condition.value
  if (condition.op === 'eq') return Array.isArray(actual) ? actual.includes(expected) : actual === expected
  if (condition.op === 'in') return (Array.isArray(expected) ? expected : [expected]).some((v) => (Array.isArray(actual) ? actual.includes(v) : actual === v))
  return !(Array.isArray(expected) ? expected : [expected]).some((v) => (Array.isArray(actual) ? actual.includes(v) : actual === v))
}

function ruleMatches(task, query) {
  const conditions = (query && query.all) || []
  return conditions.every((condition) => matchCondition(task, condition))
}

function ruleCount(query) {
  return state.tasks.filter((task) => ruleMatches(task, query)).length
}

function queryValid(query) {
  const conditions = query && query.all
  if (!Array.isArray(conditions) || !conditions.length) return false
  return conditions.every(
    (item) =>
      item &&
      QUERY_FIELDS.includes(item.field) &&
      QUERY_OPS.includes(item.op) &&
      Object.prototype.hasOwnProperty.call(item, 'value'),
  )
}

function smartCollectionView(item) {
  return { id: item.id, name: item.name, query: item.query, count: ruleCount(item.query), builtin: item.builtin }
}

// ---------------------------------------------------------------------------
// N8：基线端点 `/api/tasks` 上追加的四个查询参数（**不是新端点**）
// ⚠️ 形状照契约 §1.4 的"列表项"逐字段给——**并且保持"返回裸数组"不变**
//   （改形状会打断所有调用方；契约 §2.2 专门写了这一条）
// ---------------------------------------------------------------------------

const TASK_FILTER_KEYS = ['reading_status', 'collection_id', 'tag', 'smart_id']

/** 列表项 16 个字段（契约 §1.4）：原样搬，不加减。 */
function taskCardView(task) {
  return {
    id: task.id,
    filename: task.filename,
    status: task.status,
    progress: task.progress,
    tier: task.tier,
    source_lang: task.source_lang,
    target_lang: task.target_lang,
    native: task.native,
    created_at: task.created_at,
    stage: task.stage,
    eta_seconds: task.eta_seconds,
    elapsed_seconds: task.elapsed_seconds,
    started_at: task.started_at,
    finished_at: task.finished_at,
    last_read_page: task.last_read_page,
    text_source: task.text_source,
  }
}

/** `?tag[]=A&tag[]=B` 与 `?tag=A` 两种写法都收（契约写的是 `tag[]`，手写 query 常写成 `tag`）。 */
function queryValues(query, key) {
  return [...query.getAll(`${key}[]`), ...query.getAll(key)].filter((value) => value !== '')
}

/** 这次请求带没带 N8 的参数——**不带就放行打真后端**（基线端点照旧是真的）。 */
function hasTaskFilter(query) {
  return TASK_FILTER_KEYS.some((key) => queryValues(query, key).length > 0)
}

/**
 * 单值参数取值：**必须和 `hasTaskFilter` 用同一套读法**（`key[]` 与 `key` 都认）。
 *
 * ⚠️ 这里踩过一次（issue #124）：`hasTaskFilter` 认 `key[]`、而下面几个参数只读 `key`，
 * 于是 `/api/tasks?reading_status[]=todo` **会被拦下来、却一条都不过滤 → 静默返回全量**。
 * 现在两边都走 `queryValues`：只要拦了，就一定按同一份口径筛。
 */
function firstValue(query, key) {
  const values = queryValues(query, key)
  return values.length ? values[0] : null
}

/** 多个参数取交集（AND）；`collection_id` 按**直接成员**算（与集合计数同一条语义）。 */
function taskMatchesFilters(task, query) {
  const reading = firstValue(query, 'reading_status')
  if (reading && task.reading_status !== reading) return false

  const collectionId = intOf(firstValue(query, 'collection_id'))
  if (collectionId !== null && !(state.task_collections[task.id] || []).includes(collectionId)) return false

  const tags = queryValues(query, 'tag')
  if (tags.length && !tags.every((name) => (task.tags || []).includes(name))) return false

  const smartId = intOf(firstValue(query, 'smart_id'))
  if (smartId !== null) {
    const smart = state.smart_collections.find((item) => item.id === smartId)
    if (!smart || !ruleMatches(task, smart.query)) return false
  }
  return true
}

// ---------------------------------------------------------------------------
// 素材卡 / 引文
// ---------------------------------------------------------------------------

function materialView(material) {
  return {
    id: material.id,
    text_quote: material.text_quote,
    translated_quote: material.translated_quote,
    page: material.page,
    source_name: material.source_name,
    note: material.note,
    task_id: material.task_id,
    block_id: material.block_id,
    deleted_at: material.deleted_at,
    created_at: material.created_at,
  }
}

/** CSL-JSON 1.0.2 单条 item：**只填快照里真有的**（作者/DOI 这些快照里没有的，不编）。 */
function cslFromMaterial(material) {
  return {
    id: `material-${material.id}`,
    type: 'article-journal',
    title: material.source_name,
    'container-title': material.source_name,
    page: String(material.page),
    ...(material.note ? { note: material.note } : {}),
  }
}

function citationView(citation) {
  return {
    id: citation.id,
    draft_id: citation.draft_id,
    material_id: citation.material_id,
    order: citation.order,
    csl_json: citation.csl_json,
    anchor: citation.anchor,
  }
}

function draftView(draft) {
  return {
    id: draft.id,
    title: draft.title,
    body_md: draft.body_md,
    template_id: draft.template_id,
    updated_at: draft.updated_at,
    citations: state.citations.filter((item) => item.draft_id === draft.id).map(citationView),
  }
}

function citationsOf(draftId) {
  return state.citations
    .filter((item) => item.draft_id === draftId)
    .sort((a, b) => a.order - b.order)
    .map(citationView)
}

// ---------------------------------------------------------------------------
// 台账（N17 / N26 同源：**只有一份 memory_events**）
// ---------------------------------------------------------------------------

function memoryEvents(taskId, layer, limit) {
  let rows = state.memory_events
  if (taskId !== '') rows = rows.filter((item) => String(item.task_id) === String(taskId))
  if (layer) rows = rows.filter((item) => item.layer === layer)
  const max = Number(limit)
  return Number.isFinite(max) && max > 0 ? rows.slice(0, max) : rows
}

const LEDGER_HEADER = 'created_at,layer,stage,actor,tool,summary'

function ledgerCsv(rows) {
  const cell = (value) => `"${String(value ?? '').replace(/"/g, '""')}"`
  const lines = rows.map((item) =>
    [item.created_at, item.layer, item.stage, item.actor, item.tool, item.summary].map(cell).join(','),
  )
  return [LEDGER_HEADER, ...lines].join('\n')
}

function ledgerMarkdown(rows) {
  const lines = rows.map((item) => `| ${item.created_at} | ${item.stage} | ${item.actor} | ${item.summary} |`)
  return ['| 时间 | 环节 | 数据流向 | 说明 |', '|---|---|---|---|', ...lines].join('\n')
}

function exportMarkdown() {
  return [
    '# docwise 数据导出（mock）',
    '',
    '⚠️ 这是 mock 生成的假导出，用来把"导出"这条交互做完。',
    '- 文献：2 篇',
    '- 素材卡：2 条',
    '- 草稿：1 篇',
  ].join('\n')
}

// ---------------------------------------------------------------------------
// 每个端点的处理（键 = `METHOD 路径`）
// ---------------------------------------------------------------------------

const HANDLERS = {
  // ---- §2.1 集合
  'GET /api/collections': () => ok({ items: state.collections.map(collectionView) }),

  'POST /api/collections': ({ body }) => {
    const name = String(body.name ?? '').trim()
    if (!name || name.length > 64) return fail(400, '名字要 1–64 个字')
    const parentId = body.parent_id === undefined || body.parent_id === null ? null : intOf(body.parent_id)
    if (parentId !== null && !state.collections.some((item) => item.id === parentId)) {
      return fail(400, '父集合不存在')
    }
    if (state.collections.some((item) => item.parent_id === parentId && item.name === name)) {
      return fail(400, '同一个父集合下不许重名')
    }
    const created = { id: state.next_id.collections, name, parent_id: parentId, sort: 0 }
    state.next_id.collections += 1
    state.collections.push(created)
    return ok(collectionView(created), 201)
  },

  'PATCH /api/collections/{id}': ({ params, body }) => {
    const collection = state.collections.find((item) => item.id === Number(params.id))
    if (!collection) return fail(404, '集合不存在')
    if (body.name !== undefined) {
      const name = String(body.name).trim()
      if (!name || name.length > 64) return fail(400, '名字要 1–64 个字')
      collection.name = name
    }
    if (body.parent_id !== undefined) {
      const parentId = body.parent_id === null ? null : intOf(body.parent_id)
      if (parentId !== null && !state.collections.some((item) => item.id === parentId)) {
        return fail(400, '父集合不存在')
      }
      // ⚠️ 成环挡在服务端（契约 §2.1）：不许把自己移进自己的后代
      if (parentId === collection.id || (parentId !== null && descendantIds(collection.id).includes(parentId))) {
        return fail(400, '不许把集合移进自己的后代')
      }
      collection.parent_id = parentId
    }
    if (body.sort !== undefined) collection.sort = intOf(body.sort) ?? collection.sort
    return ok(collectionView(collection))
  },

  'DELETE /api/collections/{id}': ({ params }) => {
    const id = Number(params.id)
    const collection = state.collections.find((item) => item.id === id)
    if (!collection) return fail(404, '集合不存在')
    // ⚠️ 先算再删：`directCount` 读的是关联表，关联清空之后算出来永远是 0（踩过一次）
    const moved = childIds(id).length + directCount(id)
    const children = state.collections.filter((item) => item.parent_id === id)
    children.forEach((child) => {
      child.parent_id = collection.parent_id
    })
    state.collections = state.collections.filter((item) => item.id !== id)
    // 挂在这个集合上的文献：**只删集合，不动文献**（它们回到父集合）
    Object.values(state.task_collections).forEach((ids) => {
      const index = ids.indexOf(id)
      if (index >= 0) ids.splice(index, 1)
    })
    return ok({ deleted: true, moved_to_parent: moved })
  },

  // ---- §2.2 归集与标签
  'PUT /api/tasks/{task_id}/collections': ({ params, body }) => {
    const taskId = Number(params.task_id)
    const ids = Array.isArray(body.collection_ids) ? body.collection_ids.map(intOf) : null
    if (!ids || ids.some((id) => id === null)) return fail(400, 'collection_ids 要是整数数组')
    const unknown = ids.find((id) => !state.collections.some((item) => item.id === id))
    if (unknown !== undefined) return fail(400, `集合不存在：${unknown}`)
    state.task_collections[taskId] = [...new Set(ids)]
    return ok({ collection_ids: state.task_collections[taskId] })
  },

  'GET /api/tags': ({ query }) => {
    const kind = query.get('kind') || ''
    const rows = state.tags.filter((tag) => !kind || tag.kind === kind)
    return ok({
      items: rows.map((tag) => ({
        id: tag.id,
        name: tag.name,
        kind: tag.kind,
        doc_count: Object.values(state.task_tags).filter((list) => list.some((item) => item.name === tag.name)).length,
      })),
    })
  },

  'PUT /api/tasks/{task_id}/tags': ({ params, body }) => {
    const taskId = Number(params.task_id)
    const wanted = Array.isArray(body.tags) ? body.tags : []
    const invalid = wanted.find((tag) => !tag || !String(tag.name || '').trim() || !['topic', 'method', 'status'].includes(tag.kind))
    if (invalid) return fail(400, 'tags 要形如 [{name, kind}]，kind ∈ {topic, method, status}')
    const saved = wanted.map((tag) => {
      const name = String(tag.name).trim()
      let row = state.tags.find((item) => item.name === name && item.kind === tag.kind)
      if (!row) {
        row = { id: state.tags.length + 1, name, kind: tag.kind }
        state.tags.push(row)
      }
      return { id: row.id, name: row.name, kind: row.kind }
    })
    state.task_tags[taskId] = saved.map((tag) => ({ name: tag.name, kind: tag.kind }))
    return ok({ tags: saved })
  },

  // ---- §2.3 智能集合
  'GET /api/smart-collections': () => ok({ items: state.smart_collections.map(smartCollectionView) }),

  'POST /api/smart-collections': ({ body }) => {
    const name = String(body.name ?? '').trim()
    if (!name || name.length > 64) return fail(400, '名字要 1–64 个字')
    if (!queryValid(body.query)) {
      return fail(400, `query 要是 {all: [{field, op, value}]}，field ∈ {${QUERY_FIELDS.join(', ')}}，op ∈ {${QUERY_OPS.join(', ')}}`)
    }
    const created = { id: state.next_id.smart_collections, name, query: body.query, builtin: false }
    state.next_id.smart_collections += 1
    state.smart_collections.push(created)
    return ok(smartCollectionView(created), 201)
  },

  'DELETE /api/smart-collections/{id}': ({ params }) => {
    const id = Number(params.id)
    const row = state.smart_collections.find((item) => item.id === id)
    if (!row) return fail(404, '智能集合不存在')
    if (row.builtin) return fail(400, '内置规则不许删')
    state.smart_collections = state.smart_collections.filter((item) => item.id !== id)
    return ok({ deleted: true, id })
  },

  // ---- §2.4 素材卡
  'POST /api/materials': ({ body }) => {
    const taskId = intOf(body.task_id)
    const blockId = String(body.block_id ?? '').trim()
    const task = state.tasks.find((item) => item.id === taskId)
    // 契约 §2.4：404「块不存在」。mock 这边只认得假数据里那两篇文献的块
    if (!task || !blockId) return fail(404, '块不存在')
    const pageMatch = /^p(\d+)_b\d+$/.exec(blockId)
    const created = {
      id: state.next_id.materials,
      // 快照字段：真后端是"创建时深拷贝原文/译文/页码/文献名"
      text_quote: `（mock 原文）${task.filename} 的 ${blockId} 这一段。`,
      translated_quote: task.native ? null : `（mock 译文）${task.filename} 的 ${blockId} 这一段。`,
      page: pageMatch ? Number(pageMatch[1]) + 1 : 1, // block_id 里页序从 0 起，显示要 +1
      source_name: task.filename,
      note: body.note ? String(body.note) : null,
      task_id: task.id,
      block_id: blockId,
      deleted_at: null,
      created_at: new Date().toISOString(),
    }
    state.next_id.materials += 1
    state.materials.push(created)
    return ok(materialView(created), 201)
  },

  'GET /api/materials': ({ query }) => {
    const taskId = query.get('task_id') || ''
    const collectionId = intOf(query.get('collection_id'))
    const tag = query.get('tag') || ''
    let rows = state.materials.filter((item) => item.deleted_at === null) // 软删的不出现在列表
    if (taskId) rows = rows.filter((item) => String(item.task_id) === String(taskId))
    if (collectionId !== null) {
      rows = rows.filter((item) => (state.task_collections[item.task_id] || []).includes(collectionId))
    }
    if (tag) {
      rows = rows.filter((item) => (state.task_tags[item.task_id] || []).some((entry) => entry.name === tag))
    }
    return ok({ items: rows.map(materialView) })
  },

  'DELETE /api/materials/{id}': ({ params }) => {
    const material = state.materials.find((item) => item.id === Number(params.id))
    if (!material) return fail(404, '素材不存在')
    material.deleted_at = new Date().toISOString() // 软删 7 天（设计规范 §7.7）
    return ok({ deleted: true, id: material.id, deleted_at: material.deleted_at })
  },

  // ---- §2.5 问答落库与台账
  'POST /api/ask-logs': ({ body }) => {
    if (!Array.isArray(body.source_block_ids)) return fail(400, 'source_block_ids 要是字符串数组')
    const created = {
      id: state.next_id.ask_logs,
      task_id: intOf(body.task_id),
      question: String(body.question ?? ''),
      answer: String(body.answer ?? ''),
      source_block_ids: body.source_block_ids.map(String),
      created_at: new Date().toISOString(),
    }
    state.next_id.ask_logs += 1
    state.ask_logs.push(created)
    return ok({ id: created.id }, 201) // 契约就是这个形状：201 {id}
  },

  'GET /api/ask-logs': ({ query }) => {
    const taskId = query.get('task_id') || ''
    const rows = taskId ? state.ask_logs.filter((item) => String(item.task_id) === String(taskId)) : state.ask_logs
    return ok({ items: rows })
  },

  'GET /api/memory-events': ({ query }) => {
    const rows = memoryEvents(query.get('task_id') || '', query.get('layer') || '', query.get('limit') || '')
    return ok({ items: rows })
  },

  'POST /api/memory-events': () =>
    // ⚠️ 契约 §2.5：这个 POST 只给服务端内部用（写入方是服务端，不是前端手工埋点）。
    // 所以 mock 这里**故意不返回假数据**——前端真去调它，说明埋点写错了地方。
    fail(405, 'N17 的 POST 只给服务端内部用（契约 §2.5）：前端只调 GET，不许手工埋点'),

  // ---- §2.9 埋点：译文改动与块曝光（N33 / N34）
  'POST /api/block-edits': ({ body }) => {
    const taskId = intOf(body.task_id)
    if (!state.tasks.some((item) => item.id === taskId)) return fail(404, '任务不存在')
    const blockId = String(body.block_id ?? '')
    if (!blockId) return fail(400, 'block_id 不能为空')
    const after = String(body.after ?? '').trim()
    const before = String(body.before ?? '').trim()
    if (!after) return fail(400, '译文不能清空；要撤销请重新编辑')
    if (after === before) return fail(400, '译文没有变化，未记录')
    const created = {
      id: state.next_id.block_edits,
      task_id: taskId,
      block_id: blockId,
      before: String(body.before ?? ''),
      after,
      // 真后端由服务端算原文 sha256；mock 不持有原文，**如实给空串**而不是编一个哈希
      text_hash: '',
      created_at: new Date().toISOString(),
    }
    state.next_id.block_edits += 1
    state.block_edits.push(created)
    return ok({ id: created.id, block_id: blockId, edited: true }, 201)
  },

  'GET /api/block-edits': ({ query }) => {
    const taskId = query.get('task_id') || ''
    const blockId = query.get('block_id') || ''
    const rows = state.block_edits.filter(
      (item) =>
        (!taskId || String(item.task_id) === String(taskId)) &&
        (!blockId || item.block_id === blockId),
    )
    // 新的在前（与真后端一致）
    return ok({ items: [...rows].reverse() })
  },

  'POST /api/block-exposures': ({ body }) => {
    const taskId = intOf(body.task_id)
    if (!state.tasks.some((item) => item.id === taskId)) return fail(404, '任务不存在')
    const blockId = String(body.block_id ?? '')
    const sessionId = String(body.session_id ?? '')
    if (!blockId || !sessionId) return fail(400, 'block_id 与 session_id 都不能为空')
    const hit = state.block_exposures.find(
      (item) =>
        item.task_id === taskId &&
        item.block_id === blockId &&
        item.session_id === sessionId,
    )
    // ⭐ 幂等（契约 §2.10 的唯一键）：重复上报**不长新行**
    if (hit) return ok({ id: hit.id, created: false }, 201)
    const created = {
      id: state.next_id.block_exposures,
      task_id: taskId,
      block_id: blockId,
      session_id: sessionId,
      created_at: new Date().toISOString(),
    }
    state.next_id.block_exposures += 1
    state.block_exposures.push(created)
    return ok({ id: created.id, created: true }, 201)
  },

  // ---- §2.10 记忆（M7：N35–N39）用法偏好
  'GET /api/memories': ({ query }) => {
    const kind = query.get('kind') || ''
    if (kind && kind !== 'term' && kind !== 'cite') return fail(400, 'kind 只能是 term 或 cite')
    const enabledQ = query.get('enabled')
    let rows = [...state.memories]
    if (kind) rows = rows.filter((item) => item.kind === kind)
    if (enabledQ === 'true') rows = rows.filter((item) => item.enabled)
    else if (enabledQ === 'false') rows = rows.filter((item) => !item.enabled)
    rows.sort((a, b) => b.id - a.id)
    // ⭐ counts 用**全量**（不受筛选影响），否则界面上的数字会互相矛盾
    const counts = { term: 0, cite: 0 }
    const enabledCounts = { term: 0, cite: 0 }
    for (const item of state.memories) {
      counts[item.kind] += 1
      if (item.enabled) enabledCounts[item.kind] += 1
    }
    return ok({ items: rows, counts, enabled_counts: enabledCounts })
  },

  'POST /api/memories': ({ body }) => {
    const kind = String(body.kind ?? 'term').trim().toLowerCase()
    if (kind !== 'term' && kind !== 'cite') return fail(400, 'kind 只能是 term 或 cite')
    // ⭐ 引用习惯的 source 固定归一成 default（真后端同一口径）：它天然只有一条
    const source = kind === 'cite' ? 'default' : String(body.source ?? '').trim()
    if (!source) return fail(400, 'source 不能为空')
    const target = String(body.target ?? '').trim()
    if (!target) return fail(400, 'target 不能为空')
    const enabled = body.enabled === undefined ? true : Boolean(body.enabled)
    // ⭐ 按 (kind, source) 幂等：同一个词再存一次是**改**，不堆第二行
    const hit = state.memories.find((item) => item.kind === kind && item.source === source)
    if (hit) {
      hit.target = target
      hit.enabled = enabled
      // ⚠️ 改说法**不许把 hits 清零**（那是"真被用上几次"的账）
      hit.updated_at = new Date().toISOString()
      return ok({ item: hit, created: false }, 201)
    }
    const created = {
      id: state.next_id.memories,
      kind,
      source,
      target,
      hits: 0,
      enabled,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    state.next_id.memories += 1
    state.memories.push(created)
    return ok({ item: created, created: true }, 201)
  },

  'PATCH /api/memories/{id}': ({ params, body }) => {
    const hit = state.memories.find((item) => item.id === intOf(params.id))
    if (!hit) return fail(404, '记忆不存在')
    if (body.target === undefined && body.enabled === undefined) {
      return fail(400, '没有要改的字段')
    }
    if (body.target !== undefined) {
      const target = String(body.target).trim()
      if (!target) return fail(400, 'target 不能为空')
      hit.target = target
    }
    if (body.enabled !== undefined) hit.enabled = Boolean(body.enabled)
    hit.updated_at = new Date().toISOString()
    return ok({ item: hit })
  },

  'DELETE /api/memories/{id}': ({ params }) => {
    const id = intOf(params.id)
    const at = state.memories.findIndex((item) => item.id === id)
    if (at < 0) return fail(404, '记忆不存在')
    // ⭐ 真删（记忆不是留痕）
    state.memories.splice(at, 1)
    return ok({ deleted: true, id })
  },

  'GET /api/memories/resolve': () => {
    const terms = {}
    let cite = null
    for (const item of state.memories) {
      if (!item.enabled) continue
      if (item.kind === 'term') terms[item.source] = item.target
      else if (item.kind === 'cite') cite = item.target
      item.hits += 1
    }
    return ok({ terms, cite, counts: { term: Object.keys(terms).length, cite: cite ? 1 : 0 } })
  },

  // ---- §2.6 起草
  'GET /api/drafts': () => ok({ items: state.drafts.map(draftView) }),

  'POST /api/drafts': ({ body }) => {
    const title = String(body.title ?? '').trim()
    if (!title || title.length > 200) return fail(400, '标题要 1–200 个字')
    const created = {
      id: state.next_id.drafts,
      title,
      body_md: '',
      template_id: body.template_id ? String(body.template_id) : null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    state.next_id.drafts += 1
    state.drafts.push(created)
    return ok(draftView(created), 201)
  },

  'GET /api/drafts/{id}': ({ params }) => {
    const draft = state.drafts.find((item) => item.id === Number(params.id))
    return draft ? ok(draftView(draft)) : fail(404, '草稿不存在')
  },

  'PATCH /api/drafts/{id}': ({ params, body }) => {
    const draft = state.drafts.find((item) => item.id === Number(params.id))
    if (!draft) return fail(404, '草稿不存在')
    if (body.title !== undefined) {
      const title = String(body.title).trim()
      if (!title || title.length > 200) return fail(400, '标题要 1–200 个字')
      draft.title = title
    }
    if (body.body_md !== undefined) draft.body_md = String(body.body_md)
    if (body.template_id !== undefined) draft.template_id = body.template_id === null ? null : String(body.template_id)
    draft.updated_at = new Date().toISOString()
    return ok(draftView(draft))
  },

  'DELETE /api/drafts/{id}': ({ params }) => {
    const draft = state.drafts.find((item) => item.id === Number(params.id))
    if (!draft) return fail(404, '草稿不存在')
    const view = draftView(draft)
    state.citations = state.citations.filter((item) => item.draft_id !== draft.id)
    state.drafts = state.drafts.filter((item) => item.id !== draft.id)
    return ok(view)
  },

  'POST /api/drafts/{id}/citations': ({ params, body }) => {
    const draft = state.drafts.find((item) => item.id === Number(params.id))
    if (!draft) return fail(404, '草稿不存在')
    const material = state.materials.find((item) => item.id === intOf(body.material_id) && item.deleted_at === null)
    if (!material) return fail(404, '素材不存在')
    const order = citationsOf(draft.id).length + 1
    const created = {
      id: state.next_id.citations,
      draft_id: draft.id,
      material_id: material.id,
      order,
      // ⭐ 插入时就生成并落库：CSL-JSON 是 M4 格式检查的唯一输入
      csl_json: cslFromMaterial(material),
      anchor: { block_id: material.block_id, offset: intOf(body.anchor && body.anchor.offset) ?? 0 },
      created_at: new Date().toISOString(),
    }
    state.next_id.citations += 1
    state.citations.push(created)
    return ok(citationView(created), 201)
  },

  'GET /api/drafts/{id}/citations': ({ params }) => {
    const draftId = Number(params.id)
    if (!state.drafts.some((item) => item.id === draftId)) return fail(404, '草稿不存在')
    return ok({ items: citationsOf(draftId) })
  },

  'DELETE /api/drafts/{id}/citations': ({ params }) => {
    const draftId = Number(params.id)
    if (!state.drafts.some((item) => item.id === draftId)) return fail(404, '草稿不存在')
    const removed = citationsOf(draftId).length
    state.citations = state.citations.filter((item) => item.draft_id !== draftId)
    return ok({ deleted: true, count: removed })
  },

  // ---- §2.6 参考文献格式化（N31）
  // ⚠️ **mock 不排版**：真正的 CSL 渲染在引擎侧（citeproc-py + 样式数据），离线这里只保证
  // **形状与契约一致**、条目数跟着引文走。所以示例条目带"（示例条目）"前缀——
  // 别把它当成"真格式化结果"，也别拿它去核对期刊样式。
  'GET /api/drafts/{id}/bibliography': ({ params, query }) => {
    const draftId = Number(params.id)
    if (!state.drafts.some((item) => item.id === draftId)) return fail(404, '草稿不存在')
    const style = String(query.get('style') || '')
    if (!BIB_STYLES.includes(style)) {
      return fail(400, `style 只支持 ${BIB_STYLES.join(' / ')}`)
    }
    const cites = citationsOf(draftId)
    const entries = cites.map((item, index) => {
      const material = state.materials.find((m) => m.id === item.material_id)
      const name = material ? material.source_name : '（来源未知）'
      return `[${index + 1}]（示例条目 · ${style}）${name}`
    })
    return ok({
      style,
      locale: null,
      entries,
      item_texts: Object.fromEntries(
        cites.map((item, index) => [`material-${item.material_id}`, entries[index]]),
      ),
      count: entries.length,
      skipped: [],
      styles: BIB_STYLES,
    })
  },

  // ---- §2.7 收口检查
  'POST /api/check': ({ body }) => {
    if (!body.draft_id || typeof body.doc_text !== 'string') return fail(400, '要 {draft_id, doc_text}')
    const runId = state.next_id.check_runs
    state.next_id.check_runs += 1
    const template = state.check_runs[12]
    // 报告内容是**固定示例**：契约冻的是形状，结论得由真后端算出来
    const report = { ...structuredClone(template), run_id: runId }
    state.check_runs[runId] = report
    return ok(report)
  },

  'GET /api/check/{run_id}': ({ params }) => {
    const report = state.check_runs[Number(params.run_id)]
    return report ? ok(structuredClone(report)) : fail(404, '这次检查记录不存在')
  },

  // ---- §2.8 我的数据与台账
  'GET /api/me/storage': () =>
    ok({
      total_bytes: 1288490188,
      by_kind: { uploads: 402653184, outputs: 805306368, backups: 67108864, db: 12582912 },
      location: '（mock）data/',
    }),

  'GET /api/me/export': ({ query }) => {
    const format = query.get('format') || 'zip'
    if (format === 'md') {
      return ok(exportMarkdown(), 200, { contentType: 'text/markdown; charset=utf-8', filename: 'docwise-export.md' })
    }
    if (format === 'zip') {
      // 空 ZIP（结构合法）：mock 不造内容，但也不给一个打不开的假文件
      return ok(EMPTY_ZIP, 200, { contentType: 'application/zip', filename: 'docwise-export.zip' })
    }
    return fail(400, 'format 只支持 zip / md')
  },

  'GET /api/me/ledger': ({ query }) => {
    const format = query.get('format') || 'json'
    const rows = memoryEvents('', '', '')
    if (format === 'json') return ok({ items: rows }) // 与 N17 同源同形状
    if (format === 'csv') return ok(ledgerCsv(rows), 200, { contentType: 'text/csv; charset=utf-8', filename: 'docwise-ledger.csv' })
    if (format === 'md') return ok(ledgerMarkdown(rows), 200, { contentType: 'text/markdown; charset=utf-8', filename: 'docwise-ledger.md' })
    return fail(400, 'format 只支持 json / csv / md')
  },

  'DELETE /api/me': () => ok({ deleted: true, id: state.user.id }),

  'PATCH /api/me': ({ body }) => {
    if (body.display_name !== undefined) {
      const name = String(body.display_name ?? '').trim()
      if (!name || name.length > 64) return fail(400, '显示名要 1–64 个字')
      state.user.display_name = name
    }
    return ok({ ...state.user })
  },

  'GET /api/me/sessions': () => ok({ items: state.sessions.map((item) => ({ ...item })) }),

  'DELETE /api/me/sessions/{id}': ({ params }) => {
    const id = Number(params.id)
    if (!state.sessions.some((item) => item.id === id)) return fail(404, '会话不存在')
    state.sessions = state.sessions.filter((item) => item.id !== id)
    return ok({ deleted: true, id })
  },

  // ---- N40 / N41 偏好：服务端权威（与后端同口径：整包覆盖、只收标量、≤32 项 / ≤8KB）
  // ---- N42 概览：真数（mock 的库里有几条就报几条）
  'GET /api/me/overview': () => ok({
    tasks: state.tasks.length,
    archived_tasks: 0,
    blocks: state.tasks.length * 3,
    materials: state.materials.length,
    drafts: state.drafts.length,
    citations: state.drafts.reduce((n, d) => n + (d.citations?.length || 0), 0),
    check_runs: state.check_runs.length,
  }),

  // ---- N43 检查历史：只带摘要（明细走 N23）
  'GET /api/check': ({ query }) => {
    const draftId = Number(query.get('draft_id'))
    const rows = state.check_runs
      .filter((row) => !draftId || row.draft_id === draftId)
      .slice()
      .reverse()
      .slice(0, 50)
      .map((row) => ({
        id: row.id,
        draft_id: row.draft_id,
        lang: row.report?.step?.lang ?? 'zh',
        citation_style: row.report?.step?.citation_style ?? 'numeric',
        ruleset_version: row.report?.ruleset_version ?? 2,
        created_at: row.created_at,
        summary: row.report?.summary ?? { reported: 0, unknown: 0 },
      }))
    return ok({ items: rows })
  },

  'GET /api/me/preferences': () => ok({ prefs: { ...state.prefs } }),

  'PUT /api/me/preferences': ({ body }) => {
    const prefs = body && typeof body.prefs === 'object' && body.prefs ? body.prefs : null
    if (!prefs) return fail(400, '要给 {prefs: {...}}')
    const keys = Object.keys(prefs)
    if (keys.length > 32) return fail(400, '偏好项太多')
    for (const key of keys) {
      const value = prefs[key]
      if (value !== null && !['boolean', 'number', 'string'].includes(typeof value)) {
        return fail(400, `偏好 ${key} 只能是标量（布尔/数字/文本）`)
      }
    }
    state.prefs = { ...prefs }
    return ok({ prefs: { ...state.prefs }, updated_at: '2026-10-17T00:00:00Z' })
  },

  // ---- 基线端点上的两处"追加"（N8 / N30，清单见 MOCK_DELTAS）----

  // N8：给基线 `/api/tasks` 加查询参数。**仍然是裸数组**（改形状会打断所有调用方），
  // 只是把结果按参数筛一遍；参数取交集。
  'GET /api/tasks': ({ query }) =>
    ok(state.tasks.filter((task) => taskMatchesFilters(task, query)).map(taskCardView)),

  // N30：基线 `/api/auth/me` 的响应**只追加** `last_login_at`，既有 6 字段逐字不动。
  'GET /api/auth/me': () => ok({ ...state.user, last_login_at: state.last_login_at }),
}

const DELTA_ROUTES = new Map(MOCK_DELTAS.map((item) => [`${item.method} ${item.path}`, item]))

/** N8 / N30 这两处"追加"的命中判断（**基线端点大部分请求仍要放行**）。 */
function lookupDelta(method, path, query) {
  const tasks = DELTA_ROUTES.get('GET /api/tasks')
  // N8：只有带了查询参数才拦——不带参数时它还是那条基线端点，得打真后端
  if (method === 'GET' && query && hasTaskFilter(query) && matchPath(tasks.path, path)) {
    return { route: tasks, params: {} }
  }
  const me = DELTA_ROUTES.get('GET /api/auth/me')
  if (method === 'GET' && matchPath(me.path, path)) {
    return { route: me, params: {} }
  }
  return null
}

function lookup(method, path, query) {
  for (const route of MOCK_ROUTES) {
    if (route.method !== method) continue
    const params = matchPath(route.path, path)
    if (params) return { route, params }
  }
  return lookupDelta(method, path, query)
}

/**
 * 这个请求命中了清单里的哪一条路由（没命中返回 null）。
 *
 * 给"清单里每条路由都得有用例"这类对账用：用例写的是具体路径（`/api/drafts/1`），
 * 要反查它落在哪条模式（`/api/drafts/{id}`）上。
 */
export function mockRouteFor(method, path) {
  const { path: pathname } = parseTarget(path)
  const hit = lookup(String(method).toUpperCase(), pathname)
  return hit ? hit.route : null
}

/**
 * mock 的入口（契约 §4 冻的签名）：返回 `{status, body}`；
 * 带文件的端点再带 `contentType` / `filename`。
 *
 * ⚠️ **没覆盖的路径直接抛错**（`tests/contract-mock.test.js` 专门盯着这条）——
 * **不许静默返回空对象**：那会让前端以为"接口就是空的"，比报错难查得多。
 */
export function mockFetch(path, options = {}) {
  const { path: pathname, query } = parseTarget(path)
  const method = methodOf(options)
  const hit = lookup(method, pathname, query)
  if (!hit) {
    throw new Error(
      `契约 mock 没覆盖这个请求：${method} ${pathname}
（mock 只覆盖契约 §2 里的新增端点 N1–N29、以及 N8 / N30 两处追加，基线端点照旧打真后端；
 ⚠️ N8 要带查询参数才算（不带参数时它还是那条基线端点）；
 清单见 src/mock/contract.js 的 MOCK_ROUTES / MOCK_DELTAS——要加端点先改契约再改这里）`,
    )
  }
  const handler = HANDLERS[`${method} ${hit.route.path}`]
  return handler({ params: hit.params, query, body: parseBody(options), path: pathname })
}

/**
 * 给请求层用的一层薄适配：**开关关着、或不是 mock 覆盖的路径 → 返回 null（原样放行）**。
 *
 * 为什么"不是 mock 覆盖的路径"要放行而不是抛错：基线那 25 个端点**必须继续打真后端**，
 * 否则开关一开整个应用就没法用了。抛错只保留在 `mockFetch()` 上（你显式问它要一个
 * mock 却没覆盖时才该炸）。
 */
export function mockResponse(path, options = {}) {
  if (!isMockEnabled()) return null
  const { path: pathname, query } = parseTarget(path)
  if (!lookup(methodOf(options), pathname, query)) return null
  const result = mockFetch(path, options)
  const headers = {}
  if (result.contentType) headers['Content-Type'] = result.contentType
  else if (result.body !== null && result.body !== undefined && typeof result.body !== 'string') {
    headers['Content-Type'] = 'application/json'
  }
  const body =
    result.status === 204 || result.body === null || result.body === undefined || typeof result.body === 'string'
      ? result.body ?? null
      : JSON.stringify(result.body)
  return new Response(body, { status: result.status, headers })
}
