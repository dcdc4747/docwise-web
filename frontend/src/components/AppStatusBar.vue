<script setup>
/**
 * 底部状态条（**挂载点已就位，内容由 R8 填**）。
 *
 * ⚠️ **这个文件现在是"座位"不是"功能"**：形态 v2 §1.2 底部那条「数据流向 / 本次用了哪个模型 /
 * 待处理 N 处」是 **R8** 的活，而 R8 依赖后端 **B2**（`memory_events` 表 + `GET /api/memory-events`）
 * —— **那一层现在还没做**（后端实测没有这张表、也没有这个端点）。
 *
 * 所以本卡（issue #86 第 7 步）只做一件事：**把挂载点钉在 `App.vue` 里**，
 * 这样 R8 之后**只改自己这个文件，不用再碰外壳**。
 *
 * ⭐ **自门控 + 诚实档**：`slots` 里一个信息位都没有就整条不渲染 —— **不占屏幕、不写假数据**。
 * 两件事都写进契约，所以这里不是"顺手加的开关"：
 * - R8 卡判据③：「取不到数据时**显示"暂未接入"**（诚实档）」——**不许写死"本次用了某模型"这类假数据**；
 * - R8 卡不许做第②条：「不许写死"本次用了某模型"这类假数据（**模型名从 `memory_events.tool` 来**）」。
 *
 * 形状按 R8 卡判据①钉死三个信息位（`flow` 数据流向 / `model` 本次模型 / `todo` 待处理 N 处）。
 * 真正填内容时还要满足两条本卡**没做**的判据（照卡原文）：
 * - 判据②：`● 不出本机` 与 `▲ 正文发往模型 API` 的**图标形状不同**、文字都走 `--ink`（**色盲安全**）；
 * - 不许做第①条：**不许把警示做成高饱和文字色**（琥珀字看三天就习惯，图标 + 位置更持久）。
 * ⚠️ 口径：**不能说"数据不出本机"** —— 外文翻译 / 扫描件逐段翻译 / 导读问答三处仍调云端模型 API，
 * 准确说法是「**服务自持 + 文献存本地**」。
 */

import Icon from './Icon.vue'

/** 三个信息位的固定顺序（R8 卡判据①：数据流向 / 本次用的模型 / 待处理 N 处）。 */
const SLOT_KEYS = ['flow', 'model', 'todo']

const props = defineProps({
  /**
   * 三个信息位（R8 从 N17 算好传进来）。
   * 形状：`{ flow: {icon, text}, model: {icon, text}, todo: {icon, text} }`
   * —— 取不到的位**不要编**：整条按空处理（自门控），或按 R8 判据③ 写「暂未接入」。
   * `icon` 是 sprite 名（走 `Icon.vue`）——**形状要不同**（色盲安全），别给三个位同一颗图标。
   */
  slots: { type: Object, default: () => ({}) },
})

defineEmits(['select'])

/** 只保留真的有文字的信息位 —— 信息位缺一个就少显示一个，不补空壳。 */
const items = SLOT_KEYS.map((key) => ({ key, ...(props.slots?.[key] || {}) })).filter(
  (item) => Boolean(item.text),
)
</script>

<template>
  <!-- 自门控：三个信息位一个都没有就什么都不渲染（见脚本里的说明） -->
  <div v-if="items.length" class="sbar">
    <button
      v-for="item in items"
      :key="item.key"
      type="button"
      class="sbar-item"
      :title="item.title || ''"
      @click="$emit('select', item.key)"
    >
      <Icon v-if="item.icon" :name="item.icon" class="sm" />
      <span class="sbar-text">{{ item.text }}</span>
    </button>
  </div>
</template>
