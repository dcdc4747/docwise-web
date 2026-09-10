// 前端鉴权：令牌存取 + 统一请求封装 + 临时票据（给带不了请求头的三种请求用）。
//
// 为什么需要票据：进度推送（EventSource）、PDF 预览（iframe）、文件下载（<a href>）
// 这三种请求是浏览器自己发起的，**没法带 Authorization 请求头**，所以先换一张
// 60 秒有效、绑定"用户+任务+用途"的票据，拼在 URL 上。

import { apiUrl } from './api'

const TOKEN_KEY = 'docwise_token'

let unauthorizedHandler = null

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token, remember = true) {
  clearToken()
  const store = remember ? localStorage : sessionStorage
  store.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
  sessionStorage.removeItem(TOKEN_KEY)
}

/** 登录失效时的统一回调（由 App.vue 注册：回登录页并提示）。 */
export function setUnauthorizedHandler(fn) {
  unauthorizedHandler = fn
}

function authHeaders() {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function errorMessage(status, body) {
  const detail = body && body.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) {
    return detail.map((item) => item.msg || '参数不合法').join('；')
  }
  return `请求失败（HTTP ${status}）`
}

/** 带令牌的 fetch；遇到 401 会清令牌并触发统一回调。 */
export async function authFetch(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    ...options,
    headers: { ...(options.headers || {}), ...authHeaders() },
  })
  if (response.status === 401) {
    clearToken()
    if (unauthorizedHandler) unauthorizedHandler()
  }
  return response
}

/** 带令牌 + JSON 解析 + 错误信息归一化。204 返回 null。 */
export async function apiJson(path, options = {}) {
  const response = await authFetch(path, options)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(errorMessage(response.status, body))
  }
  if (response.status === 204) return null
  return response.json()
}

// ---------------------------------------------------------------- 账号相关
export async function login(username, password) {
  return apiJson('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
}

export async function register(username, password) {
  return apiJson('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
}

export async function demoLogin() {
  return apiJson('/api/auth/demo-login', { method: 'POST' })
}

export async function fetchMe() {
  return apiJson('/api/auth/me')
}

export async function logout() {
  try {
    await apiJson('/api/auth/logout', { method: 'POST' })
  } finally {
    clearToken()
  }
}

// ---------------------------------------------------------------- 票据
/** 换一张票据（scope: 'files' 预览/下载，'events' 进度推送）。 */
export async function ticketFor(taskId, scope) {
  const data = await apiJson('/api/auth/ticket', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId, scope }),
  })
  return data.ticket
}

/** 拼出带票据的 URL（用于 EventSource / iframe / 下载）。 */
export async function urlWithTicket(path, taskId, scope) {
  const ticket = await ticketFor(taskId, scope)
  const joiner = path.includes('?') ? '&' : '?'
  return apiUrl(`${path}${joiner}ticket=${encodeURIComponent(ticket)}`)
}
