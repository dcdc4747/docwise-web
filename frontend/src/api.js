// API base 解析（M3 PWA）：手机真机访问时前端与后端往往不在同一个 origin，
// 相对路径 /api 会指向"手机自己"，必须用绝对 base 指向电脑上的后端。
//
// 优先级：URL 参数 ?apiBase= > localStorage（docwise_api_base）> 构建时 VITE_API_BASE > 空（同源相对路径）。
// 例：手机浏览器打开 http://192.168.1.5:4173/?apiBase=http://192.168.1.5:8000
//     或构建时设置 VITE_API_BASE=http://192.168.1.5:8000 bun run build

const STORAGE_KEY = 'docwise_api_base'

function normalize(base) {
  if (!base) return ''
  return base.trim().replace(/\/+$/, '')
}

function resolveApiBase() {
  const query = new URLSearchParams(window.location.search).get('apiBase')
  if (query !== null) {
    if (query) localStorage.setItem(STORAGE_KEY, query)
    else localStorage.removeItem(STORAGE_KEY)
  }
  const stored = localStorage.getItem(STORAGE_KEY)
  const env = import.meta.env.VITE_API_BASE
  return normalize(stored || env || '')
}

export const API_BASE = resolveApiBase()

/** 把后端路径（/api/...、/files/...）拼上绝对 base。 */
export function apiUrl(path) {
  return `${API_BASE}${path}`
}
