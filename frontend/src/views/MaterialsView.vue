<template>
  <!-- 「素材库」一屏（E2 · 契约 N13）。
       这一屏存在的理由：素材卡**已经能存**（三处入口），但除了起草页左栏没有地方能**按集合/标签找**——
       聚合了却查不了，等于资产只剩一半。
       ⚠️ 三条口径：筛选靠后端（N13 的 `?collection_id?`/`&tag?`，按**源文献**所属筛，前端不重算）；
       空态分"真空"与"筛空"两种；出错**如实说、不拿假数据顶**。 -->
  <section class="mats">
    <header class="mats-top">
      <div>
        <h1 class="mats-t">素材库</h1>
        <p class="mats-sub">
          从文献里存下来的段落。按集合 / 标签筛——筛的是**这些素材的源文献**属于哪个集合、打了什么标签。
        </p>
      </div>
      <div class="mats-ops">
        <span class="mats-count">{{ countsText(items.length, { hasFilters }) }}</span>
        <button type="button" class="btn ghost sm mats-reload" @click="load">刷新</button>
      </div>
    </header>

    <div class="mats-filters">
      <label class="mats-field">
        <span>集合</span>
        <select v-model="collectionId" class="mats-select mats-collection" @change="load">
          <option value="">全部集合</option>
          <option v-for="c in collections" :key="c.id" :value="String(c.id)">
            {{ c.name }}（{{ c.doc_count }}）
          </option>
        </select>
      </label>
      <label class="mats-field">
        <span>标签</span>
        <select v-model="tag" class="mats-select mats-tag" @change="load">
          <option value="">全部标签</option>
          <option v-for="t in tags" :key="t.id" :value="t.name">
            {{ t.name }}（{{ t.doc_count }}）
          </option>
        </select>
      </label>
      <button
        v-if="hasFilters"
        type="button"
        class="btn ghost sm mats-clear"
        @click="clearFilters"
      >
        清空筛选
      </button>
      <span class="mats-current">{{ filtersText({ collectionName, tag }) }}</span>
    </div>

    <!-- 筛选项取不到：不影响看素材，但**要说清为什么下拉是空的**（不假装"你还没有集合"） -->
    <HonestNote v-if="filtersNote" class="mats-filters-note" :text="filtersNote" />
    <HonestNote v-if="materialsError" class="mats-error" :text="materialsError" />

    <p v-if="loading" class="mats-loading">正在读素材卡…</p>

    <p v-else-if="!items.length" class="mats-empty">{{ emptyText({ hasFilters }) }}</p>

    <ul v-else class="mats-grid">
      <li v-for="m in items" :key="m.id" class="mats-cell">
        <MaterialCard :material="m" @locate="locate(m)" />
      </li>
    </ul>
  </section>
</template>

<script setup>
/**
 * 「素材库」一屏（E2）。
 *
 * 三条口径（都有用例盯着）：
 * 1. ⭐ **筛选走后端**：`?collection_id?` / `&tag?` 是 N13 的契约参数，筛的是**源文献**所属；
 *    **不在前端过滤**——前端再筛一遍会与后端口径（`task_id` 为 null 的卡不属于任何集合）
 *    悄悄不一致。筛选变化 = 重新请求。
 * 2. ⭐ **点出处复用 `useWrite.jumpToMaterial`**：滚到原文 + 高亮那一句是阅读区 `traceTo` 的活，
 *    这里**不另写一套定位**（契约 §2.7）；素材缺 `block_id` 时它自己会如实说"只打开文献"。
 * 3. ⭐ **空态两种、错误如实**：筛空给出口，真空给"怎么产生第一条"；接口失败照实说。
 */
import { computed, onMounted, ref } from 'vue'

import { apiJson } from '../auth'
import HonestNote from '../components/HonestNote.vue'
import MaterialCard from '../components/MaterialCard.vue'
import {
  collectionNameOf,
  countsText,
  emptyText,
  filtersText,
} from '../materialsText'
import { loadMaterials, materials, materialsError, materialsLoading } from '../stores/useMaterials'
import { jumpToMaterial } from '../stores/useWrite'

const collectionId = ref('')
const tag = ref('')
const collections = ref([])
const tags = ref([])
const filtersNote = ref('')

const items = computed(() => materials.value)
const loading = computed(() => materialsLoading.value)
const hasFilters = computed(() => Boolean(collectionId.value || tag.value))
const collectionName = computed(() => collectionNameOf(collections.value, collectionId.value))

async function load() {
  await loadMaterials({
    collectionId: collectionId.value || undefined,
    tag: tag.value || undefined,
  })
}

/** 筛选项：取不到就**如实说明下拉为什么是空的**，不阻断素材列表。 */
async function loadFilterOptions() {
  filtersNote.value = ''
  const failures = []
  const [c, t] = await Promise.allSettled([apiJson('/api/collections'), apiJson('/api/tags')])
  if (c.status === 'fulfilled') {
    collections.value = Array.isArray(c.value?.items) ? c.value.items : []
  } else {
    collections.value = []
    failures.push('集合')
  }
  if (t.status === 'fulfilled') {
    tags.value = Array.isArray(t.value?.items) ? t.value.items : []
  } else {
    tags.value = []
    failures.push('标签')
  }
  if (failures.length) {
    filtersNote.value = `${failures.join(' / ')}列表暂时取不到——下拉里只有「全部」，素材卡本身照常可看。`
  }
}

function clearFilters() {
  collectionId.value = ''
  tag.value = ''
  load()
}

/** 点出处：交给 `useWrite.jumpToMaterial`（它会存稿、打开文献、滚到那一段并高亮）。 */
function locate(material) {
  jumpToMaterial(material)
}

onMounted(async () => {
  // 两件事互不依赖：筛选项挂了也要能看素材
  await Promise.all([loadFilterOptions(), load()])
})
</script>
