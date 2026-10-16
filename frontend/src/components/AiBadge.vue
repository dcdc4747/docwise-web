<template>
  <span class="ai-badge" :title="entry.title">
    <svg class="ic-inl" width="12" height="12" viewBox="0 0 24 24" aria-hidden="true">
      <use :href="ICON" />
    </svg>
    <span class="ai-badge-t">{{ entry.text }}</span>
  </span>
</template>

<script setup>
/**
 * AI 标识 —— 界面上**一律用这一颗芯片**说清"这段内容是 AI 生成的"（合规卡 #147）。
 *
 * 三条纪律：
 * ① ⭐ **口径必须与现实一致**：译文＝**模型翻译**；导读 / 术语 / 问答＝**模型生成**。
 *    **绝不许出现"数据不出本机"**——外文翻译 / 扫描件逐段翻译 / 导读问答三处仍调云端模型 API，
 *    准确口径是「**服务自持 + 文献存本地**」。
 * ② ⭐ **文案只有这一份**：四个位置（译文 / 问答 / 导读 / 术语）都从这里取字。
 *    各页面自己写一句"本内容由 AI 生成"，迟早会漂成好几种说法——那是合规最怕的事。
 * ③ **中性色、不做成警示**：AI 参与不是错误（`--ai-bg` / `--ai-line`），
 *    颜色里不塞情绪，靠**图标 + 位置**表达（与设计规范 §7.5 / §12.2 同一条思路）。
 *
 * ⚠️ **没有人改过的痕迹就不许标"AI 翻译"**：段落精读里被人工改过的译文，
 * 调用方必须**不给这颗芯片**（改过的句子不该被说成模型译的，见 `ReadView.vue` 的 `v-if`）。
 */
import { computed } from 'vue'

const props = defineProps({
  /** 标注的位置：`translate` 译文 · `answer` 问答 · `guide` 导读 · `terms` 术语。 */
  kind: { type: String, default: 'guide' },
})

/** 与全站图标的用法一致：sprite inline 在 `index.html`，这里只引用 symbol id。 */
const ICON = '#i-spark'

/**
 * 四种位置的文案与说明（**唯一真源**）。
 *
 * `title` 里那句"怎么核"是必须的：只写"AI 生成"而不给出核对路径，
 * 用户既不能判断该不该信，也不知道下一步做什么（与诚实提示同一条纪律）。
 */
const ENTRIES = {
  translate: {
    text: 'AI 翻译',
    title: '这一段译文由模型翻译、未经人工校对；点「改译文」改过之后会标「已人工修改」',
  },
  answer: {
    text: 'AI 生成',
    title: '这条回答由模型生成，不是原文摘录；出处已由后端校验，请点开那一句核一遍',
  },
  guide: {
    text: 'AI 生成',
    title: '导读由模型生成，不是原文摘录；每条都带出处，请对着那一句核一遍',
  },
  terms: {
    text: 'AI 生成',
    title: '术语表由模型生成，可能与文献里的用法不一致；命中后会把原文位置回填到按钮上',
  },
}

/** 传了没见过的位置时退回导读那一档（宁可说"AI 生成"，也不渲染一颗没有文案的空壳）。 */
const entry = computed(() => ENTRIES[props.kind] || ENTRIES.guide)
</script>
