<script setup>
/**
 * 手机端底部标签栏（**挂载点已就位，内容由 R6 填**）。
 *
 * ⚠️ **这个文件现在是"座位"不是"功能"**：形态 v2 §3.4 定义的 5 个标签
 * （**库 / 起草 / 检查 / 记忆 / 我的**）与抽屉接线都是 **R6** 的活。
 * 本卡（issue #86 第 7 步）只做一件事：**把挂载点钉在 `App.vue` 里**，
 * 这样 R6 之后**只改自己这个文件，不用再碰外壳**（冲突面直接消失）。
 *
 * ⭐ **自门控**：`tabs` 为空就整条不渲染 —— 所以"座位空着"这件事**不会在屏幕上留一条空栏**，
 * 也不会提前招认一个还没做的能力。R6 把真实标签传进来，它就出来了。
 * 这套写法跟仓库里既有的做法一致（`showOutline` 少于 3 条不渲染、`completedBannerTask`
 * 没有就不渲染）—— **拿不到数据不许硬编**。
 *
 * 形态口径（R6 卡点名，填的时候别写错）：
 * - 5 个标签，**第一个叫「库」不叫「读懂」**（窄屏用户看到"读懂"会以为进的是阅读页）；
 * - 桌面叫「收口」、手机标签显示「检查」（字数所限），文档里一律写「收口（手机端显示为检查）」；
 * - ⚠️ **不在手机上做精读**（形态 §3.4 的产品判断）；⚠️ 不许在手机上照搬"左下角头像"。
 */

import Icon from './Icon.vue'

defineProps({
  /**
   * 5 个标签（R6 从自己的数据源算好传进来）。
   * 形状：`[{ key, label, icon, badge? }]`；`icon` 是 sprite 名（走 `Icon.vue`）。
   * ⚠️ **空数组 = 整条不渲染**（自门控）。
   */
  tabs: { type: Array, default: () => [] },
  /** 当前选中的标签 key（由外壳按地址算出来，这个组件不读 `location.hash`）。 */
  active: { type: String, default: '' },
})

defineEmits(['select'])
</script>

<template>
  <!-- 自门控：没有标签就什么都不渲染（见脚本里的说明） -->
  <nav v-if="tabs.length" class="tabbar" aria-label="底部导航">
    <button
      v-for="item in tabs"
      :key="item.key"
      type="button"
      class="tabbar-item"
      :class="{ on: active === item.key }"
      @click="$emit('select', item.key)"
    >
      <Icon :name="item.icon" />
      <span class="tabbar-lbl">{{ item.label }}</span>
      <span v-if="item.badge" class="tabbar-badge">{{ item.badge }}</span>
    </button>
  </nav>
</template>
