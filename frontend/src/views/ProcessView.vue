<template>
  <!-- 「处理过程」一屏（形态 v2 的 M5 / 任务总表 E15）。
       数据源＝**环节台账**（`memory_events`，契约 §2.5 的 N17）；
       与「我的 · AI 使用台账」**同源**，所以导出直接指向 `/api/me/ledger`，**不另造一套**。 -->
  <section class="proc">
    <header class="proc-top">
      <div>
        <h1 class="proc-t">处理过程</h1>
        <p class="proc-sub">
          它做了什么 —— 逐条来自环节台账，与「我的 · AI 使用台账」同一份数据（不另记一份）。
        </p>
      </div>
      <div class="proc-ops">
        <!-- 导出**复用**已有的 N26（同一张表），别在这里再拼一份 CSV -->
        <button type="button" class="btn ghost sm proc-csv" @click="download('csv', 'docwise-ledger.csv')">
          导出 CSV
        </button>
        <button type="button" class="btn ghost sm proc-md" @click="download('md', 'docwise-ledger.md')">
          导出 Markdown
        </button>
        <button type="button" class="btn sm proc-reload" @click="load">刷新</button>
      </div>
    </header>

    <!-- 筛选：按文献（task_id）与层级（layer）——契约 N17 支持这两个参数 -->
    <div class="proc-filters">
      <label class="proc-field">
        <span>文献</span>
        <select v-model="taskId" class="proc-select">
          <option value="">全部</option>
          <option v-for="item in taskOptions" :key="item.id" :value="String(item.id)">
            {{ item.filename }}
          </option>
        </select>
      </label>
      <label class="proc-field">
        <span>层级</span>
        <select v-model="layer" class="proc-select">
          <option value="">全部</option>
          <option value="L0">L0 · 环节</option>
          <option value="L1">L1 · 事实</option>
          <option value="L2">L2 · 偏好</option>
        </select>
      </label>
      <span v-if="tasksNote" class="proc-muted">{{ tasksNote }}</span>
    </div>

    <HonestNote v-if="error" :text="error" />
    <p v-else-if="loading && !rows.length" class="proc-muted proc-loading">正在读台账…</p>
    <!-- ⭐ 空态要说**为什么没有**（两种"没有"必须分清：一条都没跑过 / 只是这个筛选下没有） -->
    <p v-else-if="!rows.length" class="proc-empty">{{ emptyText }}</p>

    <ol v-else class="proc-list">
      <li v-for="row in viewRows" :key="row.id" class="proc-item">
        <div class="proc-head">
          <time class="proc-at">{{ fmtTime(row.created_at) }}</time>
          <span class="proc-stage">{{ stageText(row.stage) }}</span>
          <!-- ⭐ 数据流向芯片（契约 §2.8 逐字）：api = 正文真的发往了云端模型 API -->
          <span class="proc-flow" :class="actorFlowClass(row.actor)">{{ actorChip(row.actor) }}</span>
          <span v-if="row.tool" class="proc-tool">{{ row.tool }}</span>
        </div>
        <p class="proc-sum">{{ row.summary || '（这条没有说明）' }}</p>
        <div v-if="hasPayload(row)" class="proc-detail">
          <button type="button" class="proc-more" @click="toggle(row.id)">
            {{ opened.has(row.id) ? '收起明细' : '看明细' }}
          </button>
          <template v-if="opened.has(row.id)">
            <!-- ⭐ 译文编辑那一条：**逐条 diff**（改前 / 改后）。拿不到明细就不给这一段，
                 下面的原始 JSON 会如实显示 payload 本身 —— 不许编一段 diff 出来。 -->
            <div v-if="row.diff" class="proc-diff">
              <div class="proc-diff-side">
                <span class="proc-diff-label">改前（模型译文）</span>
                <p class="proc-diff-before">{{ row.diff.before }}</p>
              </div>
              <div class="proc-diff-side">
                <span class="proc-diff-label">改后（人工译文）</span>
                <p class="proc-diff-after">{{ row.diff.after }}</p>
              </div>
              <p v-if="row.diff.blockId" class="proc-diff-where">
                位置：{{ row.diff.blockId }}
              </p>
            </div>
            <pre v-else class="proc-json">{{ pretty(row.payload) }}</pre>
          </template>
        </div>
      </li>
    </ol>

    <HonestNote
      text="口径：服务自持 + 文献存本地；外文翻译、扫描件逐段翻译、导读与问答仍会调用云端模型 API——上面每条的流向芯片就是逐条的机器证据。"
    />
  </section>
</template>

<script setup>
/**
 * 处理过程一屏（`#/process`）：把**环节台账**按"新的在前"摆出来。
 *
 * 三条口径：
 * ① **同源**：读的是 N17（`/api/memory-events`），与「我的」页那张「AI 使用台账」是**同一张表**；
 *    导出也直接用它（`/api/me/ledger?format=csv|md`），**不另做一份台账**。
 * ② ⭐ **`actor` 必须如实显示**：`api` → 「▲ 正文发往模型 API」、`local` → 「● 不出本机」。
 *    这一屏存在的意义之一就是这个"数据流向的证据"，含糊过去等于把披露做成装饰。
 * ③ **明细默认收起**：`payload` 是下钻用的，一屏铺开就成了日志墙；**没有 payload 就不给控件**。
 */
import { computed, onMounted, ref, watch } from 'vue'

import { apiJson, authFetch } from '../auth'
import HonestNote from '../components/HonestNote.vue'
import { actorChip, actorFlowClass, editDiff, stageText } from '../ledgerText'

/** 一次最多读多少条（与后端 N17 的上限 1000 对齐；默认给 200，别一次拉爆）。 */
const LIMIT = 200

const rows = ref([])
const loading = ref(false)
const error = ref('')
const taskId = ref('')
const layer = ref('')
const taskOptions = ref([])
const tasksNote = ref('')
const opened = ref(new Set())

/**
 * 列表用的行：**在取数后把 diff 算一次**（别在模板里反复调函数）。
 *
 * `diff` 只有"译文编辑"那一条才有（`ledgerText.editDiff` —— 拿不到就 `null`，
 * 模板据此回落到原始 JSON，**不许编一段 diff**）。
 */
const viewRows = computed(() =>
  rows.value.map((row) => ({ ...row, diff: editDiff(row) })),
)

/** 台账行是否值得给"看明细"：`payload` 得是**有内容的对象**（空对象不算）。 */
function hasPayload(row) {
  const value = row?.payload
  return Boolean(value) && typeof value === 'object' && Object.keys(value).length > 0
}

function toggle(id) {
  const next = new Set(opened.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  opened.value = next
}

function pretty(payload) {
  try {
    return JSON.stringify(payload, null, 2)
  } catch {
    // 坏掉的 payload 也别让整屏挂掉：如实说它读不出来
    return '（这条明细读不出来）'
  }
}

function fmtTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** ⭐ 空态分两种：**一条都没有**（跑一次就会出现）vs **只是这个筛选下没有**。 */
const emptyText = computed(() => {
  if (taskId.value || layer.value) {
    return '当前筛选下没有记录 —— 换一篇文献、或把「层级」放宽到「全部」再看。'
  }
  return '还没有环节记录：上传并跑一篇文献（取字 / 翻译 / 扫描件 OCR / 导读），或问一次问题，这里就会逐条列出来。'
})

function query() {
  const params = new URLSearchParams({ limit: String(LIMIT) })
  if (taskId.value) params.set('task_id', taskId.value)
  if (layer.value) params.set('layer', layer.value)
  return `/api/memory-events?${params.toString()}`
}

/** 新的在前：后端已经排好，这里**再排一次**（同秒/坏数据也不会乱序）。 */
function sortNewestFirst(items) {
  return [...items].sort((a, b) => {
    const left = String(a?.created_at || '')
    const right = String(b?.created_at || '')
    if (left !== right) return left < right ? 1 : -1
    return Number(b?.id || 0) - Number(a?.id || 0)
  })
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiJson(query())
    rows.value = sortNewestFirst(Array.isArray(data?.items) ? data.items : [])
  } catch (err) {
    // 取不到就如实说，**不拿假数据顶**（这一屏是"证据"，掺假比空着更糟）
    rows.value = []
    error.value = `台账暂时取不到（${err.message}）—— 这一屏先空着，不拿假数据顶。`
  } finally {
    loading.value = false
  }
}

/** 文献筛选的选项：读不到就只留「全部」，并如实说明（不给假选项）。 */
async function loadTaskOptions() {
  try {
    const data = await apiJson('/api/tasks')
    taskOptions.value = (Array.isArray(data) ? data : []).map((item) => ({
      id: item.id,
      filename: item.filename || `文献 ${item.id}`,
    }))
  } catch (err) {
    taskOptions.value = []
    tasksNote.value = `文献列表取不到（${err.message}）—— 筛选先只按「全部」看。`
  }
}

/** 导出复用 N26（同一张表）：请求带令牌 → 落 Blob → 触发下载（`<a>` 带不了请求头）。 */
async function download(format, filename) {
  try {
    const response = await authFetch(`/api/me/ledger?format=${format}`)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch (err) {
    error.value = `导出失败（${err.message}）`
  }
}

onMounted(() => {
  loadTaskOptions()
  load()
})

// 筛选一变就重读（两个下拉都是"选完即生效"，不用再点一次）
watch([taskId, layer], load)
</script>
