/**
 * 个人偏好（F 卡，契约 N40/N41）。
 *
 * ## 为什么要有这个模块
 *
 * 偏好以前只活在本机 `localStorage.docwise_prefs`：**换台电脑就全没了**
 * （`useReader` 里那句注释写得很清楚"后端没有偏好接口，契约的 N 清单里也没有这一项"）。
 * 这张卡把服务端补成**权威**。
 *
 * ## 三个口径（都有用例钉住）
 *
 * 1. ⭐ **服务端权威、`localStorage` 降级成缓存**：
 *    阅读页要**同步**读偏好（`preferredDocMode()` 打开任务那一刻就要用，等不了网络往返），
 *    所以缓存必须留；但**以服务端为准**——服务端有就以它覆盖本地。
 * 2. ⭐ **一次性迁移**：服务端**空**、本机**有**数据（老用户）→ 把本机那份推上去，
 *    否则老用户第一次登录就会"偏好被清空"。
 * 3. ⭐ **网络挂了不挡人**：写入先落缓存再推服务端；推失败只**如实报一句**，
 *    界面照旧用本地那份（`prefsError` 里会说"换设备不会带上"）。
 *
 * ⚠️ 只认**已知的四个键**（`defaultView / tier / readingSize / reducedMotion`）：
 * 后端允许任意标量键，但前端只写这四个；读的时候把没见过的键丢掉，
 * 免得一份脏数据把界面顶到未定义分支上。
 */

import { ref } from 'vue'

import { apiJson } from '../auth'

export const PREFS_KEY = 'docwise_prefs'

/** 已知偏好的默认值（也是"什么都没有"时的样子）。 */
export const DEFAULT_PREFS = {
  defaultView: 'blocks', // blocks / mono / dual（v1 的 pdf 档在 v2 阅读区没有对应模式）
  tier: 'medium', // fast / medium（精档已从界面撤下）
  readingSize: 'normal', // small / normal / large
  reducedMotion: false,
}

const VIEWS = ['blocks', 'mono', 'dual']
const TIERS = ['fast', 'medium']
const SIZES = ['small', 'normal', 'large']

export const prefs = ref({ ...DEFAULT_PREFS })
/** 取/存失败时给人看的那句话（空串 = 一切正常）。 */
export const prefsError = ref('')
/** 是否已经跟服务端对过一次（用例与界面都用它判断"能不能信这份"）。 */
export const prefsLoaded = ref(false)

/**
 * 把任意来源的一份偏好收成"已知键 + 合法值"。
 *
 * ⚠️ 值不认识就**回落默认**，不猜（猜错了会悄悄改掉用户的读法）。
 */
export function sanitizePrefs(raw) {
  const out = { ...DEFAULT_PREFS }
  if (!raw || typeof raw !== 'object') return out
  if (VIEWS.includes(raw.defaultView)) out.defaultView = raw.defaultView
  if (TIERS.includes(raw.tier)) out.tier = raw.tier
  if (SIZES.includes(raw.readingSize)) out.readingSize = raw.readingSize
  if (typeof raw.reducedMotion === 'boolean') out.reducedMotion = raw.reducedMotion
  return out
}

/** 读本机缓存（坏数据/读不到一律回落默认——它是缓存，不是权威）。 */
export function readLocalPrefs() {
  try {
    const raw = JSON.parse(localStorage.getItem(PREFS_KEY) || '{}')
    return sanitizePrefs(raw)
  } catch {
    return { ...DEFAULT_PREFS }
  }
}

/**
 * 本机**是否真的存过**偏好（迁移判据）。
 *
 * ⚠️ 不能用 `readLocalPrefs()` 判断：它对空缓存也会 sanitize 出一整套默认值，
 * 于是"本机有数据"永远成立 → 每次登录都拿默认值往服务端推一次（把别人的设置盖掉）。
 * 这条是**用例抓出来的**（"服务端空 + 本机也空 → 不该推"）。
 */
export function hasLocalPrefs() {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    if (!raw) return false
    return Object.keys(JSON.parse(raw) || {}).length > 0
  } catch {
    return false
  }
}

/** 写本机缓存；存不下就算了（偏好不许把页面搞挂）。 */
export function writeLocalPrefs(value) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(sanitizePrefs(value)))
  } catch {
    /* ignore */
  }
}

function _messageOf(error, fallback) {
  const text = error && error.message ? String(error.message) : ''
  return text || fallback
}

async function _push(value) {
  // ⚠️ **`Content-Type` 必须自己带上**：`apiJson` 只补 `Authorization`，不补这个
  // （见 `auth.js` 的 `authHeaders`）。少了它 FastAPI 会把 body 当成纯文本，
  // 回 422「Input should be a valid dictionary」——**实拍踩到过**，单测桩不看请求头所以没抓到。
  await apiJson('/api/me/preferences', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prefs: sanitizePrefs(value) }),
  })
}

/**
 * 跟服务端对一次：服务端有 → 覆盖本地；服务端空且本地有 → 把本地推上去（一次性迁移）。
 *
 * 失败不抛：`prefsError` 里留一句话，界面照旧用本地缓存。
 */
export async function loadPrefs() {
  const local = readLocalPrefs()
  prefs.value = { ...local }

  try {
    const data = await apiJson('/api/me/preferences')
    const server = data && typeof data.prefs === 'object' && data.prefs ? data.prefs : {}
    const serverKeys = Object.keys(server)
    if (serverKeys.length === 0 && hasLocalPrefs()) {
      // ⭐ 服务端还没有、本机真存过 → 老用户迁移（推上去，别把人家的设置"升级丢"）
      await _push(local)
      prefs.value = { ...local }
    } else {
      prefs.value = sanitizePrefs(server)
      // ⚠️ **只在服务端真给了东西时才写缓存**：服务端空时也写的话，
      // 下次加载就会看到"本机有数据"、把一份**默认值**当成用户设置迁移上去
      // （= 自己给自己播种，服务端永远有一行不是用户设置的偏好）。用例钉住了这一条。
      if (serverKeys.length > 0) writeLocalPrefs(prefs.value)
    }
    prefsError.value = ''
  } catch (error) {
    prefsError.value = `偏好没从服务端取到（${_messageOf(
      error,
      '网络或服务异常',
    )}）—— 先按本机这份用，改动只留在本机`
  } finally {
    prefsLoaded.value = true
  }
  return prefs.value
}

/**
 * 存一份偏好：**先落缓存再推服务端**（网络挂了界面也一致）。
 *
 * 不抛异常——调用方（`MeView` 的 watcher）不该为了偏好去 try/catch；
 * 成败看 `prefsError`（空串 = 存上了）。
 */
export async function savePrefs(patch) {
  const next = sanitizePrefs({ ...prefs.value, ...(patch || {}) })
  prefs.value = next
  writeLocalPrefs(next)
  try {
    await _push(next)
    prefsError.value = ''
    return { ok: true, prefs: next }
  } catch (error) {
    prefsError.value = `偏好没存到服务端（${_messageOf(
      error,
      '网络或服务异常',
    )}）—— 这台机器上仍然生效，但换设备不会带上`
    return { ok: false, prefs: next }
  }
}

/** 退出登录 / 换账号时复位（否则下一个人会看到上一个人的偏好）。 */
export function resetPrefs() {
  prefs.value = { ...DEFAULT_PREFS }
  prefsError.value = ''
  prefsLoaded.value = false
}
