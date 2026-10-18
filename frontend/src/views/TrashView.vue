<template>
  <!-- 回收站（2026-10-18）：删除先落在**这里**，不是直接没了。
       口径：文件与子表都留在服务端，恢复＝原样回来；「彻底删除」才真删（不可恢复）。 -->
  <section class="kn">
    <header class="kn-top">
      <div>
        <h1 class="kn-t">回收站</h1>
        <p class="kn-sub">
          删掉的文献先放这里，文件也还在——<strong>随时能恢复</strong>。
          只有点「彻底删除」才会真的清掉（那一步不可恢复）。
        </p>
      </div>
      <div class="kn-ops">
        <span class="kn-count">{{ rows.length ? `${rows.length} 篇` : '' }}</span>
        <button type="button" class="btn ghost sm" :disabled="loading" @click="load">刷新</button>
      </div>
    </header>

    <p v-if="error" class="kn-note kn-note-err">{{ error }}</p>
    <p v-if="toast" class="kn-note">{{ toast }}</p>

    <ul v-if="rows.length" class="kn-list">
      <li v-for="item in rows" :key="item.id" class="card kn-row">
        <div class="trash-main">
          <span class="kn-name">{{ item.filename }}</span>
          <span class="kn-num">
            删除于 {{ fmtDeleted(item.deleted_at) }}<template v-if="item.tags?.length"
              >· {{ item.tags.join(' / ') }}</template
            >
          </span>
        </div>
        <div class="kn-row-ops">
          <button type="button" class="btn primary sm" :disabled="busy" @click="restore(item)">
            恢复
          </button>
          <template v-if="confirmingId === item.id">
            <button type="button" class="btn danger sm" :disabled="busy" @click="purge(item)">
              确认彻底删除
            </button>
            <button type="button" class="btn ghost sm" @click="confirmingId = null">再想想</button>
          </template>
          <button v-else type="button" class="btn ghost sm" @click="confirmingId = item.id">
            彻底删除…
          </button>
        </div>
      </li>
    </ul>

    <div v-else-if="!loading" class="kn-empty">
      回收站是空的。删掉的文献会先到这里——<strong>不会直接消失</strong>。
    </div>
  </section>
</template>

<script setup>
/**
 * 回收站。
 *
 * ⚠️ 三个口径：
 * 1. **删除 = 进回收站**（后端 `deleted_at` 软删），所以这里列表走 `?trashed=1`；
 * 2. **恢复**调 `POST /api/tasks/{id}/restore`；**彻底删除**调 `DELETE .../purge`，
 *    且后端只接受回收站里的任务（两步确认是产品要求，不是摆设）；
 * 3. 彻底删除**不可恢复**，所以二次确认的按钮写"确认彻底删除"，不用含糊的"确定"。
 */
import { onMounted, ref } from 'vue'

import { apiJson, authFetch } from '../auth'
import { loadTasksAndSync } from '../stores/useLibrary'

const rows = ref([])
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const toast = ref('')
const confirmingId = ref(null)

function messageOf(err, fallback) {
  return err?.message || fallback
}

/** 删除时间：人话（"3 分钟前"这种要另写一套，这里给准确的日期时间）。 */
function fmtDeleted(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await authFetch('/api/tasks?trashed=1')
    if (!res.ok) throw new Error(`回收站加载失败（HTTP ${res.status}）`)
    const data = await res.json()
    rows.value = Array.isArray(data) ? data : []
  } catch (err) {
    error.value = messageOf(err, '回收站加载失败')
    rows.value = []
  } finally {
    loading.value = false
  }
}

async function restore(item) {
  busy.value = true
  error.value = ''
  try {
    await apiJson(`/api/tasks/${item.id}/restore`, { method: 'POST' })
    toast.value = `已恢复「${item.filename}」——它回到「历史记录」里了`
    await load()
    await loadTasksAndSync()
  } catch (err) {
    error.value = `没恢复成（${messageOf(err, '网络或服务异常')}）`
  } finally {
    busy.value = false
  }
}

async function purge(item) {
  busy.value = true
  error.value = ''
  try {
    await apiJson(`/api/tasks/${item.id}/purge`, { method: 'DELETE' })
    confirmingId.value = null
    toast.value = `已彻底删除「${item.filename}」——这一步不可恢复`
    await load()
  } catch (err) {
    error.value = `没删成（${messageOf(err, '网络或服务异常')}）`
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>
