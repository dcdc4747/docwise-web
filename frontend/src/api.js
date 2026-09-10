// API base 解析（M3 PWA）：手机真机访问时前端与后端往往不在同一个 origin，
// 相对路径 /api 会指向"手机自己"，必须用绝对 base 指向电脑上的后端。
//
// 优先级：URL 参数 ?apiBase= > localStorage（docwise_api_base）> 构建时 VITE_API_BASE > 空（同源相对路径）。
// 例：手机浏览器打开 http://192.168.1.5:4173/?apiBase=http://192.168.1.5:8000
//     或构建时设置 VITE_API_BASE=http://192.168.1.5:8000 bun run build
//
// 注意：base **只接受 http:// 或 https:// 开头**。否则（例如把说明文字一起粘进
// 网址、参数被换成一段中文）拼出来的地址不合法，浏览器会直接报
// "Failed to parse URL"，而且那个脏值会被记进 localStorage 一直生效——所以这里
// 一律校验，脏值当场丢弃并清掉本地记录。

const STORAGE_KEY = 'docwise_api_base'

function normalize(base) {
  if (!base) return ''
  const trimmed = base.trim().replace(/\/+$/, '')
  return /^https?:\/\//i.test(trimmed) ? trimmed : ''
}

function resolveApiBase() {
  const params = new URLSearchParams(window.location.search)
  if (params.has('apiBase')) {
    const value = normalize(params.get('apiBase'))
    if (value) localStorage.setItem(STORAGE_KEY, value)
    else localStorage.removeItem(STORAGE_KEY)
  }

  const stored = normalize(localStorage.getItem(STORAGE_KEY))
  if (!stored && localStorage.getItem(STORAGE_KEY)) {
    // 清掉历史上的脏值（否则会一直拼出非法地址）
    localStorage.removeItem(STORAGE_KEY)
  }
  return stored || normalize(import.meta.env.VITE_API_BASE)
}

export const API_BASE = resolveApiBase()

/** 把后端路径（/api/...、/files/...）拼上绝对 base。 */
export function apiUrl(path) {
  return `${API_BASE}${path}`
}
