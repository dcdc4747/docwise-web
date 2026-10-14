<template>
  <!-- ⭐ 多个出处 = 同一个容器里纵向排列，**不另造第二个形态**（R2 专门堵过这条路：
       实现者最容易在"两个出处挤在一起"时发明一个新形态）。"挤"就换行、就长高，不改形状。 -->
  <div class="cite-stack">
    <button
      v-for="(chip, index) in chips"
      :key="index"
      type="button"
      class="cite-chip"
      :aria-label="locateLabel(chip)"
      @click="emit('locate', chip.cite)"
    >
      <span class="cite-src">{{ chip.source }}</span>
      <!-- 页码取不到时**整段不渲染**：宁可少一段，也不编一个页码出来 -->
      <span v-if="chip.page" class="cite-page">· 第 {{ chip.page }} 页</span>
      <span v-if="chip.quote" class="cite-quote">·「{{ chip.quote }}」</span>
    </button>
  </div>
</template>

<script setup>
/**
 * 出处芯片 —— **全站唯一的"出处"视觉形态**。
 *
 * 输入是**服务端的快照字段**（素材卡/引用的 `{source_name, page, quote, block_id?, task_id?}`），
 * 组件自己不拼、不猜、不补：少一个字段就少渲染一段，不伪造坐标。
 *
 * 三条纪律写在这个文件里（改之前先看 issue #87）：
 * ① **内容顺序固定**：`来源名 · 第 X 页 ·「原句开头…」`；
 * ② ⚠️ **不许说"第 Y 段"** —— 段号在没见过的期刊上只有五六成准，**不准的段号比没有更糟**，
 *    所以这里**只有页码，没有段号**（`page` 字段，不读 `block_id` 来当段号）；
 * ③ **整块可点、可聚焦** —— 用真 `<button>`（原生键盘可达 + `:focus-visible` 焦点态），
 *    点下去只 `emit('locate')`：**滚动与高亮由页面那边的现有 `traceTo` 做**（1.6s 高亮），
 *    组件里不许自己碰 DOM 位置、也不许自己滚。
 *
 * ⚠️ 原句只取**开头**（默认 24 字）并以 `…` 收尾：芯片是"一眼认领是哪句"，不是摘录全文。
 */
import { computed } from 'vue'

const props = defineProps({
  /**
   * 单个出处对象 `{source_name, page, quote, block_id?, task_id?}`，
   * 或它的数组（数组 = 一条结论命中多处 → 纵向排列多个芯片）。
   */
  cites: { type: [Object, Array], required: true },
  /** 原句取多少字（超出加 `…`）。 */
  quoteHead: { type: Number, default: 24 },
})

const emit = defineEmits(['locate'])

function toList(value) {
  if (Array.isArray(value)) return value
  return value ? [value] : []
}

/** 页码：数字/数字字符串都收，空值返回 ''（`0` 页不存在，也算空）。 */
function pageText(cite) {
  const page = cite.page
  if (page === null || page === undefined || page === '') return ''
  const text = String(page).trim()
  return text === '0' ? '' : text
}

/** 原句开头：压平空白 → 截断 → 加省略号（不截断就不加，别为了好看硬加）。 */
function headQuote(quote) {
  const text = String(quote ?? '').replace(/\s+/g, ' ').trim()
  if (!text) return ''
  return text.length > props.quoteHead ? `${text.slice(0, props.quoteHead)}…` : text
}

const chips = computed(() =>
  toList(props.cites)
    .filter((cite) => cite && cite.source_name)
    .map((cite) => ({
      cite,
      source: String(cite.source_name),
      page: pageText(cite),
      quote: headQuote(cite.quote),
    })),
)

/** 读屏用户听到的是"这是出处、点它能去哪儿"，不是把视觉顺序再念一遍。 */
function locateLabel(chip) {
  const parts = [chip.source]
  if (chip.page) parts.push(`第 ${chip.page} 页`)
  if (chip.quote) parts.push(`「${chip.quote}」`)
  return `出处：${parts.join(' ')}，跳到原文并高亮`
}
</script>
