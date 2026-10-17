<template>
  <!-- 「记忆」一屏（形态 v2 的 M7 · 任务卡 D8/D9）。
       它记的是**这个人的用法偏好**，不是台账、也不是素材：
       · 术语习惯 —— 同一个词别这篇叫「手性」、下篇叫「手征」；
       · 引用习惯 —— 插引文默认用哪种格式。
       ⚠️ 这一页的铁律：**每条都能改、能停用、能删**（形态 §六"可看可删可下钻"），
       而且**系统不许背着人改**——这页是唯一的出口。 -->
  <section class="mem">
    <header class="mem-top">
      <div>
        <h1 class="mem-t">记忆</h1>
        <p class="mem-sub">
          记住你的用法偏好 —— 术语怎么叫、引用用什么格式。下次问答与导读会沿用它们。
        </p>
      </div>
      <div class="mem-ops">
        <span class="mem-count">{{ countsText(counts) }}</span>
        <button type="button" class="btn ghost sm mem-reload" @click="load">刷新</button>
      </div>
    </header>

    <HonestNote v-if="error" class="mem-error" :text="error" />

    <!-- ⚠️ 取不到就如实说、**不拿假数据顶**（这一屏的意义就是"你的偏好在这里"，掺假比空着更糟） -->
    <p v-if="loading" class="mem-loading">正在读你的记忆…</p>

    <!-- ───────────── 术语习惯 ───────────── -->
    <section class="mem-block">
      <h2 class="mem-h">
        术语习惯
        <span class="mem-count-inline">{{ termItems.length }} 条</span>
      </h2>

      <p v-if="!termItems.length && !loading" class="mem-empty">
        {{ emptyTextFor('term') }}
      </p>

      <ul v-else class="mem-list">
        <li
          v-for="item in termItems"
          :key="item.id"
          class="mem-row"
          :class="{ paused: isPaused(item), doomed: doomedIds.has(item.id) }"
        >
          <template v-if="editingId === item.id">
            <label class="mem-field">
              <span>原文里怎么写</span>
              <input v-model="editSource" class="mem-input" type="text" readonly />
            </label>
            <label class="mem-field">
              <span>你习惯叫什么</span>
              <input v-model="editTarget" class="mem-input" type="text" maxlength="200" />
            </label>
            <div class="mem-row-ops">
              <button type="button" class="btn sm mem-save" :disabled="saving" @click="saveEdit(item)">
                存下
              </button>
              <button type="button" class="btn ghost sm mem-cancel" @click="cancelEdit">取消</button>
            </div>
            <p v-if="rowError" class="mem-row-error">{{ rowError }}</p>
          </template>

          <template v-else>
            <div class="mem-pair">
              <span class="mem-src">{{ item.source }}</span>
              <span class="mem-arrow" aria-hidden="true">→</span>
              <span class="mem-dst">{{ item.target }}</span>
            </div>
            <div class="mem-meta">
              <span class="mem-hits" :title="'这条被真正用上过几次'">{{ hitsText(item.hits) }}</span>
              <span v-if="isPaused(item)" class="mem-paused">已停用（不注入）</span>
            </div>
            <div class="mem-row-ops">
              <button type="button" class="btn ghost sm mem-edit" @click="startEdit(item)">改</button>
              <button type="button" class="btn ghost sm mem-toggle" @click="toggleEnabled(item)">
                {{ isPaused(item) ? '启用' : '停用' }}
              </button>
              <button
                v-if="!doomedIds.has(item.id)"
                type="button"
                class="btn ghost sm mem-del"
                @click="askDelete(item)"
              >
                删
              </button>
              <button v-else type="button" class="btn sm mem-undo" @click="undoDelete(item)">
                {{ undoLeft }} 秒内可撤销
              </button>
            </div>
          </template>
        </li>
      </ul>

      <!-- 新增一对：两边都要填，缺一边就说缺哪边 -->
      <form class="mem-add" @submit.prevent="addTerm">
        <label class="mem-field">
          <span>原文里怎么写</span>
          <input
            v-model="newSource"
            class="mem-input mem-new-src"
            type="text"
            maxlength="255"
            placeholder="例如 chiral"
          />
        </label>
        <label class="mem-field">
          <span>你习惯叫什么</span>
          <input
            v-model="newTarget"
            class="mem-input mem-new-dst"
            type="text"
            maxlength="200"
            placeholder="例如 手性"
          />
        </label>
        <button type="submit" class="btn sm mem-add-btn" :disabled="saving">记下来</button>
      </form>
      <p v-if="addError" class="mem-row-error">{{ addError }}</p>
      <p class="mem-hint">同一个词再记一次就是改它的说法（不会堆出两条）。</p>
    </section>

    <!-- ───────────── 引用习惯 ───────────── -->
    <section class="mem-block">
      <h2 class="mem-h">引用习惯</h2>
      <p v-if="!citeItem && !loading" class="mem-empty">{{ emptyTextFor('cite') }}</p>
      <div v-else-if="citeItem" class="mem-cite">
        <label class="mem-field">
          <span>插引文默认用</span>
          <select v-model="citeValue" class="mem-select" @change="saveCite">
            <option v-for="opt in CITE_OPTIONS" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
            <!-- 库里的值不在候选里：**原样显示**，不悄悄替用户改成别的 -->
            <option v-if="!isKnownCite(citeItem.target)" :value="citeItem.target">
              {{ citeItem.target }}（自定义）
            </option>
          </select>
        </label>
        <span class="mem-hits">{{ hitsText(citeItem.hits) }}</span>
      </div>
      <p v-if="!citeItem" class="mem-hint">
        还没设过？选一次就记住了 ——
        <select v-model="citeValue" class="mem-select mem-select-new" @change="saveCite">
          <option value="">（选一种）</option>
          <option v-for="opt in CITE_OPTIONS" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
      </p>
    </section>

    <!-- ───────────── 改过的句子 ───────────── -->
    <section class="mem-block">
      <h2 class="mem-h">改过的句子</h2>
      <!-- ⚠️ 这一栏**这一期就是空的**，而且要说清"为什么空"——
           写"暂无数据"是敷衍，写"正在学习"是骗人。说清门槛与现状才对。 -->
      <p class="mem-empty mem-edited-empty">{{ EDITED_EMPTY_TEXT }}</p>
    </section>
  </section>
</template>

<script setup>
/**
 * 「记忆」一屏（M7 · 契约 N35–N39）。
 *
 * 三条口径（与后端 `routers/memory.py` 一致，别在这里发明）：
 *
 * 1. ⭐ **能改、能停用、能删**：`PATCH` 换说法 / 停用，`DELETE` 真删。
 *    停用 = "先别用，但别丢"（`enabled=false` 之后不再注入，但仍列在这里）。
 * 2. ⭐ **删除给撤销窗口**（设计规范 §7.7 破坏性操作）：点「删」不立刻发请求，
 *    先标成待删除、给 5 秒撤销；到点才真删。离开本页时**把待删的立刻删掉**
 *    （不能因为用户切走就把它忘在半路）。
 * 3. ⭐ **"用过几次"如实显示**：0 次就是"还没用过"——
 *    不许说成"常用"，也不许拿它当"聪明度"吹。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { apiJson } from '../auth'
import HonestNote from '../components/HonestNote.vue'
import {
  CITE_OPTIONS,
  EDITED_EMPTY_TEXT,
  countsText,
  emptyTextFor,
  hitsText,
  isPaused,
  validateTerm,
} from '../memoryText'

/** 撤销窗口多少秒（设计规范 §7.7：破坏性操作要留退路）。 */
const UNDO_SECONDS = 5

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const rowError = ref('')
const addError = ref('')
const items = ref([])
const counts = ref({ term: 0, cite: 0 })

const newSource = ref('')
const newTarget = ref('')
const editingId = ref(0)
const editSource = ref('')
const editTarget = ref('')
const citeValue = ref('')

/** 待删除的行：`{id, timer, snapshot}`。到点真删；撤销就清掉。 */
const doomed = ref(new Map())
const doomedIds = computed(() => new Set(doomed.value.keys()))
const undoLeft = ref(UNDO_SECONDS)

let countdown = null

const termItems = computed(() => items.value.filter((item) => item.kind === 'term'))
const citeItem = computed(() => items.value.find((item) => item.kind === 'cite') || null)

function isKnownCite(value) {
  return CITE_OPTIONS.some((opt) => opt.value === value)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiJson('/api/memories')
    items.value = Array.isArray(data?.items) ? data.items : []
    counts.value = data?.counts || { term: 0, cite: 0 }
    const cite = items.value.find((item) => item.kind === 'cite')
    citeValue.value = cite ? cite.target : ''
  } catch (err) {
    // 取不到就如实说，**不拿假数据顶**
    items.value = []
    counts.value = { term: 0, cite: 0 }
    error.value = `记忆暂时取不到（${err.message}）—— 这一屏先空着，不拿假数据顶。`
  } finally {
    loading.value = false
  }
}

async function addTerm() {
  addError.value = ''
  const check = validateTerm(newSource.value, newTarget.value)
  if (!check.ok) {
    addError.value = check.error
    return
  }
  saving.value = true
  try {
    await apiJson('/api/memories', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: 'term', source: check.source, target: check.target }),
    })
    newSource.value = ''
    newTarget.value = ''
    await load()
  } catch (err) {
    // 失败如实说，**不清空输入**（让人重试，不用重敲）
    addError.value = `没记上：${err.message}`
  } finally {
    saving.value = false
  }
}

function startEdit(item) {
  editingId.value = item.id
  editSource.value = item.source
  editTarget.value = item.target
  rowError.value = ''
}

function cancelEdit() {
  editingId.value = 0
  editSource.value = ''
  editTarget.value = ''
  rowError.value = ''
}

async function saveEdit(item) {
  rowError.value = ''
  const check = validateTerm(editSource.value, editTarget.value)
  if (!check.ok) {
    rowError.value = check.error
    return
  }
  saving.value = true
  try {
    await apiJson(`/api/memories/${item.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: check.target }),
    })
    cancelEdit()
    await load()
  } catch (err) {
    rowError.value = `没改上：${err.message}`
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(item) {
  rowError.value = ''
  try {
    await apiJson(`/api/memories/${item.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !item.enabled }),
    })
    await load()
  } catch (err) {
    rowError.value = `没改成：${err.message}`
  }
}

/** 点「删」：**先不发请求**，进待删除态给撤销窗口（设计规范 §7.7）。 */
function askDelete(item) {
  const map = new Map(doomed.value)
  const timer = setTimeout(() => commitDelete(item.id), UNDO_SECONDS * 1000)
  map.set(item.id, { timer, snapshot: { ...item } })
  doomed.value = map
  startCountdown()
}

function startCountdown() {
  undoLeft.value = UNDO_SECONDS
  if (countdown) clearInterval(countdown)
  countdown = setInterval(() => {
    undoLeft.value = Math.max(0, undoLeft.value - 1)
    if (undoLeft.value === 0) {
      clearInterval(countdown)
      countdown = null
    }
  }, 1000)
}

function undoDelete(item) {
  const map = new Map(doomed.value)
  const entry = map.get(item.id)
  if (entry) clearTimeout(entry.timer)
  map.delete(item.id)
  doomed.value = map
}

async function commitDelete(id) {
  const map = new Map(doomed.value)
  const entry = map.get(id)
  if (!entry) return
  map.delete(id)
  doomed.value = map
  try {
    await apiJson(`/api/memories/${id}`, { method: 'DELETE' })
    await load()
  } catch (err) {
    // 删不掉就**还回列表**（不能让它凭空消失），并如实说
    rowError.value = `没删掉：${err.message}`
  }
}

async function saveCite() {
  const value = String(citeValue.value || '').trim()
  if (!value) return
  try {
    await apiJson('/api/memories', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: 'cite', source: 'default', target: value }),
    })
    await load()
  } catch (err) {
    rowError.value = `引用格式没存上：${err.message}`
  }
}

onMounted(load)

onBeforeUnmount(() => {
  if (countdown) clearInterval(countdown)
  // ⚠️ 离开本页时把待删的立刻删掉——不能因为用户切走就把它忘在半路
  for (const [id, entry] of doomed.value) {
    clearTimeout(entry.timer)
    apiJson(`/api/memories/${id}`, { method: 'DELETE' }).catch(() => {})
  }
  doomed.value = new Map()
})
</script>
