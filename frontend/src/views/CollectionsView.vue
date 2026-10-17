<template>
  <!-- 集合（契约 N1–N4）—— 2026-10-17 新开的一屏。
       为什么必须有：左栏「集合」以前点了只弹一句"还没做"，可**接口和数据一直都在**
       （实测 `/api/collections` 就有"化学组 / 空集合"）；做出来它才有意义。 -->
  <section class="kn">
    <header class="kn-top">
      <div>
        <h1 class="kn-t">集合</h1>
        <p class="kn-sub">
          把文献按项目 / 主题分组。**一篇文献可以同时在多个集合里**，不会复制一份。
        </p>
      </div>
      <div class="kn-ops">
        <span class="kn-count">{{ countsText }}</span>
        <button type="button" class="btn ghost sm" @click="load">刷新</button>
        <button type="button" class="btn primary sm" @click="startCreate">＋ 新建集合</button>
      </div>
    </header>

    <p v-if="error" class="kn-note kn-note-err">{{ error }}</p>

    <!-- 新建 / 改名：就地一个输入行，不做弹窗（少一层，键盘也能用） -->
    <form v-if="editing" class="kn-editor" @submit.prevent="submitEditor">
      <input
        v-model="draftName"
        class="kn-input"
        type="text"
        maxlength="60"
        :placeholder="editing === 'new' ? '新集合的名字，例如：毕业论文' : '改个名字'"
        autofocus
      />
      <button type="submit" class="btn primary sm" :disabled="busy || !draftName.trim()">
        {{ editing === 'new' ? '建' : '保存' }}
      </button>
      <button type="button" class="btn ghost sm" @click="cancelEditor">取消</button>
    </form>

    <ul v-if="collections.length" class="kn-list">
      <li v-for="item in collections" :key="item.id" class="card kn-row">
        <button type="button" class="kn-row-main" @click="openCollection(item)">
          <span class="kn-name">{{ item.name }}</span>
          <span class="kn-num">{{ item.count ?? 0 }} 篇</span>
        </button>
        <div class="kn-row-ops">
          <button type="button" class="btn ghost sm" @click="startRename(item)">改名</button>
          <template v-if="confirmingId === item.id">
            <button type="button" class="btn danger sm" :disabled="busy" @click="remove(item)">
              确认删除
            </button>
            <button type="button" class="btn ghost sm" @click="confirmingId = null">再想想</button>
          </template>
          <button v-else type="button" class="btn ghost sm" @click="confirmingId = item.id">
            删除
          </button>
        </div>
      </li>
    </ul>

    <!-- 未归类：不是一个"集合"（集合是手建的容器），而是一条**固定规则**；
         所以它单独摆一行、并说清它是什么，不混进上面的列表。 -->
    <div v-if="unfiledCount !== null" class="card kn-unfiled">
      <button type="button" class="kn-row-main" @click="openUnfiled">
        <span class="kn-name">未归类</span>
        <span class="kn-num">{{ unfiledCount }} 篇</span>
      </button>
      <span class="kn-hint">还没放进任何集合的文献。删除集合不会删文献——它们会回到这里。</span>
    </div>

    <div v-if="!collections.length && !loading" class="kn-empty">
      还没有集合。点右上角「＋ 新建集合」，然后用「历史记录」卡片上的「归集」把文献放进来。
    </div>

    <!-- ==================== 智能集合（契约 N9–N11） ====================
         与"集合"的区别：集合是**手建的容器**，智能集合是**一条规则**
         （"状态 = 待读"），文献自己进进出出，不用手动搬。
         ⚠️ **内置的那几条不许删**（契约 N11 回 400），所以按钮就不给它。 -->
    <section class="kn-smart">
      <div class="kn-top">
        <div>
          <h2 class="kn-h2">智能集合</h2>
          <p class="kn-sub">按规则自动收文献——不用手动往里面放，条件满足就出现。</p>
        </div>
      </div>

      <ul v-if="smart.length" class="kn-list">
        <li v-for="item in smart" :key="item.id" class="card kn-row">
          <button type="button" class="kn-row-main" @click="openSmart(item)">
            <span class="kn-name">{{ item.name }}</span>
            <span class="kn-num">{{ item.count ?? 0 }} 篇</span>
          </button>
          <span class="chip kn-kind">{{ ruleText(item.query) }}</span>
          <span v-if="item.builtin" class="kn-hint">内置</span>
          <button v-else type="button" class="btn ghost sm" @click="removeSmart(item)">删除</button>
        </li>
      </ul>
      <p v-else class="kn-empty">还没有智能集合——下面建一条。</p>

      <form class="kn-editor" @submit.prevent="createSmart">
        <input
          v-model="smartName"
          class="kn-input"
          type="text"
          maxlength="40"
          placeholder="新智能集合的名字，例如：还没读的方法类"
        />
        <select v-model="smartStatus" class="kn-input kn-select">
          <option value="todo">规则：状态 = 待读</option>
          <option value="reading">规则：状态 = 在读</option>
          <option value="done">规则：状态 = 已读</option>
        </select>
        <button type="submit" class="btn primary sm" :disabled="smartBusy || !smartName.trim()">
          建
        </button>
      </form>
      <p v-if="smartError" class="kn-note kn-note-err">{{ smartError }}</p>
    </section>

    <p v-if="toast" class="kn-note">{{ toast }}</p>
  </section>
</template>

<script setup>
/**
 * 集合整页（N1–N4 + N8 的 `unfiled`）。**只做这一件事**：看出我有哪些集合、增删改、点进去筛。
 *
 * 三条口径：
 * 1. ⭐ **删集合不删文献**（契约 N4 的 `moved_to_parent`）——所以删除确认里必须这么说，
 *    用户才敢点；
 * 2. ⭐ **"未归类"是规则不是集合**：它由 `?unfiled=1` 现算，不落库、不许改名；
 * 3. ⭐ 收藏都在后端：建/改名/删都**先请求成功再改本地**，失败如实说（不乐观更新，
 *    否则失败后界面是个骗子）。
 */
import { computed, onMounted, ref } from 'vue'

import { apiJson } from '../auth'
import { navigate } from '../router'
import { loadTasksAndSync } from '../stores/useLibrary'
import { collections, loadKnowledge, smartCollections } from '../stores/useKnowledge'

const loading = ref(false)
const busy = ref(false)
const error = ref('')
const toast = ref('')

/** `'new'` = 正在建；数字 = 正在改那条的 id；`null` = 没在编辑 */
const editing = ref(null)
const draftName = ref('')
const confirmingId = ref(null)
const unfiledCount = ref(null)

const countsText = computed(() =>
  collections.value.length ? `${collections.value.length} 个集合` : '还没有集合',
)

function messageOf(err, fallback) {
  return err && err.message ? String(err.message) : fallback
}

async function load() {
  loading.value = true
  error.value = ''
  await loadKnowledge()
  // 「未归类」的篇数：现查一次（没有专门接口，`?unfiled=1` 就是它的口径）
  try {
    const rows = await apiJson('/api/tasks?unfiled=1')
    unfiledCount.value = Array.isArray(rows) ? rows.length : 0
  } catch {
    unfiledCount.value = null // 拿不到就不显示数字（不编 0）
  }
  loading.value = false
}

onMounted(load)

function startCreate() {
  editing.value = 'new'
  draftName.value = ''
  error.value = ''
}

function startRename(item) {
  editing.value = item.id
  draftName.value = item.name
  error.value = ''
}

function cancelEditor() {
  editing.value = null
  draftName.value = ''
}

async function submitEditor() {
  const name = draftName.value.trim()
  if (!name || busy.value) return
  busy.value = true
  error.value = ''
  try {
    if (editing.value === 'new') {
      await apiJson('/api/collections', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      toast.value = `已建集合「${name}」`
    } else {
      await apiJson(`/api/collections/${editing.value}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      toast.value = `已改名为「${name}」`
    }
    cancelEditor()
    await load()
  } catch (err) {
    error.value = `没保存成功（${messageOf(err, '网络或服务异常')}）`
  } finally {
    busy.value = false
  }
}

async function remove(item) {
  busy.value = true
  error.value = ''
  try {
    await apiJson(`/api/collections/${item.id}`, { method: 'DELETE' })
    confirmingId.value = null
    toast.value = `已删除集合「${item.name}」——里面的文献还在，只是回到了「未归类」`
    await load()
  } catch (err) {
    error.value = `没删掉（${messageOf(err, '网络或服务异常')}）`
  } finally {
    busy.value = false
  }
}

/** 点集合 = 去历史记录看它里面的文献（筛的是**直接成员**，与集合计数同一口径）。 */
async function openCollection(item) {
  await loadTasksAndSync({ collection_id: item.id })
  navigate('library')
}

async function openUnfiled() {
  await loadTasksAndSync({ unfiled: 1 })
  navigate('library')
}

// ---------------------------------------------------------------- 智能集合（N9–N11）
const smart = smartCollections
const smartName = ref('')
const smartStatus = ref('todo')
const smartBusy = ref(false)
const smartError = ref('')

const STATUS_TEXT = { todo: '状态 = 待读', reading: '状态 = 在读', done: '状态 = 已读' }

/** 规则 → 人话（"规则即数据"：不能只显示名字，用户要看得见它凭什么收文献）。 */
function ruleText(query) {
  const parts = query?.all
  if (!Array.isArray(parts) || !parts.length) return '规则未给出'
  return parts
    .map((part) => {
      const field = part?.field === 'reading_status' ? '状态' : String(part?.field ?? '?')
      const value = STATUS_TEXT[part?.value] || String(part?.value ?? '?')
      return part?.field === 'reading_status' ? `状态 = ${value.replace('状态 = ', '')}` : `${field} ${part?.op ?? '?'} ${value}`
    })
    .join('，')
}

async function createSmart() {
  const name = smartName.value.trim()
  if (!name || smartBusy.value) return
  smartBusy.value = true
  smartError.value = ''
  try {
    await apiJson('/api/smart-collections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        query: { all: [{ field: 'reading_status', op: 'eq', value: smartStatus.value }] },
      }),
    })
    smartName.value = ''
    toast.value = `已建智能集合「${name}」`
    await load()
  } catch (err) {
    smartError.value = `没建成（${messageOf(err, '网络或服务异常')}）`
  } finally {
    smartBusy.value = false
  }
}

async function removeSmart(item) {
  smartError.value = ''
  try {
    await apiJson(`/api/smart-collections/${item.id}`, { method: 'DELETE' })
    toast.value = `已删除智能集合「${item.name}」——文献一篇都没动`
    await load()
  } catch (err) {
    smartError.value = `没删掉（${messageOf(err, '网络或服务异常')}）`
  }
}

async function openSmart(item) {
  await loadTasksAndSync({ smart_id: item.id })
  navigate('library')
}
</script>
