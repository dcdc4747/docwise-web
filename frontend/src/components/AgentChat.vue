<template>
  <!-- Agent 对话：模型会自己调工具（查库 / 读段落），每一步都能看见 -->
  <div class="agent-pane">
    <!-- 顶部：模型 + 强度 + 设置 -->
    <div class="agent-bar">
      <span class="agent-model" :class="{ warn: !modelReady }">
        {{ modelLabel }}
      </span>
      <span class="agent-tier">{{ tierLabel }}</span>
      <button class="agent-gear" type="button" title="模型设置" @click="toggleConfig()">
        ⚙️
      </button>
    </div>

    <!-- 设置面板 -->
    <div v-if="configOpen" class="agent-config">
      <label>
        <span>厂商</span>
        <select :value="currentProvider" @change="pickProvider($event.target.value)">
          <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </label>
      <label>
        <span>接口地址</span>
        <input v-model="form.baseUrl" type="text" placeholder="https://api.deepseek.com/v1" />
      </label>
      <label>
        <span>模型名</span>
        <input v-model="form.model" type="text" placeholder="deepseek-chat" />
      </label>
      <label>
        <span>强度</span>
        <select v-model="form.tier">
          <option value="fast">快（便宜，适合多轮查库）</option>
          <option value="standard">标准</option>
          <option value="strong">强（贵，复杂推理）</option>
        </select>
      </label>
      <label>
        <span>API Key</span>
        <input
          v-model="form.apiKey"
          type="password"
          :placeholder="keyHint || '留空 = 不动已保存的密钥'"
        />
      </label>
      <div class="agent-config-ops">
        <span class="agent-note">{{ saveNote }}</span>
        <button class="btn primary sm" type="button" :disabled="saving" @click="save">
          保存
        </button>
      </div>
      <p class="agent-hint">
        密钥只写不读：保存后这里不会回显，页面上只显示末四位。
        <template v-if="!config || !config.server_default">
          没配就直接用不了——先填一个，或者让管理员在服务端配默认。
        </template>
      </p>
    </div>

    <!-- 对话流 -->
    <div class="agent-flow">
      <p v-if="!turns.length" class="agent-empty">
        问它一句试试：<b>「我库里有哪些讲手性的文献？」</b>
        ——它会自己去查，不是只看这一篇。
      </p>

      <div v-for="(turn, i) in turns" :key="i" class="agent-turn" :class="turn.role">
        <div v-if="turn.role === 'user'" class="agent-bubble user">{{ turn.text }}</div>
        <template v-else>
          <div v-if="turn.error" class="agent-bubble err">{{ turn.error }}</div>
          <template v-else>
            <div v-if="toolSteps(turn).length" class="agent-trace">
              <button class="agent-trace-head" type="button" @click="toggleTrace(i)">
                🛠 它查了 {{ toolCallCount(turn) }} 次 {{ traceOpen[i] ? '▾' : '▸' }}
              </button>
              <ul v-if="traceOpen[i]" class="agent-trace-list">
                <li v-for="(step, j) in toolSteps(turn)" :key="j" :class="{ bad: step.ok === false }">
                  <b>{{ step.kind === 'tool_call' ? '调' : step.ok === false ? '失败' : '返回' }}</b>
                  <code>{{ step.name }}</code>
                  <span class="agent-trace-detail">{{ detailOf(step) }}</span>
                </li>
              </ul>
            </div>
            <!-- 回答：`**加粗**` 转 <strong>，不用 v-html（模板里渲染文本更安全） -->
            <div class="agent-bubble answer">
              <template v-for="(seg, k) in segments(turn.text)" :key="k">
                <strong v-if="seg.bold">{{ seg.text }}</strong>
                <template v-else>{{ seg.text }}</template>
              </template>
            </div>
            <div v-if="turn.sources.length || turn.dropped.length" class="agent-src">
              <span v-if="turn.sources.length">出处 {{ turn.sources.length }} 处</span>
              <span v-if="turn.dropped.length" class="agent-src-drop">
                剔掉 {{ turn.dropped.length }} 个编造出处
              </span>
            </div>
            <div v-if="turn.usage && turn.usage.tool_calls" class="agent-usage">
              本轮调用 {{ turn.usage.tool_calls }} 次工具 · 模型请求 {{ turn.usage.requests }} 次
            </div>
          </template>
        </template>
      </div>

      <div v-if="busy" class="agent-bubble pending">正在查…</div>
      <div v-if="error" class="agent-bubble err">{{ error }}</div>
    </div>
  </div>
</template>

<script setup>
/**
 * Agent 面板（读懂侧）。**一个组件、任何页面都能挂**：
 *   <AgentChat :scope="{ task_id }" />
 * 页面只给上下文，不碰内部状态（状态在 `stores/useAgent`）。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'

import {
  agentBusy,
  agentConfig,
  agentConfigOpen,
  agentError,
  agentMessages,
  agentSaveNote,
  loadConfig,
  loadScenes,
  saveAgentConfig,
  sendAgent,
  toggleConfig,
  toolStepsOf,
} from '../stores/useAgent'

const props = defineProps({
  scope: { type: Object, default: () => ({}) },
})

const turns = computed(() => agentMessages.value)
const busy = agentBusy
const error = agentError
const config = agentConfig
const configOpen = agentConfigOpen
const saveNote = agentSaveNote
const saving = ref(false)
const traceOpen = reactive({})

const form = reactive({ baseUrl: '', model: '', tier: 'standard', apiKey: '' })

const providers = computed(() => (config.value && config.value.providers) || [])
const currentProvider = computed(() => {
  const base = form.baseUrl
  if (!base) return 'deepseek'
  const hit = providers.value.find((p) => p.base_url === base)
  return hit ? hit.id : 'local'
})
const keyHint = computed(() => (config.value && config.value.key_hint) || '')
const modelReady = computed(() => Boolean(config.value && (config.value.key_set || config.value.server_default)))
const modelLabel = computed(() => {
  if (!config.value) return '未配置模型'
  if (!modelReady.value) return '未配置模型'
  const model = config.value.model || form.model || '默认模型'
  return model
})
const tierLabel = computed(() => {
  const tier = (config.value && config.value.tier) || form.tier || 'standard'
  return { fast: '快', standard: '标准', strong: '强' }[tier] || tier
})

function syncForm() {
  const cfg = config.value || {}
  form.baseUrl = cfg.base_url || ''
  form.model = cfg.model || ''
  form.tier = cfg.tier || 'standard'
  form.apiKey = ''
}

watch(config, syncForm, { immediate: true })

function pickProvider(id) {
  const hit = providers.value.find((p) => p.id === id)
  if (!hit) return
  form.baseUrl = hit.base_url
  const tierModels = (config.value && config.value.tier_models) || {}
  const guess = (tierModels[id] || {})[form.tier]
  if (guess) form.model = guess
}

async function save() {
  saving.value = true
  try {
    await saveAgentConfig({ ...form })
  } finally {
    saving.value = false
  }
}

function toggleTrace(i) {
  traceOpen[i] = !traceOpen[i]
}

function toolSteps(turn) {
  return toolStepsOf(turn)
}

function toolCallCount(turn) {
  return toolStepsOf(turn).filter((step) => step.kind === 'tool_call').length
}

function detailOf(step) {
  const raw = step.kind === 'tool_call' ? step.args : step.excerpt
  const text = typeof raw === 'string' ? raw : JSON.stringify(raw || {})
  return text.length > 80 ? `${text.slice(0, 80)}…` : text
}

/** `**加粗**` → 片段数组（不引第三方 markdown，也不 v-html）。 */
function segments(text) {
  const out = []
  const body = String(text || '')
  body.split('**').forEach((chunk, idx) => {
    if (!chunk) return
    out.push({ text: chunk, bold: idx % 2 === 1 })
  })
  return out
}

onMounted(async () => {
  await Promise.all([loadScenes(), loadConfig()])
})

defineExpose({ send: (q) => sendAgent(q, props.scope) })
</script>
