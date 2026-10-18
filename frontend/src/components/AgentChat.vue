<template>
  <!-- Agent 对话：模型会自己调工具（查库 / 读段落），每一步都能看见 -->
  <div class="agent-pane">
    <!-- 顶部：模型 + 强度 + 设置 -->

    <!-- ⭐ 对话 / 轨迹：轨迹单独一页，消息流才干净（长对话尤其明显） -->
    <div v-if="turns.length" class="agent-views">
      <button
        type="button"
        :class="{ on: viewMode === 'chat' }"
        @click="viewMode = 'chat'"
      >
        对话
      </button>
      <button
        type="button"
        :class="{ on: viewMode === 'trace' }"
        @click="viewMode = 'trace'"
      >
        轨迹 · {{ totalSteps }}
      </button>
    </div>

    <!-- 轨迹页：把这一串对话里所有工具调用按顺序列出来 -->
    <div v-if="viewMode === 'trace'" class="agent-trace-view">
      <div v-for="(item, idx) in allSteps" :key="idx" class="agent-trace-item">
        <div class="agent-trace-q">Q{{ item.turnIndex }} · {{ item.question }}</div>
        <ul class="agent-trace-list">
          <li v-for="(step, j) in item.steps" :key="j" :class="{ bad: step.ok === false }">
            <b>{{ step.kind === 'tool_call' ? '调' : step.ok === false ? '失败' : '返回' }}</b>
            <code>{{ step.name }}</code>
            <span class="agent-trace-detail">{{ detailOf(step) }}</span>
          </li>
        </ul>
      </div>
      <p v-if="!allSteps.length" class="agent-empty">这轮还没调过工具。</p>
    </div>

    <!-- 对话流 -->
    <div v-if="viewMode === 'chat'" class="agent-flow">
      <div v-if="!turns.length" class="agent-empty">
        <p>问它一句试试——它会自己去查库，不是只看这一篇：</p>
        <div class="agent-quick">
          <button
            v-for="q in QUICK_PROMPTS"
            :key="q"
            type="button"
            :disabled="busy"
            @click="$emit('quick', q)"
          >
            {{ q }}
          </button>
        </div>
      </div>

      <div v-for="(turn, i) in turns" :key="i" class="agent-turn" :class="turn.role">
        <div v-if="turn.role === 'user'" class="agent-bubble user">{{ turn.text }}</div>
        <template v-else>
          <div v-if="turn.error" class="agent-bubble err">{{ turn.error }}</div>
          <template v-else>
            <!-- 生成中：过程（思考 + 工具调用）**实时可见** -->
            <div
              v-if="!turn.done && (toolSteps(turn).length || turn.thinking)"
              class="agent-process"
            >
              <div v-if="turn.thinking" class="agent-thinking">{{ thinkingTail(turn) }}</div>
              <ul v-if="toolSteps(turn).length" class="agent-trace-list">
                <li v-for="(step, j) in toolSteps(turn)" :key="j" :class="{ bad: step.ok === false }">
                  <b>{{ step.kind === 'tool_call' ? '调' : step.ok === false ? '失败' : '返回' }}</b>
                  <code>{{ step.name }}</code>
                  <span class="agent-trace-detail">{{ detailOf(step) }}</span>
                </li>
              </ul>
            </div>

            <!-- ⭐ 合规：模型生成的内容要标注（标注跟着内容走，不为省事丢掉） -->
            <div class="ai-badge-row"><AiBadge kind="answer" /></div>
            <!-- 回答：`**加粗**` 转 <strong>，不用 v-html（模板里渲染文本更安全） -->
            <div class="agent-bubble answer">
              <template v-for="(seg, k) in segments(turn.text)" :key="k">
                <strong v-if="seg.bold">{{ seg.text }}</strong>
                <template v-else>{{ seg.text }}</template>
              </template>
            </div>
            <!-- 收尾后：过程收起成一行（默认不看，需要才展开） -->
            <button
              v-if="turn.done && (toolSteps(turn).length || turn.thinking)"
              class="agent-trace-head"
              type="button"
              @click="toggleTrace(i)"
            >
              过程 {{ toolSteps(turn).length }} 步 · {{ traceOpen[i] ? '收起 ▴' : '展开 ▾' }}
            </button>
            <div v-if="turn.done && traceOpen[i]" class="agent-process">
              <div v-if="turn.thinking" class="agent-thinking">{{ turn.thinking }}</div>
              <ul class="agent-trace-list">
                <li v-for="(step, j) in toolSteps(turn)" :key="j" :class="{ bad: step.ok === false }">
                  <b>{{ step.kind === 'tool_call' ? '调' : step.ok === false ? '失败' : '返回' }}</b>
                  <code>{{ step.name }}</code>
                  <span class="agent-trace-detail">{{ detailOf(step) }}</span>
                </li>
              </ul>
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

      <div v-if="busy" class="agent-bubble pending">{{ pendingText }}</div>
      <div v-if="error" class="agent-bubble err">{{ error }}</div>
    </div>

    <!-- ⭐ 输入框那一行：模型选择在这里（和 DS Harness 一样，不占消息区顶部） -->
    <div class="agent-composer">
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
          <span>模型</span>
          <select :value="form.model" @change="pickModel($event.target.value)">
            <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
            <option value="__custom">自定义…</option>
          </select>
        </label>
        <label v-if="customModel">
          <span>手填模型名</span>
          <input v-model="form.model" type="text" placeholder="例如 deepseek-reasoner" />
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

      <textarea
        ref="inputEl"
        v-model="input"
        rows="1"
        placeholder="问它点什么…"
        :disabled="busy"
        @input="autoGrow"
        @keydown.enter.exact.prevent="submit"
      />
      <div class="agent-composer-foot">
        <button
          class="agent-model-btn"
          :class="{ warn: !modelReady }"
          type="button"
          :title="modelReady ? '点这里换模型 / 厂商 / 强度' : '还没配模型，点这里配'"
          @click="toggleConfig()"
        >
          {{ modelReady ? `${modelLabel} · ${tierLabel}` : '未配置模型' }}
          <span class="agent-model-hint">▾</span>
        </button>
        <span class="agent-kbd-hint">Enter 发送 · Shift+Enter 换行</span>
        <button
          class="agent-send"
          :class="{ ready: input.trim() && !busy }"
          type="button"
          :disabled="busy || !input.trim()"
          :title="busy ? '正在回答…' : '发送'"
          @click="submit"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 19V5M6 11l6-6 6 6" fill="none" stroke="currentColor"
                  stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * Agent 面板（读懂侧）。**一个组件、任何页面都能挂**：
 *   <AgentChat :scope="{ task_id }" />
 * 页面只给上下文，不碰内部状态（状态在 `stores/useAgent`）。
 */
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'

import AiBadge from './AiBadge.vue'

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
  sendAgentStream,
  toggleConfig,
  toolStepsOf,
} from '../stores/useAgent'

const props = defineProps({
  scope: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['quick'])

// 空态那三条：覆盖"跨库找文献 / 读这篇 / 换说法"
const QUICK_PROMPTS = [
  '我库里有哪些讲手性的文献？',
  '这篇的结论有多可靠？',
  '把这篇的要点列出三条',
]

const turns = computed(() => agentMessages.value)
const busy = agentBusy
const error = agentError
const config = agentConfig
const configOpen = agentConfigOpen
const saveNote = agentSaveNote
const saving = ref(false)
const traceOpen = reactive({})

const form = reactive({ baseUrl: '', model: '', tier: 'standard', apiKey: '' })
const input = ref('')

// 输入框自动长高：一行起步，最多 6 行再滚（避免出现原生滚动条与上下箭头）
const inputEl = ref(null)
const MAX_INPUT_H = 150

function autoGrow() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, MAX_INPUT_H)}px`
}

function submit() {
  const text = input.value.trim()
  if (!text || busy.value) return
  sendAgentStream(text, props.scope)
  input.value = ''
  nextTick(autoGrow)
}
const customModel = ref(false)
const viewMode = ref('chat')

/** 轨迹页：把每一轮的工具调用摊平，按轮次分组（Q1/Q2…） */
const allSteps = computed(() =>
  turns.value
    .map((turn, index) => ({
      turnIndex: index + 1,
      question:
        index > 0 && turns.value[index - 1].role === 'user'
          ? turns.value[index - 1].text
          : '',
      steps: toolSteps(turn),
    }))
    .filter((item) => item.steps.length),
)

const totalSteps = computed(() =>
  allSteps.value.reduce((sum, item) => sum + item.steps.length, 0),
)

const providers = computed(() => (config.value && config.value.providers) || [])
const currentProvider = computed(() => {
  const base = form.baseUrl
  if (!base) return 'deepseek'
  const hit = providers.value.find((p) => p.base_url === base)
  return hit ? hit.id : 'local'
})
const keyHint = computed(() => (config.value && config.value.key_hint) || '')

/** 当前厂商在各档位下的预设模型（去重）——"能选模型"要看得见，而不是只让用户手打。 */
const modelOptions = computed(() => {
  const all = (config.value && config.value.tier_models) || {}
  const providerModels = all[currentProvider.value] || {}
  const seen = new Set()
  for (const model of Object.values(providerModels)) {
    if (model) seen.add(model)
  }
  // 当前已保存的模型也要在列表里（否则下拉显示不出来）
  if (form.model) seen.add(form.model)
  return [...seen]
})

// 下拉默认选中第一项：否则 <select :value="" 会显示空白，看着像"没有模型可选"
watch(modelOptions, (options) => {
  if (!form.model && options.length) form.model = options[0]
}, { immediate: true })

function pickModel(value) {
  if (value === '__custom') {
    customModel.value = true
    return
  }
  customModel.value = false
  form.model = value
}
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
  customModel.value = false
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

const pendingText = computed(() => {
  // 最后一条助手消息里已经有工具调用了，就把"正在干什么"说出来
  const last = [...turns.value].reverse().find((t) => t.role === 'assistant')
  const steps = last ? toolSteps(last) : []
  if (!steps.length) return '正在想…'
  const calls = steps.filter((s) => s.kind === 'tool_call')
  const done = steps.filter((s) => s.kind === 'tool_result').length
  if (calls.length > done) return `正在查：${calls[calls.length - 1].name}…`
  return `正在整理（已查 ${done} 次）…`
})

function thinkingTail(turn) {
  const text = String(turn.thinking || '').trim()
  return text.length > 240 ? `…${text.slice(-240)}` : text
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

</script>
