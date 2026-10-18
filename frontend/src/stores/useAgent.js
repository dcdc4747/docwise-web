/**
 * Agent 对话状态（模型可自己调工具的那种问答）。
 *
 * ⚠️ **状态定义在模块顶层（单例）**，不在函数里：
 * 这和 `useAsk` 是同一个理由——`ReadView` 每次切屏都会重新挂载，
 * 定义在函数里的话一换页整条对话就没了。
 *
 * 与旧问答（`useAsk`）的关系：**两条独立线程**。旧的是"一次性读这一篇"，
 * 新的是"agent 自己去查库"；界面上给用户一个开关，不互相覆盖。
 */

import { computed, reactive } from 'vue'
import { authFetch } from '../auth'

const state = reactive({
  sceneId: 'read_ask',
  scenes: [],
  config: null,
  // 每条：{ role: 'user' | 'assistant', text, steps, sources, dropped, usage, error }
  messages: [],
  busy: false,
  error: '',
  configOpen: false,
  saving: false,
  saveNote: '',
})

export const agentMessages = computed(() => state.messages)
export const agentBusy = computed(() => state.busy)
export const agentError = computed(() => state.error)
export const agentConfig = computed(() => state.config)
export const agentConfigOpen = computed(() => state.configOpen)
export const agentSaveNote = computed(() => state.saveNote)
export const agentScenes = computed(() => state.scenes)

/** 场景列表（自描述：前端据此渲染，后端加场景不用改前端）。 */
export async function loadScenes() {
  try {
    const res = await authFetch('/api/agent/scenes')
    if (!res.ok) return
    const body = await res.json()
    state.scenes = body.items || []
  } catch {
    /* 场景列表拿不到不阻塞对话 */
  }
}

export async function loadConfig() {
  try {
    const res = await authFetch('/api/agent/config')
    if (!res.ok) return
    state.config = await res.json()
  } catch {
    /* 同上 */
  }
}

export function setScene(sceneId) {
  state.sceneId = sceneId
}

export function toggleConfig(open) {
  state.configOpen = open === undefined ? !state.configOpen : Boolean(open)
  state.saveNote = ''
}

/** 保存配置。`apiKey` 留空 = 不动原密钥（后端也是这个口径）。 */
export async function saveAgentConfig({ baseUrl, model, tier, apiKey }) {
  state.saving = true
  state.saveNote = ''
  try {
    const payload = { base_url: baseUrl, model, tier }
    if (apiKey) payload.api_key = apiKey
    const res = await authFetch('/api/agent/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) {
      state.saveNote = body.detail || `保存失败（HTTP ${res.status}）`
      return false
    }
    state.config = body
    state.saveNote = '已保存'
    return true
  } catch (exc) {
    state.saveNote = String(exc && exc.message ? exc.message : exc)
    return false
  } finally {
    state.saving = false
  }
}

export function resetAgentThread() {
  state.messages = []
  state.error = ''
}

/**
 * 发一个问题。`scope` 是页面上下文（如 `{ task_id }`），后端只收白名单字段。
 */
export async function sendAgent(question, scope = {}) {
  const text = String(question || '').trim()
  if (!text || state.busy) return
  state.error = ''
  state.messages.push({ role: 'user', text })
  const turn = reactive({
    role: 'assistant',
    text: '',
    steps: [],
    sources: [],
    dropped: [],
    usage: null,
    error: '',
  })
  state.messages.push(turn)
  state.busy = true
  try {
    const res = await authFetch('/api/agent/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scene: state.sceneId, question: text, scope }),
    })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) {
      turn.error = body.detail || `没答出来（HTTP ${res.status}）`
      return
    }
    turn.text = body.answer || ''
    turn.steps = body.steps || []
    turn.sources = body.sources || []
    turn.dropped = body.dropped_sources || []
    turn.usage = body.usage || null
  } catch (exc) {
    turn.error = `请求失败：${exc && exc.message ? exc.message : exc}`
  } finally {
    state.busy = false
  }
}

/** 轨迹里"真正查了什么"：只留工具调用/返回，收尾那条（final_result）不算查。 */
export function toolStepsOf(turn) {
  return (turn.steps || []).filter((step) => {
    const name = String(step.name || '')
    return !name.includes('final_result')
  })
}
