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

/**
 * 流式发问（SSE）。与 `sendAgent` 的差别**只在传输**：
 * 事件类型与最终结构完全一致，所以界面不用分两套。
 *
 * ⚠️ 用 `fetch` + `ReadableStream` 而不是 `EventSource`：
 * EventSource 只能 GET、也带不了 `Authorization` 头。
 */
export async function sendAgentStream(question, scope = {}) {
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
    const res = await authFetch('/api/agent/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ scene: state.sceneId, question: text, scope }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      turn.error = body.detail || `没答出来（HTTP ${res.status}）`
      return
    }
    if (!res.body) {
      turn.error = '这个浏览器不支持流式读取'
      return
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // SSE：事件之间用空行分隔
      let cut = buffer.indexOf('\n\n')
      while (cut !== -1) {
        const chunk = buffer.slice(0, cut)
        buffer = buffer.slice(cut + 2)
        cut = buffer.indexOf('\n\n')
        const line = chunk.split('\n').find((l) => l.startsWith('data: '))
        if (!line) continue
        let event = null
        try {
          event = JSON.parse(line.slice(6))
        } catch {
          continue
        }
        applyEvent(turn, event)
      }
    }
  } catch (exc) {
    turn.error = `请求失败：${exc && exc.message ? exc.message : exc}`
  } finally {
    state.busy = false
  }
}

/** 把一帧事件并到这一轮回答里（后端形状见 `app/agent/runtime.stream_scene`）。 */
function applyEvent(turn, event) {
  if (event.type === 'tool_call') {
    turn.steps.push({ kind: 'tool_call', name: event.name, args: event.args })
  } else if (event.type === 'tool_result') {
    turn.steps.push({
      kind: 'tool_result',
      name: event.name,
      ok: event.ok !== false,
      excerpt: event.excerpt || '',
    })
  } else if (event.type === 'delta') {
    turn.text += event.text || ''
  } else if (event.type === 'final') {
    // 以 final 为准（模型可能边流边改口，最终答案才算数）
    if (event.answer) turn.text = event.answer
    turn.sources = event.sources || []
    turn.dropped = event.dropped_sources || []
    turn.usage = event.usage || null
    if (event.steps && event.steps.length) turn.steps = event.steps
  } else if (event.type === 'error') {
    turn.error = event.message || '模型调用失败'
  }
}
