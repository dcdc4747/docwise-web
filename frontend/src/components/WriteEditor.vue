<template>
  <!--
    写作页的正文编辑器（TipTap / ProseMirror）。

    为什么换掉 textarea（2026-10-19 用户原话：「字号不能改、标题不能改、间距不能改，
    跟记事本一样」）：纯 textarea 只有一种字号，标题只是带 `#` 的字，
    用户没法像在 WPS/Word 里那样"看着像一篇稿子"。

    设计口径：
    ① **存储仍是 Markdown**（`drafts.body_md`）：引文 `[n]`、大纲、导出、AI 写入的锚点校验
       全部按 Markdown 做，编辑器只在 `writeRich.js` 那一层互转；
    ② **结构编辑是富文本**：标题级别、加粗/斜体、对齐、列表、引用都是真样式；
    ③ **版式（字号/行距/段距/缩进）是文档级设置**，不是逐字标记 ——
       Markdown 存不下逐字样式，硬存就会在保存后悄悄丢掉（那种"改了没保存住"更糟）。
  -->
  <div class="we">
    <div class="we-bar" role="toolbar" aria-label="排版工具栏">
      <select
        class="we-sel"
        :value="headingLevel"
        title="段落样式"
        @change="setHeading(Number($event.target.value))"
      >
        <option :value="0">正文</option>
        <option :value="1">标题 1</option>
        <option :value="2">标题 2</option>
        <option :value="3">标题 3</option>
      </select>

      <span class="we-sep" />

      <button type="button" :class="{ on: isActive('bold') }" title="加粗（Ctrl+B）" @click="cmd('toggleBold')">
        <b>B</b>
      </button>
      <button type="button" :class="{ on: isActive('italic') }" title="斜体（Ctrl+I）" @click="cmd('toggleItalic')">
        <i>I</i>
      </button>
      <button type="button" :class="{ on: isActive('bulletList') }" title="无序列表" @click="cmd('toggleBulletList')">
        •
      </button>
      <button type="button" :class="{ on: isActive('orderedList') }" title="有序列表" @click="cmd('toggleOrderedList')">
        1.
      </button>
      <button type="button" :class="{ on: isActive('blockquote') }" title="引用块" @click="cmd('toggleBlockquote')">
        ❝
      </button>

      <span class="we-sep" />

      <button type="button" title="左对齐" @click="setAlign('left')">⬅</button>
      <button type="button" title="居中" @click="setAlign('center')">↔</button>
      <button type="button" title="右对齐" @click="setAlign('right')">➡</button>

      <span class="we-sep" />

      <label class="we-field" title="正文字号">
        字号
        <select
          :value="typography.fontSize"
          @change="setTypo('fontSize', Number($event.target.value))"
        >
          <option v-for="size in FONT_SIZES" :key="size" :value="size">{{ size }}</option>
        </select>
      </label>
      <label class="we-field" title="行距">
        行距
        <select :value="typography.lineHeight" @change="setTypo('lineHeight', Number($event.target.value))">
          <option v-for="lh in LINE_HEIGHTS" :key="lh" :value="lh">{{ lh }}</option>
        </select>
      </label>
      <label class="we-field" title="段间距（磅）">
        段距
        <select :value="typography.paraSpacing" @change="setTypo('paraSpacing', Number($event.target.value))">
          <option v-for="ps in PARA_SPACINGS" :key="ps" :value="ps">{{ ps }}</option>
        </select>
      </label>
      <button type="button" :class="{ on: typography.indent }" title="首行缩进两字" @click="toggleIndent">
        缩进
      </button>

      <span class="we-sep" />

      <button type="button" title="撤销（Ctrl+Z）" @click="cmd('undo')">↶</button>
      <button type="button" title="重做（Ctrl+Shift+Z）" @click="cmd('redo')">↷</button>
    </div>

    <div
      v-if="editor"
      ref="hostEl"
      class="we-page"
      :style="pageStyle"
      @keydown="onKeydown"
    >
      <EditorContent :editor="editor" class="we-content" />
    </div>
    <div v-else class="we-page we-loading">编辑器加载中…</div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Editor, EditorContent } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import TextAlign from '@tiptap/extension-text-align'
import { htmlToMd, mdToHtml } from '../writeRich'

const props = defineProps({
  /** Markdown 正文（唯一的存储形态） */
  modelValue: { type: String, default: '' },
  /** 文档级版式 */
  typography: {
    type: Object,
    default: () => ({ fontSize: 16, lineHeight: 1.8, paraSpacing: 10, indent: false }),
  },
})

const emit = defineEmits(['update:modelValue', 'update:typography', 'save'])

const FONT_SIZES = [14, 15, 16, 17, 18, 20]
const LINE_HEIGHTS = [1.5, 1.65, 1.8, 2.0]
const PARA_SPACINGS = [0, 6, 10, 14, 18]

const editor = ref(null)
const hostEl = ref(null)
const headingLevel = ref(0)

/** 文档级版式 → 页面样式（字号/行距/段距/缩进都在这一处生效） */
const pageStyle = computed(() => {
  const typo = props.typography || {}
  return {
    '--we-font-size': `${typo.fontSize || 16}px`,
    '--we-line-height': String(typo.lineHeight || 1.8),
    '--we-para-gap': `${typo.paraSpacing == null ? 10 : typo.paraSpacing}px`,
    '--we-indent': typo.indent ? '2em' : '0',
  }
})

function buildEditor() {
  return new Editor({
    content: mdToHtml(props.modelValue),
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
        // 代码块用不上，且会和正文里的等宽片段混淆
        codeBlock: false,
      }),
      TextAlign.configure({ types: ['heading', 'paragraph'] }),
    ],
    editorProps: {
      attributes: {
        class: 'we-prose',
        'aria-label': '稿件正文',
        spellcheck: 'false',
      },
    },
    onUpdate: ({ editor: instance }) => {
      syncing = true
      emit('update:modelValue', htmlToMd(instance.getHTML()))
      syncHeading()
      // 下一拍放开，避免父级回写又触发一次 setContent
      Promise.resolve().then(() => {
        syncing = false
      })
    },
    onSelectionUpdate: () => syncHeading(),
  })
}

/** 防止 `modelValue` 回写与 `onUpdate` 互相打架（经典死循环） */
let syncing = false

function syncHeading() {
  if (!editor.value) return
  for (const level of [1, 2, 3]) {
    if (editor.value.isActive('heading', { level })) {
      headingLevel.value = level
      return
    }
  }
  headingLevel.value = 0
}

function cmd(name) {
  const chain = editor.value?.chain().focus()
  if (!chain) return
  chain[name]().run()
}

function setHeading(level) {
  const chain = editor.value?.chain().focus()
  if (!chain) return
  headingLevel.value = level
  if (level === 0) chain.setParagraph().run()
  else chain.toggleHeading({ level }).run()
}

function setAlign(value) {
  editor.value?.chain().focus().setTextAlign(value).run()
}

function isActive(name) {
  return Boolean(editor.value?.isActive(name))
}

function setTypo(key, value) {
  emit('update:typography', { ...props.typography, [key]: value })
}

function toggleIndent() {
  setTypo('indent', !props.typography.indent)
}

function onKeydown(event) {
  if ((event.ctrlKey || event.metaKey) && (event.key === 's' || event.key === 'S')) {
    event.preventDefault()
    emit('save')
  }
}

onMounted(() => {
  editor.value = buildEditor()
})

onBeforeUnmount(() => {
  editor.value?.destroy()
  editor.value = null
})

// 外部改动（AI 写入 / 撤销 / 模板骨架 / 切稿）→ 同步进编辑器
watch(
  () => props.modelValue,
  (next) => {
    if (!editor.value || syncing) return
    const currentMd = htmlToMd(editor.value.getHTML())
    if (String(next || '') === currentMd) return
    const { from } = editor.value.state.selection
    editor.value.commands.setContent(mdToHtml(next), { emitUpdate: false })
    // 光标尽量留在原处（外部插入/撤销时体验更连续）
    try {
      const size = editor.value.state.doc.content.size
      editor.value.commands.setTextSelection(Math.min(from, Math.max(0, size - 1)))
    } catch {
      /* 位置失效就让编辑器自己决定 */
    }
  },
)

/* ---------------- 给页面用的命令式接口 ---------------- */

defineExpose({
  /** 聚焦并落到文末（AI 写完后接着写） */
  focusEnd() {
    editor.value?.chain().focus('end').run()
  },
  /** 聚焦第 n 个标题（提纲跳转用，0 基） */
  focusHeading(index) {
    if (!editor.value) return
    const doc = editor.value.state.doc
    let seen = -1
    let target = null
    doc.descendants((node, pos) => {
      if (node.type.name === 'heading') {
        seen += 1
        if (seen === index) {
          target = pos + 1
          return false
        }
      }
      return true
    })
    if (target == null) {
      editor.value.chain().focus('end').run()
      return
    }
    editor.value.chain().focus().setTextSelection(target).run()
    // 让浏览器把它滚进视野
    const node = editor.value.view.nodeDOM(target - 1)
    if (node && node.scrollIntoView) node.scrollIntoView({ block: 'center', behavior: 'smooth' })
  },
  /** 光标处的 Markdown 偏移估算（插引文要按 Markdown 坐标算） */
  caretOffset() {
    if (!editor.value) return null
    try {
      const { from } = editor.value.state.selection
      const before = editor.value.state.doc.textBetween(0, from, '\n\n')
      return before.length
    } catch {
      return null
    }
  },
  focus: () => editor.value?.commands.focus(),
  isReady: () => Boolean(editor.value),
})
</script>

<style scoped>
.we {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1 1 auto;
}
.we-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  padding: 6px 10px;
  border-bottom: 1px solid var(--line, #e6e8ee);
  background: #fafbfd;
}
.we-bar button {
  min-width: 28px;
  height: 26px;
  border: 1px solid transparent;
  background: transparent;
  border-radius: 6px;
  font: inherit;
  font-size: 13px;
  color: #3d4657;
  cursor: pointer;
}
.we-bar button:hover { background: #eef1f6; }
.we-bar button.on { background: #e8eeff; border-color: #c7d5ff; color: #2b4bd0; }
.we-sel, .we-field select {
  height: 26px;
  border: 1px solid var(--line, #e6e8ee);
  border-radius: 6px;
  background: #fff;
  font: inherit;
  font-size: 12px;
  padding: 0 4px;
}
.we-field {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #6b7280;
}
.we-sep {
  width: 1px;
  height: 18px;
  background: var(--line, #e6e8ee);
  margin: 0 4px;
}

/* 纸张观感：A4 宽度 + 页边距，像稿子而不是输入框 */
.we-page {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 28px 0 60px;
  background: #f3f4f7;
}
.we-loading { padding: 40px; color: #8a92a4; font-size: 13px; }
.we-content { max-width: 760px; margin: 0 auto; }
:deep(.we-prose) {
  min-height: 60vh;
  background: #fff;
  padding: 56px 64px 80px;
  border: 1px solid #e6e8ee;
  border-radius: 4px;
  box-shadow: 0 2px 10px rgba(17, 24, 39, 0.04);
  outline: none;
  font-family: var(--serif, 'Source Han Serif SC', 'Songti SC', Georgia, serif);
  font-size: var(--we-font-size, 16px);
  line-height: var(--we-line-height, 1.8);
  color: #1f2430;
}
:deep(.we-prose p) {
  margin: 0 0 var(--we-para-gap, 10px);
  text-indent: var(--we-indent, 0);
}
:deep(.we-prose h1),
:deep(.we-prose h2),
:deep(.we-prose h3) {
  margin: calc(var(--we-para-gap, 10px) + 8px) 0 8px;
  line-height: 1.35;
  font-weight: 700;
  text-indent: 0;
}
:deep(.we-prose h1) { font-size: calc(var(--we-font-size, 16px) * 1.7); }
:deep(.we-prose h2) { font-size: calc(var(--we-font-size, 16px) * 1.35); }
:deep(.we-prose h3) { font-size: calc(var(--we-font-size, 16px) * 1.15); }
:deep(.we-prose blockquote) {
  margin: 0 0 var(--we-para-gap, 10px);
  padding: 4px 0 4px 14px;
  border-left: 3px solid #d7dce6;
  color: #4b5563;
}
:deep(.we-prose ul),
:deep(.we-prose ol) {
  margin: 0 0 var(--we-para-gap, 10px);
  padding-left: 1.6em;
}
:deep(.we-prose p.is-editor-empty:first-child::before) {
  content: '正文由你来写……（用工具栏设标题；从素材卡插入的引文是 [1] 这样的编号）';
  float: left;
  height: 0;
  color: #aab1c0;
  pointer-events: none;
}
</style>
