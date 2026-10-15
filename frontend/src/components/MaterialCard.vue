<template>
  <!-- 自跑模式：不登录取数也能把三种状态看全（`:demo="true"` 或 URL 带 `demo=mock`）。
       组件不许变成"必须接真接口才看得见"的东西 —— 那样样式评审与截图验收都没法做。 -->
  <div v-if="showDemo" class="mat-demo">
    <MaterialCard v-for="sample in DEMO_MATERIALS" :key="sample.id" :material="sample" />
  </div>

  <article v-else-if="material" class="mat-card" :class="stateClass">
    <!-- 软删态：状态钉在最上面一行，一眼可辨（不隐藏 —— 7 天撤销窗口要靠它） -->
    <p v-if="isDeleted" class="mat-badge">已删除 · 7 天内可撤销</p>

    <p class="mat-quote">{{ quoteText }}</p>
    <!-- 中文文献没有译文：`translated_quote` 为 null 就整行不渲染（不写"暂无译文"这种噪音） -->
    <p v-if="translatedText" class="mat-trans">{{ translatedText }}</p>
    <p v-if="noteText" class="mat-note">备注：{{ noteText }}</p>

    <!-- ⭐ 出处只有一种形态：`CiteChip`（全站唯一，不另造一套）。
         能回跳时它是活链接；`task_id` 为 null（源文献已删）时整块 `inert`——
         置灰、不可点、键盘也进不去：**死链不许做成活链样式**。 -->
    <div v-if="canJump" class="mat-cite">
      <CiteChip :cites="cite" @locate="emit('locate', material)" />
    </div>
    <div v-else class="mat-cite mat-frozen" inert>
      <CiteChip :cites="cite" />
    </div>

    <HonestNote
      v-if="isOrphan"
      text="源文献已删除，仅存快照（出处与页码是创建时深拷贝的，引用照常成立）"
    />

    <div v-if="isDeleted" class="mat-ops">
      <button type="button" class="btn mat-restore" @click="emit('restore', material)">
        撤销删除
      </button>
    </div>
  </article>
</template>

<script setup>
/**
 * 素材卡 —— M2 的"证据快照"卡片（issue #110 / 任务卡：卡②）。
 *
 * 交付物是**一个组件**，不是素材库页：页面装配（"素材从哪来"）归外壳负责人。
 *
 * 三条不能改的东西：
 * ① ⚠️ **快照就是快照**：`text_quote` / `translated_quote` / `page` / `source_name` 全是
 *    创建时深拷贝进 `Material` 的（契约 §2.4）。组件**只显示服务端给的值，不自己拼、不 JOIN
 *    `tasks` 拿名字** —— 那样"删掉源任务后素材卡仍显示出处"这条 M2 判据当场失效。
 * ② ⚠️ **三个状态必须一眼可辨**：正常 / **源文献已删（`task_id` 为 null）** / 软删（`deleted_at` 非空）。
 *    中间那一态是本卡的原始判据，用的是统一形态 `HonestNote`（中性灰，不是红黄）。
 * ③ ⚠️ **卡片本身不是按钮**：整卡做 `<button>` 会与里面的 `CiteChip`（真 `<button>`）
 *    套成非法嵌套、读屏也念不清。所以根是 `<article>`，**可交互的只有两个原生 `<button>`**：
 *    出处芯片（回跳）与撤销删除 —— 键盘可达、`div + @click` 一个都不用。
 *
 * 出处口径照全站硬约定：**只说「第 X 页 ·「这一句的开头…」」，永远不说"第 Y 段"**
 * （`CiteChip` 已经钉住，本组件不碰页码、不补段号）。
 */
import { computed } from 'vue'

import CiteChip from './CiteChip.vue'
import HonestNote from './HonestNote.vue'

const props = defineProps({
  /** 契约 §2.4 的 `Material` 对象（**服务端快照**）。自跑模式下可不传。 */
  material: { type: Object, default: null },
  /** 自跑模式：渲染三种状态的示例数据（等价于 URL 带 `demo=mock`）。 */
  demo: { type: Boolean, default: false },
})

/** `locate` 带出**整份 material**（页面拿 `task_id` + `block_id` + `text_quote` 去走现有 `traceTo`）；
 *  `restore` 是软删态的"撤销删除"，真正的撤销请求归素材库页发。 */
const emit = defineEmits(['locate', 'restore'])

/** URL 里的 `demo=mock`（哈希路由下 query 可能落在 hash 里，两处都看）。 */
function demoFromUrl() {
  if (typeof window === 'undefined' || !window.location) return false
  const target = `${window.location.search || ''}&${window.location.hash || ''}`
  return /(?:^|[?&])demo=mock(?:&|$)/.test(target)
}

const showDemo = computed(() => props.demo || demoFromUrl())

/** 空白压平：PDF 块里带换行，卡片上按一行文字摆（不做 `pre-wrap`，免得行距被原稿带跑）。 */
function flat(value) {
  return String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim()
}

const quoteText = computed(() => flat(props.material?.text_quote))
const translatedText = computed(() => flat(props.material?.translated_quote))
const noteText = computed(() => flat(props.material?.note))

/** 软删（`deleted_at` 非空）：还在，但已不在正常列表里。 */
const isDeleted = computed(() => Boolean(props.material?.deleted_at))
/** ⭐ 源文献已删（`task_id` 为 null）且自己没被软删 —— M2 判据的那一态。 */
const isOrphan = computed(() => !isDeleted.value && props.material?.task_id == null)
/** 只有拿得到 `task_id` 才谈得上"回跳原文"；否则不装成活链。 */
const canJump = computed(() => props.material?.task_id != null)

const stateClass = computed(() => ({
  'is-orphan': isOrphan.value,
  'is-deleted': isDeleted.value,
}))

/** 出处芯片的输入：**只搬快照字段**，一个都不补。 */
const cite = computed(() => ({
  source_name: props.material?.source_name,
  page: props.material?.page,
  quote: props.material?.text_quote,
  block_id: props.material?.block_id,
  task_id: props.material?.task_id,
}))

/** 三种状态的示例（形状与 `frontend/src/mock/contract.js` 的 `materials` 一致）。 */
const DEMO_MATERIALS = [
  {
    id: 1,
    text_quote: '（示例）读者信任一个答案，取决于能否跳回它出处的那句话。',
    translated_quote: 'Readers trust an answer when they can jump back to the sentence it came from.',
    page: 3,
    source_name: '示例文献.pdf',
    note: '选题依据',
    task_id: 42,
    block_id: 'p2_b7',
    deleted_at: null,
    created_at: '2026-10-15T02:00:00+00:00',
  },
  {
    id: 2,
    text_quote: '（示例）这条素材卡的源文献已被删除，只剩快照。',
    translated_quote: null,
    page: 11,
    source_name: '已删除的文献.pdf',
    note: null,
    task_id: null,
    block_id: null,
    deleted_at: null,
    created_at: '2026-10-15T02:00:00+00:00',
  },
  {
    id: 3,
    text_quote: '（示例）我删掉的这条还在 7 天撤销窗口里。',
    translated_quote: null,
    page: 5,
    source_name: '示例文献.pdf',
    note: null,
    task_id: 42,
    block_id: 'p4_b2',
    deleted_at: '2026-10-15T03:00:00+00:00',
    created_at: '2026-10-15T02:00:00+00:00',
  },
]
</script>
