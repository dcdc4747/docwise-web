/**
 * 块曝光埋点（N34 · 形态 §5 假设 1 的**分母**）—— 2026-10-16
 *
 * 为什么要有它：形态 §5 把"用户真的会去改译文"写成**待验证假设**，判据是
 * **修改率 ＝ 被改块数 / 被曝光块数**，并写死 `观测期 ≥14 天 且 曝光块数 ≥500`
 * 之前一律"**继续观测**"。而在这之前**前端一处都没上报过曝光** →
 * 那个分母**永远是 0**，判据永远算不出来（`block_exposures` 表一直是空的）。
 *
 * 四条口径（照契约「§2.9 埋点」与数据模型「§2.10」，**别自己发明**）：
 * ① **一次会话一个 `session_id`**（打开阅读页生成一个）；
 * ② ⭐ **请求体是单个对象**（N34：`{task_id, block_id, session_id, entered_at?, left_at?}`）
 *    —— **不是批量数组**，所以**一块一次请求**；
 * ③ ⭐ **幂等**：唯一键 `(user_id, task_id, block_id, session_id)`——同一会话同一块只记一行，
 *    重复上报**不长新行**，只把 `left_at` 往后推（"这块看了更久"）；
 * ④ ⭐ **两个时间戳都要记**（进入 / 离开）——把"曝光定义之争"
 *    （全部曝光块 vs 停留 ≥3 秒）变成一次数据对照，而不是先吵一架。
 *
 * ⚠️ **这里只上报，不判"建 / 砍"**；**也不写台账**——台账"一次会话只写一条"是
 * **服务端**收到曝光时写的（见 `backend/app/routers/block_events.py`）。
 *
 * 设计取舍（都是为了"别把后端打爆"与"别拖慢阅读"）：
 * - **一个块一个会话最多两次请求**（进入一次、离开一次），不是滚一次报一次；
 * - **并发闸**：最多 `MAX_INFLIGHT` 个请求在飞，其余排队——183 块同时进视口时
 *   不能一次打 183 个请求；
 * - **失败就丢，不重试**（重试风暴比丢一条曝光更糟），**绝不打断阅读**；
 * - **离开走 `sendBeacon`**：关页/切页时普通 fetch 会被取消，那是会**静默丢数据**的；
 *   没有 Beacon 才退回 `keepalive: true` 的 fetch。
 */
import { apiUrl } from './api'
import { getToken } from './auth'

/** 同时在飞的请求上限（183 块同时进视口时，不能一次打 183 个）。 */
export const MAX_INFLIGHT = 6

/**
 * 离开页面时最多补发多少个"离开"（**不是越多越好**）。
 *
 * ⚠️ 关页/切页那一瞬间浏览器**不会等**：一口气发 183 个 beacon，后面绝大多数会被丢掉。
 * 所以这里给个上限，优先补**最近还在看的那批**（`reported` 的插入顺序就是进入顺序，
 * 取末尾 `BEACON_MAX` 个最接近"最后停在哪"）。
 * 代价如实说：**靠后的那些块的 `left_at` 可能只停在"进入时刻"**——
 * 也就是说"停留 ≥3 秒"那种更严的分母会**偏小**，分析时要记得这一点。
 * 而"全部曝光块"那个分母（形态 §5 明确要求两种各算一遍）**不受影响**：
 * 它只靠"进入"那一次上报，那个是进入时就发出去的。
 */
export const BEACON_MAX = 40

/** 一次阅读会话的 id（打开阅读页生成一个；同一会话内所有曝光共用它）。 */
export function newSessionId() {
  const rand =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
  return `s_${rand}`.slice(0, 64)
}

/**
 * 从给定节点里挑出**真的在视口内**的块编号（**纯函数**，好测）。
 *
 * 判据取"块盒与视口有交集"；**按文档顺序去重**。三条原因写在这里，免得以后被"顺手优化掉"：
 * - **窄屏时桌面那条渲染路径仍在 DOM 里**（`.page .cols p`），反之亦然，
 *   所以只按**布局盒**判定，不靠选择器猜当前是哪条路径；
 * - **零尺寸的盒不算**（没渲染 / `display:none` 的 `clientHeight` 为 0，`getBoundingClientRect` 仍会给 0 宽高）；
 * - 同一块理论上只命中一个元素，真命中两个也只算一次。
 *
 * `margin` 是**放宽**（把"几乎就要进来了"的也算上），不是收紧：
 * 视口按 `[-margin, viewportHeight + margin]` 算。
 */
export function visibleBlockIds(root, { viewportHeight = 0, margin = 0 } = {}) {
  if (!root || typeof root.querySelectorAll !== 'function') return []
  const ids = []
  const seen = new Set()
  const top = -margin
  const bottom = viewportHeight + margin
  for (const el of root.querySelectorAll('[data-block-id]')) {
    const id = el.getAttribute('data-block-id')
    if (!id || seen.has(id)) continue
    if (!el.clientHeight) continue // 零尺寸 = 没真渲染
    const rect = el.getBoundingClientRect()
    if (rect.bottom > top && rect.top < bottom) {
      seen.add(id)
      ids.push(id)
    }
  }
  return ids
}

/**
 * 曝光上报器。
 *
 * @param {{taskId: number, sessionId?: string, now?: () => Date, viewportHeight?: number}} options
 *        `now` 注入是为了测试定得住时间；`viewportHeight` 供无头环境/测试用。
 */
export function createExposureReporter({
  taskId,
  sessionId = newSessionId(),
  now = () => new Date(),
  viewportHeight = 0,
} = {}) {
  /** 已经报过"进入"的块（本会话内幂等：同一块不再入队，避免反复滚来滚去刷请求）。 */
  const reported = new Set()
  const queue = []
  let inflight = 0
  let disposed = false

  const stamp = () => now().toISOString()

  async function postOne(item) {
    const headers = { 'Content-Type': 'application/json' }
    const token = typeof getToken === 'function' ? getToken() : null
    if (token) headers.Authorization = `Bearer ${token}`
    const body = JSON.stringify({
      task_id: taskId,
      block_id: item.block_id,
      session_id: sessionId,
      entered_at: item.entered_at ?? null,
      left_at: item.left_at ?? null,
    })
    const res = await fetch(apiUrl('/api/block-exposures'), { method: 'POST', headers, body })
    if (!res.ok) throw new Error(String(res.status))
  }

  function pump() {
    while (!disposed && inflight < MAX_INFLIGHT && queue.length) {
      const item = queue.shift()
      inflight += 1
      postOne(item)
        .catch(() => {
          /* 旁支数据：失败就丢，不重试、不打断阅读 */
        })
        .finally(() => {
          inflight -= 1
          pump()
        })
    }
  }

  return {
    taskId,
    sessionId,

    /** 块进入视口（本会话每块只报一次）。 */
    enter(blockIds) {
      if (disposed || !Array.isArray(blockIds)) return
      const at = stamp()
      for (const id of blockIds) {
        if (!id || reported.has(id)) continue
        reported.add(id)
        queue.push({ block_id: id, entered_at: at, left_at: at })
      }
      pump()
    },

    /** 块离开视口：把 `left_at` 往后推（这是"看了多久"的来源）。 */
    leave(blockIds) {
      if (disposed || !Array.isArray(blockIds)) return
      const at = stamp()
      for (const id of blockIds) {
        if (!id || !reported.has(id)) continue
        queue.push({ block_id: id, entered_at: null, left_at: at })
      }
      pump()
    },

    /** 扫描一次当前视口内的块（调用方在滚动 / 尺寸变化后调它）。 */
    scan(root) {
      if (disposed) return
      const height = viewportHeight || (typeof window !== 'undefined' ? window.innerHeight : 0)
      this.enter(visibleBlockIds(root, { viewportHeight: height }))
    },

    /** 页面要走（hidden / beforeunload）：Beacon 把最后一批送出去。 */
    beacon() {
      if (disposed) return
      const at = stamp()
      const items = queue.splice(0, queue.length)
      // ⚠️ 只补**最近**那批（见 BEACON_MAX 的说明）：一口气发几百个只会被浏览器丢掉。
      const recent = [...reported].slice(-BEACON_MAX)
      for (const id of recent) items.push({ block_id: id, entered_at: null, left_at: at })
      if (!items.length) return
      const url = apiUrl('/api/block-exposures')
      let sent = 0
      for (const item of items) {
        if (sent >= BEACON_MAX) break
        const payload = JSON.stringify({
          task_id: taskId,
          block_id: item.block_id,
          session_id: sessionId,
          entered_at: item.entered_at ?? null,
          left_at: item.left_at ?? null,
        })
        const ok =
          typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function'
            ? navigator.sendBeacon(url, new Blob([payload], { type: 'application/json' }))
            : false
        if (ok) {
          sent += 1
          continue
        }
        // 没有 Beacon（或它拒收）：退回 keepalive fetch
        try {
          const headers = { 'Content-Type': 'application/json' }
          const token = typeof getToken === 'function' ? getToken() : null
          if (token) headers.Authorization = `Bearer ${token}`
          fetch(url, { method: 'POST', headers, body: payload, keepalive: true }).catch(() => {})
          sent += 1
        } catch {
          /* ignore */
        }
      }
    },

    /** 卸载：停掉一切，之后不再上报。 */
    dispose() {
      disposed = true
      queue.length = 0
    },

    /** 测试用：看一眼内部状态，不参与产品逻辑。 */
    _debug() {
      return { reported: [...reported], queued: queue.length, inflight, disposed }
    },
  }
}

export default { newSessionId, visibleBlockIds, createExposureReporter, MAX_INFLIGHT }
