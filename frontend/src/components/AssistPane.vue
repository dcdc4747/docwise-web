<template>
  <!--
    右栏「助手」的**共用骨架**。

    为什么要有这个组件（2026-10-19，修了三次同类 bug 之后）：
    - 读懂页：中间有个 237px 的节点把高度链切断 → 输入框被顶到中间；
    - 写作页：`.wr-helper-body` 是 `display:block` → 输入框悬在面板中间；
    - 模型下拉：`bottom: calc(100% + 6px)` 相对了错的容器。

    三次的根因是同一个：**高度链靠"每一级都恰好能伸缩"的隐式约定**，
    一旦有节点不参与 flex，就静默失效（不报错、构建也过，只有用户看见）。

    现在把这条链写死在组件里：
      `.assist-pane`（可伸缩列）→ `.assist-pane-body`（吃掉剩余高度）
    页面只负责"往里塞内容"，不用再关心高度；新加页签也不会重犯。
  -->
  <div :class="['assist-pane', rootClass]">
    <!-- 页签之上：手机抽屉的把手 / 关闭键这类东西（不放进 .tabs，那个契约只放页签） -->
    <slot name="above-tabs" />

    <div v-if="tabs.length" class="tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        :class="{ on: activeKey === tab.key }"
        @click="$emit('update:activeKey', tab.key)"
      >
        {{ tab.label }}
      </button>
      <!-- 页签右侧的动作位（例如"新对话"），默认空 -->
      <slot name="tabs-extra" />
    </div>

    <div ref="bodyEl" :class="['assist-pane-body', bodyClass]">
      <slot />
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  /** 页签：[{ key, label }] */
  tabs: { type: Array, default: () => [] },
  activeKey: { type: String, default: '' },
  /** 保留各页原来的类名（`.assist` / `.wr-helper`），样式与测试选择器都不用改 */
  rootClass: { type: [String, Array, Object], default: '' },
  bodyClass: { type: [String, Array, Object], default: '' },
})

defineEmits(['update:activeKey'])

/** 有的页面要按名字拿到滚动容器（例如切页签时回到顶部） */
const bodyEl = ref(null)
defineExpose({ bodyEl })
</script>
