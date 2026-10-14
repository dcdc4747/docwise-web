/**
 * 哈希路由（**不引 vue-router** —— 形态 §7 定的：左栏路由只做单页切换，不值当引一个依赖）。
 *
 * 这个模块**只认识地址，不认识数据**：
 * 它把 `location.hash` 解析成 `{ name, params }`，再把 `{ name, params }` 拼回地址。
 * **至于"进阅读页要拉哪篇论文的数据"——那是调用方的事，这里一个字都不知道。**
 * 这么切的理由：路由与界面状态各管一摊，谁改谁都不会牵动对方（契约 §2）。
 *
 * 四个函数签名是**契约冻结的**（`docs/契约_前端命名与拆分_v1_20261014.md` §2.1），不要自己改名。
 */

/** 路由表：`name` → 路径模式。`:taskId` 这类是参数段。 */
export const ROUTES = {
  library: '/',
  read: '/read/:taskId',
  write: '/write',
  memory: '/memory',
  process: '/process',
  me: '/me',
  admin: '/admin',
}

/** 兜底路由：未知地址一律落这里（**不许报错、不许白屏**）。 */
export const FALLBACK_ROUTE = 'library'

/** 去掉开头可能出现的 `#`，统一成 `'/'` 起头的路径。 */
function normalizePath(raw) {
  let path = String(raw ?? '').trim()
  if (path.startsWith('#')) path = path.slice(1)
  if (!path.startsWith('/')) path = `/${path}`
  // 去掉查询串与末尾斜杠（`/read/12?tab=guide` → `/read/12`）
  path = path.split('?')[0]
  if (path.length > 1 && path.endsWith('/')) path = path.slice(0, -1)
  return path
}

/** 把路径按路由表切成段，便于逐段比对。 */
function segments(path) {
  return path.split('/').filter(Boolean)
}

/**
 * 解析一段地址 → `{ name, params }`。
 *
 * **不知道的地址一律返回 library**（契约 §2.1 纪律 2：未知 hash → 落到库页，不报错、不白屏）。
 * 参数校验也在这一层（纪律 3）：`#/read/abc`、`#/read/0` 这种**任务号不合法的一律当"不认识的地址"落库页**——
 * 这样调用方永远不用处理"进了阅读页但没有任务号"这种半吊子状态。
 *
 * @param {string} hash 例：`#/read/12`、`/write`、`''`
 * @returns {{name: string, params: {taskId?: number}}}
 */
export function parseHash(hash) {
  const path = normalizePath(hash)
  const parts = segments(path)

  if (parts.length === 0) return { name: 'library', params: {} }

  const [head, ...rest] = parts
  const name = Object.keys(ROUTES).find((key) => {
    const pattern = segments(ROUTES[key])
    return pattern.length > 0 && pattern[0] === head
  })

  if (!name) return { name: FALLBACK_ROUTE, params: {} }

  const pattern = segments(ROUTES[name])
  // 段数对不上就不是这个路由（例：`/read` 少一段、`/library/x` 多一段）
  if (pattern.length !== parts.length) return { name: FALLBACK_ROUTE, params: {} }

  const params = {}
  for (let i = 1; i < pattern.length; i += 1) {
    const key = pattern[i].startsWith(':') ? pattern[i].slice(1) : null
    if (key) params[key] = rest[i - 1]
  }

  if (name === 'read') {
    const id = Number(params.taskId)
    // 任务号必须是正整数；不合法就当作"不认识的地址"落库页（见上面的说明）
    if (!Number.isInteger(id) || id <= 0) return { name: FALLBACK_ROUTE, params: {} }
    params.taskId = id
  }

  return { name, params }
}

/**
 * `{ name, params }` → 地址串（**带 `#`**，可直接赋给 `location.hash`）。
 * 未知 name 落兜底路由（与 parseHash 对称，不会拼出坏地址）。
 */
export function buildHash(name, params = {}) {
  const key = Object.prototype.hasOwnProperty.call(ROUTES, name) ? name : FALLBACK_ROUTE
  const pattern = segments(ROUTES[key])
  const path = pattern
    .map((seg) => {
      if (!seg.startsWith(':')) return seg
      const value = params[seg.slice(1)]
      return value === undefined || value === null ? '' : String(value)
    })
    .filter(Boolean)
    .join('/')
  return `#/${path}`
}

/** 当前地址对应的路由（读一次，不进响应式）。 */
export function currentRoute() {
  const hash = typeof window === 'undefined' ? '' : window.location.hash
  return parseHash(hash)
}

/**
 * 改地址（**只碰 `location.hash`，不碰任何界面状态**）。
 *
 * - 目标与当前相同时**不写**（否则浏览器会白记一条历史）；
 * - `replace: true` → 用 `replaceState` 顶掉当前历史（例：纠正一个坏地址，不希望用户按后退又回去）；
 * - ⚠️ 用 `location.hash` 而不是 `pushState`：hash 变化**不会发给后端**，
 *   所以后端那条 SPA 回退（`/api`、`/files` 之外 + `Accept: text/html`）永远命中 `index.html`——
 *   换句话说 **history 模式才需要动后端，hash 模式零风险**；
 * - ⚠️ **改完由我们自己广播一次 `hashchange`**，不指望浏览器替我们发：
 *   ① `replaceState` 本来就不发；② 各环境对"赋 hash 是否同步派发"并不一致（happy-dom 就不是），
 *   不自己发会出现"地址变了但界面没跟着变"的偶发。**多派发一次没有副作用**——
 *   接线的 `App.vue` 先比对"这是不是我刚写的那次"，再比对状态，重复通知会被挡掉。
 */
export function navigate(name, params = {}, { replace = false } = {}) {
  if (typeof window === 'undefined') return
  const target = buildHash(name, params)
  if (window.location.hash === target) return
  if (replace) {
    const url = `${window.location.pathname}${window.location.search}${target}`
    window.history.replaceState(null, '', url)
  } else {
    window.location.hash = target
  }
  window.dispatchEvent(new HashChangeEvent('hashchange'))
}

/**
 * 订阅地址变化（组件里用）。
 *
 * 返回取消订阅的函数——**组件卸载时必须调**，否则监听会越积越多。
 * `onChange` 收到的是解析后的 `{ name, params }`。
 */
export function onRouteChange(onChange) {
  if (typeof window === 'undefined') return () => {}
  const handler = () => onChange(currentRoute())
  window.addEventListener('hashchange', handler)
  return () => window.removeEventListener('hashchange', handler)
}
