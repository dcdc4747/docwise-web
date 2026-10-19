/**
 * `WriteEditor` 的测试替身。
 *
 * 为什么需要：TipTap/ProseMirror 依赖真实 DOM 的量测，happy-dom 里会抛错。
 * 单测关心的是**页面对"正文变化"的反应**（保存、撤销、AI 写入、骨架），
 * 不是 ProseMirror 内部——所以用一个保持同样 `v-model` 契约的 textarea 替身。
 *
 * ⚠️ 2026-10-19 起页面绑的是 **HTML**（`bodyHtml`），而用例断言的是 Markdown 文本：
 * 替身在这里做一次转换，用例继续按 Markdown 断言（那是产品行为，不是标签形状）。
 *
 * 真浏览器里跑的是真编辑器（`src/components/WriteEditor.vue`）；
 * 这个文件**只被测试通过 `vi.mock` 引用**。
 */
import { ref, watch } from 'vue'

import { htmlToMd, mdToHtml } from '../../src/writeRich'

export default {
  name: 'WriteEditorStub',
  props: {
    modelValue: { type: String, default: '' },
    typography: { type: Object, default: () => ({}) },
  },
  emits: ['update:modelValue', 'update:typography', 'save'],
  setup(props, { emit, expose }) {
    const text = ref(htmlToMd(props.modelValue))

    watch(
      () => props.modelValue,
      (next) => {
        const md = htmlToMd(next)
        if (md !== text.value) text.value = md
      },
    )

    function onInput(event) {
      text.value = event.target.value
      emit('update:modelValue', mdToHtml(text.value))
    }

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
