<template>
  <section class="lib-filters" aria-label="知识库筛选">
    <!-- 自跑模式：不登录取数也能看到筛选条 + 「当前筛选」+ 「筛空了给出口」三样。
         ⚠️ 说清"这是示例数据"——示例不标注就成了假数据。 -->
    <HonestNote v-if="showDemo" text="自跑模式：下面用的是组件自带的示例数据（不是你的库）" />

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
      <div v-if="collectionsValue.length" class="lib-fl-row">
        <span class="lib-fl-key">集合</span>
        <div class="lib-fl-chips">
          <button
            v-for="item in collectionsValue"
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

      <!-- ③ 标签：契约 §2.2 的字段是 **`tag[]`（数组）** —— 所以这里是**多选**：
           点一个加一个、再点同一个就取消。请求由页面发（`?tag[]=A&tag[]=B`）。 -->
      <div v-if="tagsValue.length" class="lib-fl-row">
        <span class="lib-fl-key">标签</span>
        <div class="lib-fl-chips">
          <button
            v-for="item in tagsValue"
            :key="`t${item.name}`"
            type="button"
            class="lib-chip"
            :class="{ 'is-on': tagNames.includes(item.name) }"
            :aria-pressed="tagNames.includes(item.name)"
            @click="pickTag(item.name)"
          >
            {{ item.name }}
          </button>
        </div>
      </div>

      <!-- ④ 智能集合：⚠️ 规则是数据、也是它的全部意义 —— 芯片上必须能把规则说出来，
           否则它和一条写死的按钮长得一模一样。键盘用户靠 aria-label 也能听到同一句话。 -->
      <div v-if="smartValue.length" class="lib-fl-row">
        <span class="lib-fl-key">智能集合</span>
        <div class="lib-fl-chips">
          <button
            v-for="item in smartValue"
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
        <button type="button" class="btn lib-fl-clear" @click="applyClear">清除筛选</button>
      </div>
    </div>

    <!-- ⑥ ⭐「有文献，但被筛没了」= 说清是**筛选**造成的 + 给出口。
         用全站统一的 `EmptyState variant="filtered"`（它的默认说明就会说"是筛选造成的"）；
         **绝不说"暂无数据"**——那句话既没说原因、也没给出路。真空态（库里真的没有）归页面。
         ⚠️ 它**落在筛选卡之外**（`.lib-fl-card` 已经闭合）：这一块说的是"列表是空的"，
         塞进筛选卡的边框里会让人以为"是筛选控件自己坏了"。
         ⚠️ 宿主**只给了 `shown` 没给 `total`** 时也照样出这个出口，但说明要诚实：
         那种情况下我们**说不清**是"筛没了"还是"库本来就是空的"。 -->
    <EmptyState
      v-if="filteredEmpty"
      variant="filtered"
      title="这个筛选下没有文献"
      :description="filteredDesc"
      @clear="applyClear"
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
 * 四条纪律：
 * ① **筛选必须能清空**：点当前档即取消、`activeLabels` 一出现就有「清除筛选」出口；
 * ② ⭐ **"筛空了"要分得清是谁造成的**：`total > 0 && shown === 0` 才算筛选造成的空，
 *    这种情况交给统一空态（说原因 + 给出路）；**库里本来就是空的**不许在这里冒充筛空态；
 *    ⚠️ 拿不到 `total` 时**也出出口**，但说明里要写明"说不清是筛没了还是库本来就是空的"；
 * ③ **智能集合的规则必须露出来**（`ruleLabel`）——规则不说出来，它就是一条写死的按钮；
 * ④ **标签是多选**（契约字段是 `tag[]`）：点一个加一个、再点同一个取消，发出去的是数组。
 *
 * ⭐ **自跑模式**（`:demo="true"` 或地址带 `demo=mock`）：不登录取数也能把筛选条、
 * 「当前筛选」、以及**「筛空了给出口」当场看到**——示例库在组件里，点击是真的在筛。
 * 页面把组件摆好之后就不能再"必须接真接口才看得见"了。
 */
import { computed, ref } from 'vue'

import EmptyState from './EmptyState.vue'
import HonestNote from './HonestNote.vue'

const props = defineProps({
  /** 当前筛选值：`{reading_status, collection_id, tag[], smart_id}`（空值 = 没筛）。 */
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
  /** 自跑模式：用组件自带的示例数据渲染（等价于 URL 带 `demo=mock`）。 */
  demo: { type: Boolean, default: false },
})

const emit = defineEmits(['change', 'clear'])

/** URL 里的 `demo=mock`（哈希路由下 query 可能落在 hash 里，两处都看）。 */
function demoFromUrl() {
  if (typeof window === 'undefined' || !window.location) return false
  const target = `${window.location.search || ''}&${window.location.hash || ''}`
  return /(?:^|[?&])demo=mock(?:&|$)/.test(target)
}

const showDemo = computed(() => props.demo || demoFromUrl())

// ============================================================ 自跑模式的示例库

const DEMO_COLLECTIONS = [
  { id: 1, name: '毕业论文', count: 2 },
  { id: 2, name: '文献综述', count: 1 },
  { id: 3, name: '方法对比', count: 1 },
]
const DEMO_TAGS = [{ name: 'RAG' }, { name: '双盲实验' }, { name: '待复现' }]
const DEMO_SMART = [
  {
    id: 1,
    name: '待读',
    query: { all: [{ field: 'reading_status', op: 'eq', value: 'todo' }] },
    count: 2,
  },
  {
    id: 2,
    name: '扫描件',
    query: { all: [{ field: 'text_source', op: 'eq', value: 'ocr' }] },
    count: 1,
  },
]

/** 示例库（4 篇）：自跑模式下**真的筛一遍** —— 这样"筛空了给出口"能当场复现。 */
const DEMO_TASKS = [
  { reading_status: 'todo', collection_id: 1, tags: ['RAG'] },
  { reading_status: 'reading', collection_id: 2, tags: ['双盲实验'] },
  { reading_status: 'done', collection_id: 1, tags: ['RAG', '待复现'] },
  { reading_status: 'todo', collection_id: 3, tags: [] },
]

const DEMO_SMART_RULES = {
  1: (task) => task.reading_status === 'todo',
  2: () => false, // 示例库里没有扫描件 —— 顺手让"筛空了"这条路也能看到
}

const demoFilters = ref({ reading_status: 'todo' })

function demoMatch(task, filters) {
  if (filters.reading_status && task.reading_status !== filters.reading_status) return false
  if (filters.collection_id != null && String(task.collection_id) !== String(filters.collection_id)) return false
  if (filters.smart_id != null) {
    const rule = DEMO_SMART_RULES[filters.smart_id]
    if (!rule || !rule(task)) return false
  }
  const wanted = Array.isArray(filters.tag) ? filters.tag : filters.tag ? [filters.tag] : []
  if (wanted.length && !wanted.every((name) => task.tags.includes(name))) return false
  return true
}

const demoShown = computed(() => DEMO_TASKS.filter((task) => demoMatch(task, demoFilters.value)).length)

// ============================================================ 数据源（真 / 自跑）

const filtersValue = computed(() => (showDemo.value ? demoFilters.value : props.filters || {}))
const collectionsValue = computed(() => (showDemo.value ? DEMO_COLLECTIONS : props.collections))
const tagsValue = computed(() => (showDemo.value ? DEMO_TAGS : props.tags))
const smartValue = computed(() => (showDemo.value ? DEMO_SMART : props.smartCollections))
const totalValue = computed(() => (showDemo.value ? DEMO_TASKS.length : props.total))
const shownValue = computed(() => (showDemo.value ? demoShown.value : props.shown))

/** 状态三档 + "全部"（取值来自契约 §1.1：`todo` / `reading` / `done`）。 */
const STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'todo', label: '待读' },
  { value: 'reading', label: '在读' },
  { value: 'done', label: '已读' },
]

const STATUS_LABEL = Object.fromEntries(STATUS_OPTIONS.map((o) => [o.value, o.label]))

const status = computed(() => filtersValue.value?.reading_status ?? '')
const collectionId = computed(() => filtersValue.value?.collection_id ?? '')
const smartId = computed(() => filtersValue.value?.smart_id ?? '')

/** 标签统一读成**数组**：宿主给数组（契约字段是 `tag[]`）或给单个字符串都收。 */
const tagNames = computed(() => {
  const raw = filtersValue.value?.tag
  const list = Array.isArray(raw) ? raw : raw ? [raw] : []
  return list.filter((item) => item !== '' && item !== null && item !== undefined).map(String)
})

/** 空值一律**从筛选对象里剔掉**：发出的永远是"干净的查询条件"，不是一串空字符串／空数组。 */
function nextFilters(patch) {
  const merged = { ...filtersValue.value, ...patch }
  const out = {}
  for (const [key, value] of Object.entries(merged)) {
    if (Array.isArray(value)) {
      if (value.length) out[key] = value
    } else if (value !== '' && value !== null && value !== undefined) {
      out[key] = value
    }
  }
  return out
}

/** 改动统一从这里出去：自跑模式改本地示例库，正常模式交给页面。 */
function applyChange(next) {
  if (showDemo.value) {
    demoFilters.value = next
    return
  }
  emit('change', next)
}

function applyClear() {
  if (showDemo.value) {
    demoFilters.value = {}
    return
  }
  emit('clear')
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
  applyChange(nextFilters({ reading_status: value }))
}

function pickCollection(id) {
  applyChange(nextFilters({ collection_id: sameId(collectionId.value, id) ? '' : id }))
}

/** 标签多选：在数组里加一个 / 去掉一个（不是"单选换一个"）。 */
function pickTag(name) {
  const next = tagNames.value.includes(name)
    ? tagNames.value.filter((item) => item !== name)
    : [...tagNames.value, name]
  applyChange(nextFilters({ tag: next }))
}

function pickSmart(id) {
  applyChange(nextFilters({ smart_id: sameId(smartId.value, id) ? '' : id }))
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
    const hit = collectionsValue.value.find((item) => sameId(collectionId.value, item.id))
    labels.push(`集合：${hit ? hit.name : collectionId.value}`)
  }
  if (tagNames.value.length) labels.push(`标签：${tagNames.value.join(' / ')}`)
  if (smartId.value !== '') {
    const hit = smartValue.value.find((item) => sameId(smartId.value, item.id))
    labels.push(`智能集合：${hit ? hit.name : smartId.value}`)
  }
  return labels
})

/**
 * ⭐ 有筛选、且当前一篇都没有 → 出统一空态。
 *
 * 两种输入都出：
 * - `total > 0`（知道库里有东西）→ 确定是筛选造成的；
 * - `total` 拿不到（宿主没给）→ **也出**（不然用户面对空列表没有任何出口），
 *   但说明里如实写"说不清是筛没了还是库本来就是空的"。
 * `shown` 拿不到（null）时**不出**：那时连"空"都还不确定，那是页面的事。
 */
const filteredEmpty = computed(
  () =>
    activeLabels.value.length > 0 &&
    shownValue.value === 0 &&
    (totalValue.value === null || totalValue.value > 0),
)

const filteredDesc = computed(() => {
  const who = activeLabels.value.join(' · ')
  if (totalValue.value === null) {
    return `当前筛选（${who}）下没有匹配的文献。库里一共几篇这一项没拿到，所以说不清是「筛没了」还是「库本来就是空的」——先清除筛选看看。`
  }
  return `库里共 ${totalValue.value} 篇，当前筛选（${who}）下没有匹配的文献。`
})
</script>
