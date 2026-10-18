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
  <div class="we" @keydown="onKeydown">
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

      <!-- 插图 / 插表（2026-10-19）：图片读成 dataURL 保存进正文，不上传服务器 -->
      <button type="button" title="插入图片（本地文件，不联网）" @click="pickImage">🖼</button>
      <button type="button" title="插入表格（3×3 带表头）" @click="insertTable">▦</button>
      <template v-if="inTable">
        <button type="button" title="加一行" @click="tableCmd('addRowAfter')">＋行</button>
        <button type="button" title="加一列" @click="tableCmd('addColumnAfter')">＋列</button>
        <button type="button" title="删这一行" @click="tableCmd('deleteRow')">－行</button>
        <button type="button" title="删这一列" @click="tableCmd('deleteColumn')">－列</button>
        <button type="button" title="删整张表" @click="tableCmd('deleteTable')">删表</button>
      </template>
      <input
        ref="imageInput"
        type="file"
        accept="image/*"
        class="we-file"
        @change="onImagePicked"
      />

      <span class="we-sep" />

      <label class="we-field" title="字体（作用于选区）">
        字体
        <select :value="currentFontFamily" @change="setFontFamily($event.target.value)">
          <option value="">默认</option>
          <option v-for="font in FONT_FAMILIES" :key="font.label" :value="font.value">
            {{ font.label }}
          </option>
        </select>
      </label>
      <label class="we-field" title="正文字号">
        字号
        <select
          :value="currentFontSize"
          title="选中一段后设为该字号（作用于选区）"
          @change="setFontSize(Number($event.target.value))"
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
      <button type="button" title="重做（Ctrl+Shift+Z / Ctrl+Y）" @click="cmd('redo')">↷</button>
    </div>

    <div
      v-if="editor"
      ref="hostEl"
      class="we-page"
      :style="pageStyle"
    >
      <EditorContent :editor="editor" class="we-content" />
    </div>
    <div v-else class="we-page we-loading">编辑器加载中…</div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Editor, EditorContent } from '@tiptap/vue-3'
import { Extension } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import TextAlign from '@tiptap/extension-text-align'
import { TextStyle } from '@tiptap/extension-text-style'
import Image from '@tiptap/extension-image'
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table'

const props = defineProps({
  /** Markdown 正文（唯一的存储形态） */
  modelValue: { type: String, default: '' },
  /** 文档级版式 */
  typography: {
    type: Object,
    default: () => ({ fontSize: 16, lineHeight: 1.8, paraSpacing: 10, indent: false }),
  },
})

const emit = defineEmits(['update:modelValue', 'update:typography', 'save', 'image-error'])

/**
 * 逐处字号（TextStyle + `font-size` 属性）。
 *
 * 为什么要自己写：TipTap 官方没有独立的 FontSize 扩展，
 * 而"选中这段设成 18px"必须落到 **mark**（内联 span 的 style）里，
 * 才能在 HTML 往返后仍然存在。
 */
const FontSize = Extension.create({
  name: 'fontSize',
  addOptions() {
    return { types: ['textStyle'] }
  },
  addGlobalAttributes() {
    return [
      {
        types: this.options.types,
        attributes: {
          fontSize: {
            default: null,
            parseHTML: (element) => element.style.fontSize || null,
            renderHTML: (attributes) =>
              attributes.fontSize ? { style: `font-size: ${attributes.fontSize}` } : {},
          },
        },
      },
    ]
  },
  addCommands() {
    return {
      setFontSize:
        (size) =>
        ({ chain }) =>
          chain().setMark('textStyle', { fontSize: size }).run(),
      unsetFontSize:
        () =>
        ({ chain }) =>
          chain().setMark('textStyle', { fontSize: null }).removeEmptyTextStyle().run(),
    }
  },
})

/**
 * 块级样式（段落/标题/列表项/引用上的 `style`）。
 *
 * 为什么需要：AI 改版式时把字号字体写在**段落**上（`<p style="font-size:17px">`），
 * 而 TipTap 只认 schema 里声明过的属性——没声明就**静默丢掉**，
 * 表现是"模型说改了、编辑器里没变"。这里把常用几项声明成属性，解析与渲染都保留。
 */
const BLOCK_STYLE_ATTRS = ['fontFamily', 'fontSize', 'lineHeight', 'textIndent']

const BlockStyle = Extension.create({
  name: 'blockStyle',
  addOptions() {
    return { types: ['paragraph', 'heading', 'listItem', 'blockquote'] }
  },
  addGlobalAttributes() {
    return [
      {
        types: this.options.types,
        attributes: Object.fromEntries(
          BLOCK_STYLE_ATTRS.map((key) => [
            key,
            {
              default: null,
              parseHTML: (element) => element.style[key] || null,
              renderHTML: (attributes) =>
                attributes[key] ? { style: `${kebab(key)}: ${attributes[key]}` } : {},
            },
          ]),
        ),
      },
    ]
  },
})

/** `fontFamily` → `font-family`（CSS 属性名） */
function kebab(name) {
  return name.replace(/[A-Z]/g, (ch) => `-${ch.toLowerCase()}`)
}

const FONT_SIZES = [12, 14, 16, 18, 20, 22, 24]

/**
 * 字体（2026-10-19 用户要求）：中文写作真正会用到的几款，全部用**系统自带**的字族名，
 * 不引外部字体文件（离线可用、也不增加打包体积）。
 * `value` 为空 = 跟随文档默认（宋体）。
 */
/**
 * 逐处字体（与字号同一套 `textStyle` 机制）。
 * 之所以自己写：TipTap 官方只有 TextStyle 基座，具体属性要自己挂。
 */
const FontFamily = Extension.create({
  name: 'fontFamily',
  addOptions() {
    return { types: ['textStyle'] }
  },
  addGlobalAttributes() {
    return [
      {
        types: this.options.types,
        attributes: {
          fontFamily: {
            default: null,
            parseHTML: (element) => element.style.fontFamily || null,
            renderHTML: (attributes) =>
              attributes.fontFamily ? { style: `font-family: ${attributes.fontFamily}` } : {},
          },
        },
      },
    ]
  },
  addCommands() {
    return {
      setFontFamily:
        (family) =>
        ({ chain }) =>
          chain().setMark('textStyle', { fontFamily: family }).run(),
      unsetFontFamily:
        () =>
        ({ chain }) =>
          chain().setMark('textStyle', { fontFamily: null }).removeEmptyTextStyle().run(),
    }
  },
})

/**
 * 写作快捷键（2026-10-19）——目标是**像 Word/WPS 一样能盲操**。
 *
 * 为什么自己再注册一遍（StarterKit 本来就有 Bold/Italic/UndoRedo）：
 * ① 快捷键是**产品承诺**，集中在这一处才读得全、改得动（散在三个扩展里没人说得清）；
 * ② `Tab` 是 StarterKit 的缺口：ListItem 只在"能缩进"时接住它，**正文里没人接**，
 *    浏览器会把焦点移到工具栏/下一个控件上（实测：`Tab` 的 `defaultPrevented` 是 false）。
 *    这里统一兜底：列表里缩进，其余情况**吞掉这个键**（返回 true → ProseMirror 调 preventDefault），
 *    正文不插不可见的制表符——首行缩进是文档级设置（工具栏「缩进」），不靠空格伪造。
 * ③ 优先级调高（1000）：先于 StarterKit 的 ListItem 拿到 `Tab`，行为才由这里说了算；
 *    键位与官方扩展一致，不会出现"两套快捷键各管一半"。
 *
 * `Mod-s` **故意不写在这里**：它要在 DOM 层 `stopPropagation`（见 `onKeydown`），
 * 否则页面级的保存监听会收到第二遍、存两次。
 */
const WriteShortcuts = Extension.create({
  name: 'writeShortcuts',
  priority: 1000,
  addKeyboardShortcuts() {
    return {
      'Mod-b': () => this.editor.commands.toggleBold(),
      'Mod-i': () => this.editor.commands.toggleItalic(),
      // 撤销/重做**总是返回 true**（= 吞掉按键）：历史为空时也不能落回浏览器的原生撤销，
      // 那会绕过 ProseMirror 的 history、直接改 DOM（状态与文档就对不上了）。
      'Mod-z': () => {
        this.editor.commands.undo()
        return true
      },
      'Shift-Mod-z': () => {
        this.editor.commands.redo()
        return true
      },
      'Mod-y': () => {
        this.editor.commands.redo()
        return true
      },
      // 列表里 Tab / Shift-Tab = 缩进 / 反缩进；不在列表里就只吞键，焦点不跳走
      Tab: ({ editor }) => {
        if (editor.isActive('listItem')) {
          if (editor.commands.sinkListItem('listItem')) return true
        }
        return true
      },
      'Shift-Tab': ({ editor }) => {
        if (editor.isActive('listItem')) {
          if (editor.commands.liftListItem('listItem')) return true
        }
        return true
      },
    }
  },
})

const FONT_FAMILIES = [
  { label: '宋体', value: "'Songti SC', 'SimSun', 'Source Han Serif SC', serif" },
  { label: '黑体', value: "'Heiti SC', 'SimHei', 'Source Han Sans SC', sans-serif" },
  { label: '楷体', value: "'Kaiti SC', 'KaiTi', 'STKaiti', serif" },
  { label: '仿宋', value: "'FangSong', 'STFangsong', serif" },
  { label: '思源宋体', value: "'Source Han Serif SC', 'Noto Serif SC', serif" },
  { label: '思源黑体', value: "'Source Han Sans SC', 'Noto Sans SC', sans-serif" },
  { label: '等宽', value: "'JetBrains Mono', Consolas, 'Courier New', monospace" },
]
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
    // v-model 收发的是 HTML（逐段字号都在里面），Markdown 由页面从 HTML 派生
    content: props.modelValue || '<p></p>',
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
        // 代码块用不上，且会和正文里的等宽片段混淆
        codeBlock: false,
      }),
      TextAlign.configure({ types: ['heading', 'paragraph'] }),
      TextStyle,
      FontSize,
      FontFamily,
      BlockStyle,
      // 插图（本地图片走 dataURL，不新增上传接口）
      Image.configure({ inline: false, allowBase64: true }),
      // 表格：3×3 带表头那种，够日常用
      Table.configure({ resizable: false }),
      TableRow,
      TableHeader,
      TableCell,
      WriteShortcuts,
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
      emit('update:modelValue', instance.getHTML())
      syncHeading()
      // 下一拍放开，避免父级回写又触发一次 setContent
      Promise.resolve().then(() => {
        syncing = false
      })
    },
    onSelectionUpdate: () => {
        syncHeading()
        syncFontSize()
        syncFontFamily()
      },
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

/** 选区当前字体（没有内联 mark 时显示"默认"） */
const currentFontFamily = ref('')
function normalizeFamily(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/["']/g, '')
    .replace(/\s+/g, '')
}

function syncFontFamily() {
  const raw = editor.value?.getAttributes('textStyle')?.fontFamily || ''
  if (!raw) {
    currentFontFamily.value = ''
    return
  }
  // 命中已知字体就回显选项自己的值（引号风格不同，必须归一后比）
  const hit = FONT_FAMILIES.find((font) => normalizeFamily(font.value) === normalizeFamily(raw))
  currentFontFamily.value = hit ? hit.value : raw
}

function setFontFamily(family) {
  const chain = editor.value?.chain().focus()
  if (!chain) return
  if (!family) chain.unsetFontFamily().run()
  else chain.setFontFamily(family).run()
  currentFontFamily.value = family
  syncFontFamily()
}

/** 是否在表格里（决定"表格操作"那排按钮显不显示） */
const inTable = computed(() => Boolean(editor.value?.isActive('table')))

const imageInput = ref(null)

function pickImage() {
  imageInput.value?.click()
}

/**
 * 选中本地图片 → 读成 dataURL → 插进正文。
 *
 * 为什么用 dataURL：后端没有"上传图片"的接口，加一个要动契约与存储；
 * dataURL 直接进 `body_html`/`body_md`（内联 `<img src="data:…">`），
 * 保存、导出、回读都不依赖外部文件。代价是正文体积变大——单张图限额 1.5 MB。
 */
function onImagePicked(event) {
  const file = event.target.files && event.target.files[0]
  if (!file) return
  if (file.size > 1_500_000) {
    // 超限不静默：把它告诉父级（页面会弹 toast）
    emit('image-error', '图片超过 1.5 MB，先压缩再插')
    event.target.value = ''
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    const src = String(reader.result || '')
    if (src) editor.value?.chain().focus().setImage({ src, alt: file.name }).run()
  }
  reader.readAsDataURL(file)
  event.target.value = ''
}

function insertTable() {
  editor.value?.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()
}

/** 表格操作：命令名直接用 TipTap 的（addRowAfter / deleteTable …） */
function tableCmd(name) {
  const chain = editor.value?.chain().focus()
  if (!chain) return
  const fn = chain[name]
  if (typeof fn === 'function') fn.call(chain).run()
}

function setFontSize(size) {
  const chain = editor.value?.chain().focus()
  if (!chain) return
  if (!size) chain.unsetFontSize().run()
  else chain.setFontSize(`${size}px`).run()
  syncFontSize()
}

/** 选区当前字号（没有内联 mark 时显示文档默认） */
const currentFontSize = ref(props.typography?.fontSize || 16)
function syncFontSize() {
  const size = editor.value?.getAttributes('textStyle')?.fontSize
  currentFontSize.value = size ? Number(String(size).replace('px', '')) : (props.typography?.fontSize || 16)
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

/**
 * 编辑器内的按键兜底（快捷键本体见 `WriteShortcuts`）。
 *
 * 两件事 ProseMirror 管不到，必须在这一层做：
 * ① `Ctrl/Cmd+S` 保存——`preventDefault` 拦掉浏览器「保存网页」对话框，再走页面的保存回调。
 *    `stopPropagation` 是给 WriteView 的页面级监听留的：编辑器有焦点时**只存一次**，
 *    焦点在标题栏/助手输入框时由页面那条监听接手。
 * ② `Ctrl/Cmd+B` 的**冒泡**——外壳 App.vue 在 window 上把 `Ctrl+B` 当"收起/展开左栏"
 *    （全局快捷键）。写作区里它必须是加粗，不切断冒泡的话会一边加粗一边把左栏收起来
 *    （2026-10-19 实测：`rail-min` 从 true 变 false）。
 *
 * 复制/粘贴/剪切（`Ctrl+C/V/X`）**不在这里处理**：交给浏览器与 ProseMirror 原生剪贴板，
 * 它同时带 `text/html` 与 `text/plain`，富文本和纯文本都不会粘成源码。
 */
function onKeydown(event) {
  if (!(event.ctrlKey || event.metaKey)) return
  const key = String(event.key || '').toLowerCase()
  if (key === 's') {
    event.preventDefault()
    event.stopPropagation()
    emit('save')
    return
  }
  if (key === 'b') {
    // 加粗已由 `Mod-b` 处理；这里只拦住冒泡，别让外壳再收一次左栏
    event.preventDefault()
    event.stopPropagation()
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
    const currentHtml = editor.value.getHTML()
    if (String(next || '') === currentHtml) return
    const { from } = editor.value.state.selection
    editor.value.commands.setContent(next || '<p></p>', { emitUpdate: false })
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
/* 插图（2026-10-19）：最宽不溢出页面，居中 */
.we :deep(img) {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 8px auto;
  border-radius: 6px;
}
/* 表格：细边框 + 表头浅灰，跟 Word 观感接近 */
.we :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 10px 0;
}
.we :deep(th),
.we :deep(td) {
  border: 1px solid var(--line);
  padding: 6px 8px;
  vertical-align: top;
}
.we :deep(th) {
  background: #f5f6f9;
  font-weight: 600;
  text-align: left;
}
/* 隐藏原生文件框（用工具栏按钮触发） */
.we-file {
  display: none;
}

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
