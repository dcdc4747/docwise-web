<template>
  <button
    type="button"
    class="mat-save"
    :class="[variant, { saved, failed }]"
    :title="title"
    :disabled="!ready || saving"
    @mousedown.prevent
    @click.stop="save"
  >
    {{ text }}
  </button>
</template>

<script setup>
/**
 * 「存为素材」—— 阅读区**三处入口共用的同一个控件**（M2 / 契约 §2.4 的 N12）。
 *
 * 三处都在：**段落精读的划词浮标 / 问答答案的出处 / 导读要点的出处**。
 * ⚠️ 三处必须走**同一个 store 的同一条路径**（`useMaterials.saveMaterial`）——
 * 各写一套的话，请求体、文案、失败处理必然各走各的。
 *
 * 三条细节：
 * ① `@mousedown.prevent`：浮标是浮在选中的文字上的，按下时若不清掉默认行为，
 *    浏览器会把选区丢掉、浮标跟着消失（"点不着"就是这么来的）；
 * ② `@click.stop`：别让点击冒泡到段落/页面上的划词与选中处理；
 * ③ 文案**不说"存这一句"**：契约的入参只有 `{task_id, block_id}`，服务端按**块**深拷贝
 *    原文与出处，划词存下来的是**那一段**（说成"存这一句"就是骗人）。
 */
import { computed } from 'vue'

import { saveMaterial, saveState } from '../stores/useMaterials'

const props = defineProps({
  /** 当前任务的 id（`currentTask.id`）。 */
  taskId: { type: [Number, String], default: null },
  /** 这一段/这一句所在的**块编号**（没有块坐标就存不了，按钮会置灰）。 */
  blockId: { type: String, default: '' },
  /** 三种入口的样式钩子：`chip`（划词浮标）/ `src`（问答出处）/ `guide`（导读要点）。 */
  variant: { type: String, default: 'src' },
  /** 默认文案；存上 / 没存上时会就地换掉（就地反馈，不跳页）。 */
  label: { type: String, default: '存为素材' },
  note: { type: String, default: null },
})

const bid = computed(() => String(props.blockId || '').trim())
const ready = computed(() => Boolean(Number(props.taskId)) && Boolean(bid.value))
/** 只认**这一段**的保存状态（三处入口共用一份状态，靠 blockId 区分）。 */
const mine = computed(() => saveState.value.blockId === bid.value)
const saving = computed(() => mine.value && saveState.value.status === 'saving')
const saved = computed(() => mine.value && saveState.value.status === 'saved')
const failed = computed(() => mine.value && saveState.value.status === 'error')

const text = computed(() => {
  if (saving.value) return '正在存…'
  if (saved.value) return '已存为素材'
  if (failed.value) return '没存上，重试'
  return props.label
})

const title = computed(() => {
  if (!ready.value) return '这一段没有块坐标，存不了素材'
  if (failed.value) return saveState.value.message || '没存上'
  if (saved.value) return '已存到写作页左栏的素材里'
  return '把这一段存成素材卡（原文与出处由服务端按快照记下）'
})

function save() {
  if (!ready.value || saving.value) return
  saveMaterial({ taskId: props.taskId, blockId: bid.value, note: props.note })
}
</script>
