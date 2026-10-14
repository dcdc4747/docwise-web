<template>
  <svg class="ic" :width="size" :height="size" aria-hidden="true">
    <use :href="`#i-${name}`" />
  </svg>
</template>

<script setup>
/**
 * 图标包装：sprite（35 个 `<symbol id="i-…">`）已经整段 inline 进 `index.html`，
 * 这里只负责把它按名字摆出来 —— 好处是**名字写在属性里**，改图标只改一个字符串，
 * 不用去模板里抄一段 `<svg>…<use/></svg>`。
 *
 * 用法：`<Icon name="search" />`；要小一号写 `<Icon name="search" class="sm" />`
 * （额外的 class 会经属性透传合并到根 `<svg>` 上，最终是 `class="ic sm"`）。
 *
 * 三条纪律（`03_形态与设计/设计参考/图标集_用法.md` §二）：
 * ① `stroke: currentColor` 由 CSS 统一给，**不许改成固定色**——改了就不能跟随选中态，
 *    等于退回 emoji 的老问题；
 * ② `display: block` 由 CSS 给（svg 默认 inline 会吃到行高，上下不匀）；
 * ③ 图标与文字的间距走容器的 flex + gap，不用 margin。
 */
defineProps({
  /** 图标名（去掉 `i-` 前缀）：`search` / `download` / `more` … 见图标集 35 个 id */
  name: { type: String, required: true },
  /** 边长（px）。默认 20 = 基准 `.ic`；按钮内一般改用 class="sm"（16） */
  size: { type: [Number, String], default: 20 },
})
</script>
