<template>
  <footer class="lib-ov">
    <!-- 自跑模式：不登录取数也能看到"概况带文字明细 + 标签云"。
         ⚠️ 说清这是示例数据。 -->
    <HonestNote v-if="showDemo" text="自跑模式：下面是组件自带的示例数据（不是你的库）" />

    <!-- ⭐ 概况的**全部信息都在文字里**：`N 篇文献 · M 块 · X 条素材 · Y 条引用`。
         如果以后要加分类条形图，也必须**带着这行文字明细**（只有色块等于什么都没说）。 -->
    <p v-if="statsValue" class="lib-ov-line">{{ line }}</p>
    <!-- 数据没就位就如实说，**不摆一排 0 冒充"统计好了"** -->
    <HonestNote v-else text="概况暂未接入（等基线 GET /api/tasks 带上计数）" />

    <!-- 标签云：拿不到标签就整块不渲染，不摆一个空壳 -->
    <ul v-if="tagList.length" class="lib-cloud" aria-label="标签云">
      <li v-for="item in tagList" :key="item.name">
        <button
          type="button"
          class="lib-tag"
          :aria-label="`按标签「${item.name}」筛选（${item.count} 篇）`"
          @click="emit('pick-tag', item.name)"
        >
          {{ item.name }}<span class="lib-tag-n">{{ item.count }}</span>
        </button>
      </li>
    </ul>
  </footer>
</template>

<script setup>
/**
 * 知识库概况底行（issue #111 / 任务卡：卡③）。
 *
 * 只做两件事：**把库里的家底用文字说清**（篇 / 块 / 素材 / 引用）+ **标签云**。
 *
 * 三条纪律：
 * ① ⚠️ **不许只有色块**：概况行必须是可读的文字明细（"分类条形图必须带文字明细"）；
 * ② **数据没就位就如实说**：`stats` 没给 → 走统一诚实形态 `HonestNote`，
 *    **不许摆一排 0** —— 一排 0 会被当成"这个库是空的"，那是另一件事（也是假的）；
 * ③ ⭐ **自跑模式**（`:demo="true"` 或地址带 `demo=mock`）：不登录取数也能看到这一行，
 *    但**必须标明是示例数据**（示例不标注就成了假数据）。
 *
 * 数从哪来：**同一次** `GET /api/tasks`（N8 追加参数）的响应，不新造端点；标签可点 → `pick-tag`。
 */
import { computed } from 'vue'

import HonestNote from './HonestNote.vue'

const props = defineProps({
  /** `{tasks, blocks, materials, citations}`；整块没给 = 数据未就位（诚实档）。 */
  stats: { type: Object, default: null },
  /** `[{name, count}]`。 */
  tags: { type: Array, default: () => [] },
  /** 自跑模式：用组件自带的示例数据渲染（等价于 URL 带 `demo=mock`）。 */
  demo: { type: Boolean, default: false },
})

const emit = defineEmits(['pick-tag'])

/** URL 里的 `demo=mock`（哈希路由下 query 可能落在 hash 里，两处都看）。 */
function demoFromUrl() {
  if (typeof window === 'undefined' || !window.location) return false
  const target = `${window.location.search || ''}&${window.location.hash || ''}`
  return /(?:^|[?&])demo=mock(?:&|$)/.test(target)
}

const showDemo = computed(() => props.demo || demoFromUrl())

/** 示例家底（数字都是**示例**，界面上已标明）。 */
const DEMO_STATS = { tasks: 5, blocks: 412, materials: 9, citations: 3 }
const DEMO_TAGS = [
  { name: 'RAG', count: 3 },
  { name: '双盲实验', count: 2 },
  { name: '待复现', count: 1 },
]

const statsValue = computed(() => (showDemo.value ? DEMO_STATS : props.stats))
const tagsValue = computed(() => (showDemo.value ? DEMO_TAGS : props.tags))

/** 缺哪个数就按 0 计（后端字段没给不等于"说了没有"），但**整块缺失**走诚实档。 */
function count(value) {
  return Number.isFinite(value) ? value : 0
}

const line = computed(
  () =>
    `${count(statsValue.value?.tasks)} 篇文献 · ${count(statsValue.value?.blocks)} 块 · ` +
    `${count(statsValue.value?.materials)} 条素材 · ${count(statsValue.value?.citations)} 条引用`,
)

/** 没有名字的标签不渲染（不许出现一个空标签按钮）。 */
const tagList = computed(() =>
  tagsValue.value
    .filter((item) => item && item.name)
    .map((item) => ({ name: String(item.name), count: count(item.count) })),
)
</script>
