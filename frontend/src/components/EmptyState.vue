<template>
  <div class="empty">
    <div class="empty-title">{{ title }}</div>
    <p v-if="descText" class="empty-desc">{{ descText }}</p>
    <div class="empty-ops">
      <!-- 真空：给一个**动作**（主按钮），不是一行小链接 -->
      <button
        v-if="variant === 'empty' && actionText"
        type="button"
        class="btn primary empty-action"
        @click="emit('action')"
      >
        {{ actionText }}
      </button>
      <!-- 筛空了：给**出口**（说清是筛选造成的，再把筛选去掉） -->
      <button
        v-else-if="variant === 'filtered'"
        type="button"
        class="btn empty-clear"
        @click="emit('clear')"
      >
        {{ clearText }}
      </button>
    </div>
    <slot />
  </div>
</template>

<script setup>
/**
 * 空态 —— **必须分两种**，因为"库里什么都没有"和"有文献但筛没了"是两件完全不同的事：
 *
 * | 变体 | 谁造成 | 给什么 |
 * |---|---|---|
 * | `empty`（真空） | 库里就是空的 | **一个动作**（主按钮，去上传/去新建） |
 * | `filtered`（筛空了） | 筛选条件造成的 | **一个出口**（清除筛选），并把"是筛选造成的"说清 |
 *
 * ⚠️ 两种都**绝不说"暂无数据"**：这句话没告诉用户"为什么空""我能做什么"，
 * 是这一版设计里最想删掉的一句"看起来说清了、其实什么都没说"的文案。
 * 谁把"暂无数据"传进来，开发环境会 `console.warn`。
 *
 * 空态是"另一半"：**真空至少出现过一次主按钮** —— 用户第一次进来看到的应该是"能做什么"，
 * 而不是一面墙。
 */
import { computed, watchEffect } from 'vue'

const props = defineProps({
  /** `empty` = 真空（库里什么都没有）；`filtered` = 筛空了（有文献，被筛没了）。 */
  variant: {
    type: String,
    default: 'empty',
    validator: (value) => ['empty', 'filtered'].includes(value),
  },
  /** 一句话说清"空的是什么"。 */
  title: { type: String, required: true },
  /** 补充说明；筛空态不给的话用一句"是筛选造成的"兜底，不留白。 */
  description: { type: String, default: '' },
  /** 真空态的主按钮文案（**必给**：动作由调用方决定，组件不替它编）。 */
  actionText: { type: String, default: '' },
  /** 筛空态的出口文案。 */
  clearText: { type: String, default: '清除筛选' },
})

const emit = defineEmits(['action', 'clear'])

const descText = computed(() => {
  if (props.description) return props.description
  return props.variant === 'filtered' ? '当前筛选条件下没有匹配的文献。' : ''
})

const BANNED = '暂无数据'

watchEffect(() => {
  if (!import.meta.env.DEV) return
  if (props.title.includes(BANNED) || props.description.includes(BANNED)) {
    console.warn(
      `[EmptyState] 不许说「${BANNED}」：真空态说清"库是空的"并给动作，筛空态说清"是筛选造成的"并给出口。`,
    )
  }
})
</script>
