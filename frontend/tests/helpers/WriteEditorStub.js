/**
 * `WriteEditor` 的测试替身。
 *
 * 为什么需要：TipTap/ProseMirror 依赖真实 DOM 的量测（`getClientRects` 等），
 * happy-dom 里会抛 `Cannot read properties of undefined (reading 'fontSize')`。
 * 单测关心的是**页面对"正文变化"的反应**（保存、撤销、AI 写入、骨架），
 * 不是 ProseMirror 内部——所以用一个保持同样 `v-model` 契约的 textarea 替身。
 *
 * ⚠️ 真浏览器里跑的是真编辑器（`src/components/WriteEditor.vue`）；
 * 这个文件**只被测试通过 `vi.mock` 引用**。
 */
import { ref, watch } from 'vue'

export default {
  name: 'WriteEditorStub',
  props: {
    modelValue: { type: String, default: '' },
    typography: { type: Object, default: () => ({}) },
  },
  emits: ['update:modelValue', 'update:typography', 'save'],
  setup(props, { emit, expose }) {
    const text = ref(props.modelValue)

    watch(
      () => props.modelValue,
      (next) => {
        if (next !== text.value) text.value = next
      },
    )

    function onInput(event) {
      text.value = event.target.value
      emit('update:modelValue', text.value)
    }

    // 页面用到的命令式接口（聚焦 / 文末 / 标题 / 光标偏移）在这里给出等价物
    expose({
      focus: () => {},
      focusEnd: () => {},
      focusHeading: () => {},
      caretOffset: () => text.value.length,
      isReady: () => true,
    })

    return { text, onInput, FONT_SIZES: [14, 16, 18, 20] }
  },
  template: `
    <div class="we we-stub">
      <div class="we-bar">
        <button
          v-for="size in FONT_SIZES"
          :key="size"
          type="button"
          class="we-fontsize"
          @click="$emit('update:typography', { ...typography, fontSize: size })"
        >{{ size }}</button>
      </div>
      <textarea
        class="wr-editor"
        aria-label="稿件正文"
        :value="text"
        @input="onInput"
      />
    </div>
  `,
}
