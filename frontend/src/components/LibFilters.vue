<template>
  <section class="lib-filters" aria-label="知识库筛选">
    <div class="lib-fl-card">
      <!-- ① 状态（读没读）：四档单选，点当前档 = 取消这一档（这也是"筛选能清空"的一种） -->
      <div class="lib-fl-row">
        <span class="lib-fl-key">状态</span>
        <div class="lib-fl-chips">
          <button
            v-for="option in STATUS_OPTIONS"
            :key="option.value || 'all'"
            type="button"
            class="lib-chip"
            :class="{ 'is-on': status === option.value }"
            :aria-pressed="status === option.value"
            @click="pickStatus(option.value)"
          >
            {{ option.label }}
          </button>
        </div>
      </div>

      <!-- ② 集合（可嵌套的树由页面摆，这里只出"筛哪一档"） -->
      <div v-if="collections.length" class="lib-fl-row">
        <span class="lib-fl-key">集合</span>
        <div class="lib-fl-chips">
          <button
            v-for="item in collections"
            :key="`c${item.id}`"
            type="button"
            class="lib-chip"
            :class="{ 'is-on': sameId(collectionId, item.id) }"
            :aria-pressed="sameId(collectionId, item.id)"
            @click="pickCollection(item.id)"
          >
            {{ item.name }}<span v-if="hasCount(item.count)" class="lib-chip-n">{{ item.count }}</span>
          </button>
        </div>
      </div>

      <!-- ③ 标签：字段是 `tag[]`，这里一次筛一个；再点同一个就是取消 -->
      <div v-if="tags.length" class="lib-fl-row">
        <span class="lib-fl-key">标签</span>
        <div class="lib-fl-chips">
          <button
            v-for="item in tags"
            :key="`t${item.name}`"
            type="button"
            class="lib-chip"
            :class="{ 'is-on': tag === item.name }"
            :aria-pressed="tag === item.name"
            @click="pickTag(item.name)"
          >
            {{ item.name }}
          </button>
        </div>
      </div>

      <!-- ④ 智能集合：⚠️ 规则是数据、也是它的全部意义 —— 芯片上必须能把规则说出来，
           否则它和一条写死的按钮长得一模一样。键盘用户靠 aria-label 也能听到同一句话。 -->
      <div v-if="smartCollections.length" class="lib-fl-row">
        <span class="lib-fl-key">智能集合</span>
        <div class="lib-fl-chips">
          <button
            v-for="item in smartCollections"
            :key="`s${item.id}`"
            type="button"
            class="lib-chip"
            :class="{ 'is-on': sameId(smartId, item.id) }"
            :aria-pressed="sameId(smartId, item.id)"
            :aria-label="`${item.name}（${ruleLabel(item.query)}）`"
            :title="ruleLabel(item.query)"
            @click="pickSmart(item.id)"
          >
            {{ item.name }}<span v-if="hasCount(item.count)" class="lib-chip-n">{{ item.count }}</span>
          </button>
        </div>
      </div>

      <!-- ⑤ 当前筛选 + 唯一出口：说清"现在筛的是什么"，且随时能清掉 -->
      <div v-if="activeLabels.length" class="lib-fl-row lib-fl-active">
        <span class="lib-fl-key">当前</span>
        <span class="lib-fl-sum">{{ activeLabels.join(' · ') }}</span>
        <button type="button" class="btn lib-fl-clear" @click="emit('clear')">清除筛选</button>
      </div>
    </div>

    <!-- ⑥ ⭐「有文献，但被筛没了」= 说清是**筛选**造成的 + 给出口。
         用全站统一的 `EmptyState variant="filtered"`（它的默认说明就会说"是筛选造成的"）；
         **绝不说"暂无数据"**——那句话既没说原因、也没给出路。真空态（库里真的没有）归页面。
         ⚠️ 它**落在筛选卡之外**（`.lib-fl-card` 已经闭合）：这一块说的是"列表是空的"，
         塞进筛选卡的边框里会让人以为"是筛选控件自己坏了"。 -->
    <EmptyState
      v-if="filteredEmpty"
      variant="filtered"
      title="这个筛选下没有文献"
      :description="filteredDesc"
      @clear="emit('clear')"
    />
  </section>
</template>

<script setup>
/**
 * 知识库筛选区 —— 筛选 / 标签条（issue #111 / 任务卡：卡③）。
 *
 * ⭐ **本组件只出"筛选条"，自己不取数、不管列表**：
 * 数据源是基线 `GET /api/tasks` + 契约 §2.2 的 N8 追加参数
 * （`?reading_status?` `&collection_id?` `&tag[]?` `&smart_id?`），**发起请求与摆页面是外壳负责人的活**。
 * 筛选状态按卡里的允许项走 **props + 回调**（不进 `stores/`）：
 * `filters` 进、`change` / `clear` 出 —— 这样它不依赖后端有没有写好、也不需要自己编假数据。
 *
 * 三条纪律：
 * ① **筛选必须能清空**：点当前档即取消、`activeLabels` 一出现就有「清除筛选」出口；
 * ② ⭐ **"筛空了"要分得清是谁造成的**：`total > 0 && shown === 0` 才算筛选造成的空，
 *    这种情况交给统一空态（说原因 + 给出路）；**库里本来就是空的**不许在这里冒充筛空态；
 * ③ **智能集合的规则必须露出来**（`ruleLabel`）——规则不说出来，它就是一条写死的按钮。
 */
import { computed } from 'vue'

import EmptyState from './EmptyState.vue'

const props = defineProps({
  /** 当前筛选值：`{reading_status, collection_id, tag, smart_id}`（空值 = 没筛）。 */
  filters: { type: Object, default: () => ({}) },
  /** 可选集合：`[{id, name, count}]`（count 可缺）。 */
  collections: { type: Array, default: () => [] },
  /** 可选标签：`[{name}]`。 */
  tags: { type: Array, default: () => [] },
  /** 可选智能集合：`[{id, name, query, count}]`（`query` 是"规则即数据"）。 */
  smartCollections: { type: Array, default: () => [] },
  /** 库里一共几篇（**用来判断"空"是不是筛选造成的**）。拿不到就给 null。 */
  total: { type: Number, default: null },
  /** 当前筛选下有几篇。拿不到就给 null。 */
  shown: { type: Number, default: null },
})

const emit = defineEmits(['change', 'clear'])

/** 状态三档 + "全部"（取值来自契约 §1.1：`todo` / `reading` / `done`）。 */
const STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'todo', label: '待读' },
  { value: 'reading', label: '在读' },
  { value: 'done', label: '已读' },
]

const STATUS_LABEL = Object.fromEntries(STATUS_OPTIONS.map((o) => [o.value, o.label]))

const status = computed(() => props.filters?.reading_status ?? '')
const collectionId = computed(() => props.filters?.collection_id ?? '')
const tag = computed(() => props.filters?.tag ?? '')
const smartId = computed(() => props.filters?.smart_id ?? '')

/** 空值一律**从筛选对象里剔掉**：发出的永远是"干净的查询条件"，不是一串空字符串。 */
function nextFilters(patch) {
  const merged = { ...props.filters, ...patch }
  const out = {}
  for (const [key, value] of Object.entries(merged)) {
    if (value !== '' && value !== null && value !== undefined) out[key] = value
  }
  return out
}

function sameId(current, candidate) {
  // 后端给的是数字，URL / 手写配置里可能是字符串，两边都收
  if (current === '' || current === null || current === undefined) return false
  return String(current) === String(candidate)
}

function hasCount(value) {
  return Number.isFinite(value)
}

function pickStatus(value) {
  emit('change', nextFilters({ reading_status: value }))
}

function pickCollection(id) {
  emit('change', nextFilters({ collection_id: sameId(collectionId.value, id) ? '' : id }))
}

function pickTag(name) {
  emit('change', nextFilters({ tag: tag.value === name ? '' : name }))
}

function pickSmart(id) {
  emit('change', nextFilters({ smart_id: sameId(smartId.value, id) ? '' : id }))
}

/** 规则 → 人话（"规则即数据"：`query.all` 里每条的 field/op/value）。 */
const FIELD_LABEL = {
  reading_status: '状态',
  tag: '标签',
  collection: '集合',
  native: '中文文献',
  text_source: '取字方式',
}
const OP_LABEL = { eq: '=', in: '属于', not_in: '不属于' }
const VALUE_LABEL = { todo: '待读', reading: '在读', done: '已读', ocr: 'OCR', text: '文字层' }

function ruleLabel(query) {
  const parts = query?.all
  if (!Array.isArray(parts) || parts.length === 0) return '规则未给出'
  return `规则：${parts
    .map((part) => {
      const field = FIELD_LABEL[part?.field] || String(part?.field ?? '?')
      const op = OP_LABEL[part?.op] || String(part?.op ?? '?')
      const raw = Array.isArray(part?.value) ? part.value.join(' / ') : part?.value
      const value = VALUE_LABEL[raw] || String(raw ?? '?')
      return `${field} ${op} ${value}`
    })
    .join('，')}`
}

/** 当前筛了哪几样（人能读的一句话，不是把参数名念一遍）。 */
const activeLabels = computed(() => {
  const labels = []
  if (status.value) labels.push(`状态：${STATUS_LABEL[status.value] || status.value}`)
  if (collectionId.value !== '') {
    const hit = props.collections.find((item) => sameId(collectionId.value, item.id))
    labels.push(`集合：${hit ? hit.name : collectionId.value}`)
  }
  if (tag.value) labels.push(`标签：${tag.value}`)
  if (smartId.value !== '') {
    const hit = props.smartCollections.find((item) => sameId(smartId.value, item.id))
    labels.push(`智能集合：${hit ? hit.name : smartId.value}`)
  }
  return labels
})

/** ⭐ 只有"库里有东西 + 现在筛没了"才算筛选造成的空。 */
const filteredEmpty = computed(
  () => activeLabels.value.length > 0 && props.total !== null && props.shown === 0 && props.total > 0,
)

const filteredDesc = computed(
  () => `库里共 ${props.total} 篇，当前筛选（${activeLabels.value.join(' · ')}）下没有匹配的文献。`,
)
</script>
