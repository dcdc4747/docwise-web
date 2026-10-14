<template>
  <p class="hnote">
    <!-- 图标是"信息"语义（不是警告）：形状承担语义，颜色里不塞情绪。
         sprite 由图标包（issue #88）inline 进 index.html；宽高属性只是它落地前的兜底，
         F2 的 `svg.ic-inl` 一进 CSS 就会盖掉（CSS 优先于表现属性）。 -->
    <svg class="ic-inl" width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
      <use :href="icon" />
    </svg>
    <span class="hnote-text">{{ text }}</span>
  </p>
</template>

<script setup>
/**
 * 诚实提示 —— 本产品特有的一类元素：**把"我们不知道"说出来，但不做成报错的样子**。
 *
 * 三条纪律：
 * ① **中性灰**（`--unknown`）——**不是红、也不是黄**：它是"这件事我们说不准"，
 *    不是一个错误，也不是一个警告。做成警示色会让用户以为自己做错了什么。
 * ② ⚠️ **文案必须说"为什么"**：✅「无法判断（稿件未含版式信息）」❌「无法判断」。
 *    只说结论不说原因的"诚实"，用户既不能判断该不该信，也不知道下一步做什么。
 *    开发环境里对着那句光秃秃的"无法判断"会 `console.warn`，把这条纪律顶到人眼前。
 * ③ 一行文字 + 一个图标，**不占卡片、不带边框、不弹层**（它要能贴着结论常驻）。
 */
import { watchEffect } from 'vue'

const props = defineProps({
  /** ⚠️ 必须带原因，见纪律 ②。 */
  text: { type: String, required: true },
  /** sprite symbol id（默认信息图标）。 */
  icon: { type: String, default: '#i-info' },
})

/** 光秃秃的"无法判断"就是这条纪律的反面教材，开发时直接喊出来。 */
const BARE_UNKNOWN = /^无法判断[。.!！]?$/

watchEffect(() => {
  if (import.meta.env.DEV && BARE_UNKNOWN.test(props.text.trim())) {
    console.warn('[HonestNote] 诚实提示必须说"为什么"：把「无法判断」补成「无法判断（…原因…）」。')
  }
})
</script>
