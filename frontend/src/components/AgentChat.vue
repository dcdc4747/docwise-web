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
      <span class="agent-views-spacer" />
      <!-- 开新对话：只清当前场景（读懂/写作各一条，互不影响） -->
      <button
        type="button"
        class="agent-new-thread"
        :disabled="busy"
        :title="busy ? '等这轮答完再开新对话' : '清空当前对话，重新开始'"
        @click="startNewThread"
      >
        ＋ 新对话
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
              <!-- 批量：整组采纳 / 忽略。`全部采用（N）` 里的 N 是**还没处置**的条数 -->
              <div class="agent-revs-head">
                <span class="agent-revs-count">{{ turn.revisions.length }} 条建议</span>
                <span class="spacer" />
                <!-- ⭐ 复制全部：只拼**未忽略**的改后文本（已忽略的不算数） -->
                <button
                  type="button"
                  class="agent-revs-copy"
                  :disabled="!copyableCount(i, turn)"
                  @click="copyAll(i, turn)"
                >
                  复制全部改后文本
                </button>
                <button
                  type="button"
                  class="agent-revs-all"
                  :disabled="!pendingCount(i, turn)"
                  @click="applyAll(i, turn)"
                >
                  全部采用（{{ pendingCount(i, turn) }}）
                </button>
                <button
                  type="button"
                  class="agent-revs-ignore"
                  :disabled="!pendingCount(i, turn)"
                  @click="ignoreAll(i, turn)"
                >
                  忽略全部
                </button>
              </div>
              <p
                v-if="copyHints[i + ':all']"
                class="agent-revs-hint"
                :class="{ bad: copyHints[i + ':all'].bad }"
                role="status"
                aria-live="polite"
              >
                {{ copyHints[i + ':all'].text }}
              </p>
              <!--
                ⭐ 段落级建议（`original` 可能是一整段）：正文最多 3 行，超出折起来。
                折叠是**按字数估 + 模板里真的截断**（不靠浏览器量高度——happy-dom 不排版，
                量不出来），再用 CSS 的 3 行钳兜一层。**不用 v-html**：这里全是文本插值。
              -->
              <div
                v-for="(rev, k) in turn.revisions"
                :key="k"
                class="agent-rev"
                :class="[revisionClass(i, k), { 'is-long': isLongRevision(rev) }]"
              >
                <div
                  class="agent-rev-orig"
                  :class="{ 'is-clamped': isClamped(i, k, rev.original) }"
                >{{ bodyText(i, k, rev.original) }}</div>
                <div
                  class="agent-rev-new"
                  :class="{ 'is-clamped': isClamped(i, k, rev.revised) }"
                >{{ bodyText(i, k, rev.revised) }}</div>
                <button
                  v-if="isCollapsible(rev)"
                  type="button"
                  class="agent-rev-expand"
                  :aria-expanded="isExpanded(i, k) ? 'true' : 'false'"
                  @click="toggleExpand(i, k)"
                >
                  {{ isExpanded(i, k) ? '收起' : '展开全文' }}
                </button>
                <div class="agent-rev-foot">
                  <span class="agent-rev-reason">{{ rev.reason }}</span>
                  <span
                    v-if="revisionStatus(i, k)"
                    class="agent-rev-state"
                    :class="revisionClass(i, k)"
                  >
                    {{ revisionStatusText(i, k) }}
                  </span>
                  <button
                    type="button"
                    class="agent-rev-copy"
                    @click="copyOne(i, k, rev)"
                  >
                    复制改后文本
                  </button>
                  <button
                    type="button"
                    class="agent-rev-apply"
                    :disabled="isSettled(i, k)"
                    @click="applyOne(i, k, rev)"
                  >
                    采用
                  </button>
                  <button
                    type="button"
                    class="agent-rev-ignore"
                    :disabled="isSettled(i, k)"
                    @click="ignoreOne(i, k)"
                  >
                    忽略
                  </button>
                </div>
                <p
                  v-if="copyHints[i + ':' + k]"
                  class="agent-rev-hint"
                  :class="{ bad: copyHints[i + ':' + k].bad }"
                  role="status"
                  aria-live="polite"
                >
                  {{ copyHints[i + ':' + k].text }}
                </p>
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
  newThread,
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

// ============================================================ 改写建议：采用 / 忽略（单条与批量）

/**
 * 每条建议的处置：`applied`（已采用）/ `ignored`（已忽略）/ `missing`（正文里找不到原句）。
 *
 * 键用「第几轮 : 第几条」——**同一条建议不能重复采用**，批量也不会把已经处置过的再带上。
 * 对话清空时一并清掉（否则新一轮的第 0 条会继承上一轮的状态）。
 */
const revStates = reactive({})

function revisionStatus(turnIndex, revIndex) {
  return revStates[`${turnIndex}:${revIndex}`] || ''
}

function setRevisionStatus(turnIndex, revIndex, status) {
  revStates[`${turnIndex}:${revIndex}`] = status
}

/** 已处置（采用 / 忽略）的不能再点；`missing` 不算处置过——正文改一下还能再试。 */
function isSettled(turnIndex, revIndex) {
  const status = revisionStatus(turnIndex, revIndex)
  return status === 'applied' || status === 'ignored'
}

/** 卡片左侧的状态色（绿 = 已采用、灰 = 已忽略、琥珀 = 正文里没找到）。 */
function revisionClass(turnIndex, revIndex) {
  const status = revisionStatus(turnIndex, revIndex)
  return status ? `is-${status}` : ''
}

function revisionStatusText(turnIndex, revIndex) {
  const status = revisionStatus(turnIndex, revIndex)
  if (status === 'applied') return '已采用'
  if (status === 'ignored') return '已忽略'
  if (status === 'missing') return '没采用 · 原文没找到'
  return ''
}

/** 还没处置的条数（「全部采用（N）」的 N，也是「忽略全部」的作用范围）。 */
function pendingCount(turnIndex, turn) {
  const revisions = (turn && turn.revisions) || []
  let count = 0
  revisions.forEach((_, revIndex) => {
    if (!isSettled(turnIndex, revIndex)) count += 1
  })
  return count
}

/**
 * 采用一条：只把 `apply-revision` 抛给页面——**正文的替换由页面做**，组件不碰稿子。
 *
 * `report` 是页面回报结果的通道：页面的 `applyRevision` 是同步函数，所以 `emit` 返回时
 * 结果已经拿到了。页面说"正文里找不到原句"时不能标成「已采用」（那是假话），标 `missing`。
 */
function applyOne(turnIndex, revIndex, rev) {
  if (isSettled(turnIndex, revIndex)) return
  let outcome = null
  emit('apply-revision', rev, {
    report: (ok) => {
      outcome = ok
    },
  })
  setRevisionStatus(turnIndex, revIndex, outcome === false ? 'missing' : 'applied')
}

function ignoreOne(turnIndex, revIndex) {
  if (isSettled(turnIndex, revIndex)) return
  setRevisionStatus(turnIndex, revIndex, 'ignored')
}

/**
 * 全部采用：**依次**把每条待处理建议交回页面（同一个 `apply-revision`，与单条点「采用」一致）。
 * `batch = { total, index, last }` 让页面知道这是同一批、哪一条是最后一条（页面的
 * 「采用 N 条，跳过 M 条」汇总与批量撤销都挂在这上面）。
 */
function applyAll(turnIndex, turn) {
  const rows = []
  ;((turn && turn.revisions) || []).forEach((rev, revIndex) => {
    if (rev && !isSettled(turnIndex, revIndex)) rows.push({ revIndex, rev })
  })
  const total = rows.length
  if (!total) return
  rows.forEach((row, index) => {
    let outcome = null
    emit('apply-revision', row.rev, {
      batch: { total, index, last: index === total - 1 },
      report: (ok) => {
        outcome = ok
      },
    })
    setRevisionStatus(turnIndex, row.revIndex, outcome === false ? 'missing' : 'applied')
  })
}

/** 忽略全部：只标成已忽略，**不发 `apply-revision`**——之后批量采用也不会再带上它们。 */
function ignoreAll(turnIndex, turn) {
  ;((turn && turn.revisions) || []).forEach((_, revIndex) => {
    if (!isSettled(turnIndex, revIndex)) setRevisionStatus(turnIndex, revIndex, 'ignored')
  })
}

// ============================================================ 改写建议：长文折叠 / 复制

/**
 * 折叠阈值：窄侧栏一行约 25–30 个汉字，3 行 ≈ 80 字。
 *
 * ⚠️ 不在模板里量 `scrollHeight`：happy-dom（测试环境）不做排版，量出来恒为 0，
 * 那个判断在测试里永远是"没超出"——测不出来的东西不敢当唯一依据。
 * 所以这里**按字数估 + 真的把显示文本截断**，CSS 再按 3 行钳一次兜底。
 */
const FOLD_AT = 80
/** 超过这个字数算「长建议」：正文小一号、行高收紧（120 字基本就是一整段了）。 */
const LONG_AT = 120
/** 剪贴板被拒 / 非安全上下文 / 没有这个 API 时的兜底文案（不许静默失败）。 */
const COPY_FAILED = '复制失败，请手动选中'

const expanded = reactive({})
const copyHints = reactive({})

function lengthOf(value) {
  return String(value == null ? '' : value).trim().length
}

/** 这一段要不要折：超过 3 行的字数，或硬换了 3 行以上（段落级建议常带换行）。 */
function needsFold(value) {
  const text = String(value == null ? '' : value)
  return lengthOf(text) > FOLD_AT || text.split('\n').length > 3
}

function isCollapsible(rev) {
  if (!rev) return false
  return needsFold(rev.original) || needsFold(rev.revised)
}

function isLongRevision(rev) {
  if (!rev) return false
  return Math.max(lengthOf(rev.original), lengthOf(rev.revised)) > LONG_AT
}

function isExpanded(turnIndex, revIndex) {
  return Boolean(expanded[`${turnIndex}:${revIndex}`])
}

function toggleExpand(turnIndex, revIndex) {
  const key = `${turnIndex}:${revIndex}`
  expanded[key] = !expanded[key]
}

/** 折叠时只显示前 3 行 / 前 80 字（截过才加省略号，没截就不加）。 */
function foldText(value) {
  const text = String(value == null ? '' : value)
  const lines = text.split('\n').slice(0, 3)
  let out = lines.join('\n')
  if (out.length > FOLD_AT) out = out.slice(0, FOLD_AT).trimEnd()
  return out === text ? text : `${out.trimEnd()}…`
}

function bodyText(turnIndex, revIndex, value) {
  return isExpanded(turnIndex, revIndex) ? String(value == null ? '' : value) : foldText(value)
}

/** 折叠态才挂 3 行钳（CSS），展开后整段铺开。 */
function isClamped(turnIndex, revIndex, value) {
  return needsFold(value) && !isExpanded(turnIndex, revIndex)
}

/**
 * 未忽略的条目（「复制全部」的作用范围）。
 * `applied` / `missing` 都算——只有被用户**明确忽略**的才不复制。
 */
function copyableRevisions(turnIndex, turn) {
  return ((turn && turn.revisions) || []).filter(
    (rev, revIndex) =>
      rev &&
      revisionStatus(turnIndex, revIndex) !== 'ignored' &&
      Boolean(String(rev.revised || '').trim()),
  )
}

function copyableCount(turnIndex, turn) {
  return copyableRevisions(turnIndex, turn).length
}

function setCopyHint(key, text, bad = false) {
  copyHints[key] = { text, bad }
}

function copyHintKey(turnIndex, revIndex) {
  return `${turnIndex}:${revIndex}`
}

async function writeClipboard(text) {
  if (
    typeof navigator === 'undefined' ||
    !navigator.clipboard ||
    typeof navigator.clipboard.writeText !== 'function'
  ) {
    throw new Error('clipboard-unavailable')
  }
  await navigator.clipboard.writeText(text)
}

/** 复制一条改后文本；成功/失败都写在卡片下方（失败给手动复制的兜底）。 */
async function copyOne(turnIndex, revIndex, rev) {
  const key = copyHintKey(turnIndex, revIndex)
  const text = String((rev && rev.revised) || '')
  if (!text.trim()) {
    setCopyHint(key, COPY_FAILED, true)
    return
  }
  try {
    await writeClipboard(text)
    setCopyHint(key, '已复制改后文本')
  } catch {
    setCopyHint(key, COPY_FAILED, true)
  }
}

/** 复制全部：**未忽略**的 revised 按换行拼起来（忽略掉的不算）。 */
async function copyAll(turnIndex, turn) {
  const key = `${turnIndex}:all`
  const rows = copyableRevisions(turnIndex, turn)
  if (!rows.length) {
    setCopyHint(key, '没有可复制的建议（都忽略了）')
    return
  }
  try {
    await writeClipboard(rows.map((rev) => String(rev.revised || '')).join('\n'))
    setCopyHint(key, `已复制 ${rows.length} 条改后文本`)
  } catch {
    setCopyHint(key, COPY_FAILED, true)
  }
}

// 清空对话（重新开一轮）时把处置 / 展开 / 复制提示一起清掉，免得新一轮继承旧状态
watch(
  () => turns.value.length,
  (len) => {
    if (len) return
    for (const key of Object.keys(revStates)) delete revStates[key]
    for (const key of Object.keys(expanded)) delete expanded[key]
    for (const key of Object.keys(copyHints)) delete copyHints[key]
  },
)

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

/** 开新对话：清空当前场景的线程（别的场景不动），并回到对话页。 */
function startNewThread() {
  if (busy.value) return
  newThread()
  viewMode.value = 'chat'
}

onMounted(async () => {
  await Promise.all([loadScenes(), loadConfig()])
  // ⚠️ 必须**在 loadScenes 之后**切场景：反过来会被默认场景顶掉，
  // 写作页就会拿 read_ask 的 scene 去问（连 output 类型都是错的）。
  if (props.scene && props.scene !== sceneId.value) setScene(props.scene)
})

</script>

<!--
  只补"批量操作行 + 三种处置状态 + 长文折叠 + 复制提示"这几条，
  **建议卡本体的样式仍走 style.css 里那套**（`.dw .agent-rev*`）。
  这里不引阴影、不加大色块：状态只用左侧一道细色条 + 小字标签。
-->
<style scoped>
.agent-views-spacer {
  flex: 1 1 auto;
}
.agent-new-thread {
  border: 0;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: var(--fs-micro);
  padding: 2px 6px;
  border-radius: 6px;
  cursor: pointer;
}
.agent-new-thread:hover:not(:disabled) {
  background: #f1f3f7;
  color: var(--ink);
}
.agent-new-thread:disabled {
  color: #c2c8d2;
  cursor: default;
}

.agent-revs-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 2px;
  /* 窄栏里「复制全部 + 全部采用 + 忽略全部」放不下一行：允许换行，别把按钮压扁 */
  flex-wrap: wrap;
}

.agent-revs-count {
  font-size: var(--fs-micro);
  color: var(--muted);
}

.agent-revs-head button {
  border: 1px solid var(--accent-line, #c7d2fe);
  background: #fff;
  color: var(--accent);
  border-radius: 999px;
  padding: 3px 10px;
  font: inherit;
  font-size: var(--fs-micro);
  cursor: pointer;
}

.agent-revs-head button:hover:not(:disabled) {
  background: var(--accent-soft, #eef2ff);
}

.agent-revs-head button.agent-revs-ignore {
  border-color: var(--line);
  color: var(--muted);
}

.agent-revs-head button:disabled {
  opacity: 0.45;
  cursor: default;
}

/* 已采用 / 已忽略 / 没找到：左侧一道细色条，卡片底色只做极轻的变化
   （色条从 1px 变 3px 会让文字右移 2px，所以左内边距补回 2px） */
.agent-rev.is-applied {
  border-left: 3px solid #86efac;
  padding-left: 8px;
  background: #f7fdf9;
}

.agent-rev.is-ignored {
  border-left: 3px solid #e2e8f0;
  padding-left: 8px;
  background: #fafafa;
  opacity: 0.72;
}

.agent-rev.is-missing {
  border-left: 3px solid #fcd34d;
  padding-left: 8px;
  background: #fffdf5;
}

/* 窄栏里「理由 + 状态 + 两个按钮」会挤：允许换行，别把按钮压扁 */
.agent-rev-foot {
  flex-wrap: wrap;
}

.agent-rev-state {
  flex: 0 0 auto;
  font-size: var(--fs-micro);
  color: var(--muted);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 1px 8px;
  white-space: nowrap;
}

.agent-rev-state.is-applied {
  color: #15803d;
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.agent-rev-state.is-missing {
  color: #b45309;
  border-color: #fde68a;
  background: #fffbeb;
}

.agent-rev-foot button.agent-rev-ignore {
  border-color: var(--line);
  color: var(--muted);
}

.agent-rev-foot button.agent-rev-ignore:hover:not(:disabled) {
  background: #f8fafc;
}

/* 处置过的按钮是死的：不给 hover 反馈，免得看着还能点 */
.agent-rev-foot button:disabled {
  opacity: 0.5;
  cursor: default;
}

.agent-rev-foot button:disabled:hover {
  background: #fff;
}

/* ---------- 段落级建议：长文折叠 ---------- */

/* 折叠态：CSS 兜一层 3 行（真截断在脚本里，这里防不同宽度下多出一行） */
.agent-rev-orig.is-clamped,
.agent-rev-new.is-clamped {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
}

/* 「展开全文 / 收起」：做成文字链，不跟底下的采用/忽略抢视觉 */
.agent-rev-expand {
  justify-self: start;
  border: 0;
  background: none;
  padding: 0;
  font: inherit;
  font-size: var(--fs-micro);
  color: var(--accent);
  cursor: pointer;
}

.agent-rev-expand:hover {
  text-decoration: underline;
}

/* 长建议（>120 字）视觉降噪：正文小一号、行高略紧（整段阅读时不再像一堵墙） */
.agent-rev.is-long .agent-rev-orig,
.agent-rev.is-long .agent-rev-new {
  font-size: var(--fs-micro);
  line-height: 1.55;
}

/* `reason` 始终小字灰（全局那份是 `.dw .agent-rev-reason`，这里加一层组件作用域钉死） */
.agent-rev .agent-rev-reason {
  font-size: var(--fs-micro);
  color: var(--muted);
}

/* ---------- 复制：成功 / 失败都当面说（失败给手动选中的兜底） ---------- */

.agent-revs-hint,
.agent-rev-hint {
  margin: 0;
  font-size: var(--fs-micro);
  line-height: 1.5;
  color: var(--muted);
}

.agent-revs-hint.bad,
.agent-rev-hint.bad {
  color: #b45309;
}

/* 复制按钮与「忽略」同色：它不改变建议的处置状态 */
.agent-rev-foot button.agent-rev-copy {
  border-color: var(--line);
  color: var(--muted);
}

.agent-rev-foot button.agent-rev-copy:hover:not(:disabled) {
  background: #f8fafc;
}

.agent-revs-head button.agent-revs-copy {
  border-color: var(--line);
  color: var(--muted);
}

.agent-revs-head button.agent-revs-copy:hover:not(:disabled) {
  background: #f8fafc;
}
</style>
