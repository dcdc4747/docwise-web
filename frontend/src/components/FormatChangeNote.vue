<template>
  <!-- 没有改动就**整块不渲染**：一条"AI 改了 0 处"比没有更糟（用户会以为真发生了什么）。 -->
  <div
    v-if="visible"
    class="fmt-note"
    role="status"
    :title="titleAttr"
  >
    <svg class="ic-inl fmt-note-ic" width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
      <use href="#i-spark" />
    </svg>
    <span class="fmt-note-text">{{ message }}</span>
    <span class="fmt-note-spacer" aria-hidden="true" />
    <button type="button" class="btn sm" @click="onUndo">撤销这次改动</button>
    <button type="button" class="btn ghost sm" @click="onDismiss">知道了</button>
  </div>
</template>

<script setup>
/**
 * AI 改版式的痕迹条 —— 让"AI 动过的地方"看得见、且能一键撤回。
 *
 * 为什么需要：AI 已经能直接改字号 / 字体 / 行距 / 缩进，但改完界面上**没有任何标识**，
 * 用户回头看不出"这段是谁动的"；同一页的 AI 标记（`AiBadge`）只覆盖译文与生成内容，
 * 改版式这条路上是空的。这条提示条补的就是这个不一致。
 *
 * 三条纪律：
 * ① ⭐ **绝不编段号**：`blocks` 是真拿到的段号才显示具体数字；
 *    拿不到（前端目前就是拿不到）就照实说「若干处」，**不猜、不补一个像样的数字**。
 *    编出来的段号比没有更糟——用户会拿它去数，数不上就不信整条提示。
 * ② **撤销与「知道了」是两件事**：前者回滚、后者只是把这条收掉（不碰稿子）。
 *    按钮文案必须把差别说清（「撤销这次改动」不是「关闭」）。
 * ③ **自门控**：没有 changes 时整块不渲染，不占屏幕、不出空壳。
 *
 * props：`changes` = `[{ draftId, versionId, blocks: Number[], summary }]`（可为空）。
 * emits：`undo` / `dismiss`，都带上 `changes`（调用方知道撤销/收起的是哪一批）。
 */
import { computed } from 'vue'

const props = defineProps({
  /**
   * 这一次（或这几批）尚未处理的 AI 改版式记录。
   * `blocks` 可以为空数组——空数组就是"段号没拿到"，不是"改了 0 处"。
   */
  changes: { type: Array, default: () => [] },
})

const emit = defineEmits(['undo', 'dismiss'])

/** 段号超过这个数就折叠（设计口径：最多列 5 个）。 */
const COLLAPSE_AFTER = 5

/** 自门控：传空 / 不传 / 传 null 都当"没有改动"，整块不渲染。 */
const visible = computed(() => Array.isArray(props.changes) && props.changes.length > 0)

/**
 * 把各批记录里的段号并起来（去重 + 升序）。
 *
 * 为什么要并：同一次改版式可能分多条记（比如分栏改），段号重复出现时
 * 按条数报「改了 5 处」会**多数一遍**；按去重后的段号报才与用户数得上的数字一致。
 */
const blocks = computed(() => {
  const seen = new Set()
  const out = []
  for (const change of props.changes || []) {
    for (const raw of change?.blocks || []) {
      const num = Number(raw)
      if (!Number.isInteger(num) || num <= 0 || seen.has(num)) continue
      seen.add(num)
      out.push(num)
    }
  }
  return out.sort((a, b) => a - b)
})

/**
 * 标题句：有段号就报数，没有就报「若干处」。
 *
 * ⚠️ 这里**不拿 `changes.length` 当段数**：一次改版式可以只改 1 段却记成 1 条，
 * 也可以改 8 段记成 1 条；条数不是处数，混用就是编数字。
 */
const message = computed(() => {
  const count = blocks.value.length
  if (!count) return 'AI 改了若干处版式（具体段号没记下来）'
  if (count <= COLLAPSE_AFTER) {
    return `AI 改了 ${count} 处版式（第 ${blocks.value.join('、')} 段）`
  }
  // 超过 5 个只列前 5 个再接「等 N 处」——全列出来会把提示条撑成两行（手机上尤其明显）
  return `AI 改了 ${count} 处版式（第 ${blocks.value.slice(0, COLLAPSE_AFTER).join('、')}… 等 ${count} 处）`
})

/**
 * `summary` 只当 tooltip 用，且**与标题句重复时不显示**（悬停出来一句一模一样的字很吵）。
 * 摘要里如果带了"改成小四宋体"这类具体信息，用户悬停就能看到。
 */
const titleAttr = computed(() => {
  const summary =
    [...(props.changes || [])]
      .reverse()
      .map((change) => (change?.summary || '').trim())
      .find(Boolean) || ''
  return summary && summary !== 'AI 改了版式' ? summary : null
})

function onUndo() {
  emit('undo', props.changes)
}

function onDismiss() {
  emit('dismiss', props.changes)
}
</script>

<style scoped>
/* 浅色提示条（不是警告）：底色用 AI 那套 `--ai-bg`，图标形状承担语义、颜色里不塞情绪。 */
.fmt-note {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-5);
  font-size: var(--fs-meta);
  color: var(--ink);
  background: var(--ai-bg);
  border-bottom: 1px solid var(--line-soft);
}
.fmt-note-ic {
  flex: none;
  color: var(--accent);
}
.fmt-note-text {
  min-width: 0;
}
.fmt-note-spacer {
  flex: 1;
}
</style>
