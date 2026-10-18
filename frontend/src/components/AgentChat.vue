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
          <div v-if="turn.error" class="agent-error">
            <span>{{ turn.error }}</span>
            <button type="button" :disabled="busy" @click="retry(turn)">重试</button>
          </div>
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

            <!-- 写作侧：可采用的替换建议（点了才写进稿子） -->
            <div v-if="turn.revisions && turn.revisions.length" class="agent-revisions">
              <div v-for="(rev, k) in turn.revisions" :key="k" class="agent-rev">
                <div class="agent-rev-orig">{{ rev.original }}</div>
                <div class="agent-rev-new">{{ rev.revised }}</div>
                <div class="agent-rev-foot">
                  <span class="agent-rev-reason">{{ rev.reason }}</span>
                  <button type="button" @click="$emit('apply-revision', rev)">采用</button>
                </div>
              </div>
            </div>
            <div v-if="turn.notes && turn.notes.length" class="agent-notes">
              <span v-for="(note, k) in turn.notes" :key="k">{{ note }}</span>
            </div>

            <!-- 元信息：只写算得出来的事实（模型 / 用时 / 步数） -->
            <div v-if="turn.done" class="agent-meta">
              <span v-if="turn.model || modelLabel">{{ turn.model || modelLabel }}</span>
              <span v-if="turn.elapsedMs">{{ (turn.elapsedMs / 1000).toFixed(1) }}s</span>
              <span v-if="toolSteps(turn).length">{{ toolSteps(turn).length }} 步</span>
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
    <div v-if="viewMode === 'chat'" class="agent-composer">
      <!-- 设置面板 -->
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
        <div class="agent-model-wrap">
          <button
            class="agent-model-btn"
            :class="{ warn: !modelReady }"
            type="button"
            :title="modelReady ? '选模型' : '还没配模型，先去设置里配'"
            @click="toggleModels()"
          >
            {{ modelReady ? modelLabel : '未配置模型' }}
            <span class="agent-model-hint">▾</span>
          </button>
        <!-- ⭐ 只选模型：一个列表，点一下换；自定义配置在「设置」里 -->
          <div v-if="modelOpen" class="agent-models">
          <div class="agent-models-head">选择模型</div>
          <button
            v-for="item in modelChoices"
            :key="item.provider + ':' + item.model"
            type="button"
            class="agent-models-item"
            :class="{ on: item.active }"
            @click="chooseModel(item)"
          >
            <span class="agent-models-name">{{ item.model }}</span>
            <span class="agent-models-provider">{{ item.providerName }}</span>
            <span v-if="item.active" class="agent-models-check">✓</span>
          </button>
          <button class="agent-models-more" type="button" @click="openSettingsFromPicker()">
            更多设置（接口地址 / API Key / 强度）
          </button>
        </div>
        </div>
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
  agentError,
  agentMessages,
  agentSaveNote,
  agentSceneId,
  loadConfig,
  loadScenes,
  openSettings,
  saveAgentConfig,
  retryTurn,
  sendAgentStream,
  setScene,
  toolStepsOf,
} from '../stores/useAgent'

const props = defineProps({
  scope: { type: Object, default: () => ({}) },
  // 场景：读懂 = read_ask（默认），写作 = write_compose
  scene: { type: String, default: 'read_ask' },
})
const emit = defineEmits(['quick', 'apply-revision'])

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
const saveNote = agentSaveNote
const sceneId = agentSceneId
const saving = ref(false)
const traceOpen = reactive({})

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
  const hit = providers.value.find((p) => p.base_url === (config.value || {}).base_url)
  return hit ? hit.id : 'deepseek'
})

/**
 * 模型列表：按厂商摊平，**只读后端给的预设**（不提供自定义输入——
 * 自定义属于「设置」，挤在输入框旁边就会变成一坨表单）。
 */
const modelChoices = computed(() => {
  const cfg = config.value || {}
  const tierModels = cfg.tier_models || {}
  const out = []
  const seen = new Set()
  for (const provider of providers.value) {
    for (const model of Object.values(tierModels[provider.id] || {})) {
      if (!model) continue
      const key = `${provider.id}:${model}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({
        provider: provider.id,
        providerName: provider.name,
        model,
        baseUrl: provider.base_url,
        active: cfg.model === model,
      })
    }
  }
  // 当前模型若不在预设里（如服务端默认），也要能看见"现在用的是哪个"
  if (cfg.model && !out.some((item) => item.model === cfg.model)) {
    out.unshift({
      provider: currentProvider.value,
      providerName: '当前',
      model: cfg.model,
      baseUrl: cfg.base_url || '',
      active: true,
    })
  }
  return out
})

const modelOpen = ref(false)

function toggleModels() {
  modelOpen.value = !modelOpen.value
}

async function chooseModel(item) {
  modelOpen.value = false
  await saveAgentConfig({
    baseUrl: item.baseUrl || (config.value || {}).base_url || '',
    model: item.model,
    tier: (config.value || {}).tier || 'standard',
    apiKey: '',
  })
}

function openSettingsFromPicker() {
  modelOpen.value = false
  openSettings(true)
}

const modelReady = computed(() => Boolean(config.value && (config.value.key_set || config.value.server_default)))
const modelLabel = computed(() => {
  if (!config.value) return '未配置模型'
  if (!modelReady.value) return '未配置模型'
  const model = config.value.model || '默认模型'
  return model
})
const tierLabel = computed(() => {
  const tier = (config.value && config.value.tier) || 'standard'
  return { fast: '快', standard: '标准', strong: '强' }[tier] || tier
})



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

function retry(turn) {
  // 用页面给的 scope 重问（撤掉失败那条由 store 负责）
  retryTurn(turn, props.scope)
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
  // ⚠️ 必须**在 loadScenes 之后**切场景：反过来会被默认场景顶掉，
  // 写作页就会拿 read_ask 的 scene 去问（连 output 类型都是错的）。
  if (props.scene && props.scene !== sceneId.value) setScene(props.scene)
})

</script>
