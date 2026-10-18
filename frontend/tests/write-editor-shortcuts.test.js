/**
 * 写作编辑器的快捷键契约（2026-10-19）。
 *
 * 为什么守源码而不是挂载：TipTap/ProseMirror 需要真实 DOM 量测，happy-dom 里跑不起来
 * （`tests/helpers/WriteEditorStub.js` 就是因此存在的替身）。快捷键本体注册在
 * `WriteEditor.vue` 的 `addKeyboardShortcuts` 与 DOM 的 keydown 里，**替身里没有**，
 * 所以这一包用「源码级断言 + 纯函数级断言」把两件最容易悄悄坏掉的事钉住：
 *
 * ① **键真的注册了**：撤销 / 重做 / 加粗 / 斜体 / Tab。少注册一个，界面看起来一切正常，
 *    只是按下去没反应（Tab 更糟：焦点会跳出编辑器）。
 * ② **没有抢键**：`Ctrl+S` 不许弹浏览器的「保存网页」；`Ctrl+B` 不许顺带把外壳左栏收起来；
 *    复制/粘贴/剪切不许被自定义处理器接走（接走就会粘成源码）。
 *
 * 真浏览器里的行为验证见 `tests/note-shortcuts.md`（本包只保证"代码长成了这样"）。
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { htmlToMd, mdToHtml } from '../src/writeRich'

const read = (p) => readFileSync(path.resolve(process.cwd(), p), 'utf8')
const EDITOR = read('src/components/WriteEditor.vue')
const VIEW = read('src/views/WriteView.vue')

/** 剥注释：注释里常写「不许 key === 's'」这类反例，不剥会把说明文字当成实现。 */
function stripComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')
}

/** 取一个 `function name(...) { ... }` 的函数体（够用即可：这些函数里没有嵌套模板串的花活）。 */
function functionBody(source, name) {
  const at = source.indexOf(`function ${name}(`)
  if (at < 0) return ''
  const start = source.indexOf('{', at)
  if (start < 0) return ''
  let depth = 0
  for (let i = start; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1
    else if (source[i] === '}') {
      depth -= 1
      if (depth === 0) return source.slice(start + 1, i)
    }
  }
  return ''
}

const EDITOR_CODE = stripComments(EDITOR)
const VIEW_CODE = stripComments(VIEW)
/** 快捷键扩展那一段（`const WriteShortcuts = Extension.create({…})` 到下一个常量之间）。 */
const KEYMAP = EDITOR_CODE.slice(
  EDITOR_CODE.indexOf('const WriteShortcuts'),
  EDITOR_CODE.indexOf('const FONT_FAMILIES'),
)
const EDITOR_KEYDOWN = functionBody(EDITOR_CODE, 'onKeydown')
const VIEW_KEYDOWN = functionBody(VIEW_CODE, 'onWriteKeydown')

describe('写作编辑器 · 快捷键注册（源码级）', () => {
  it('有 addKeyboardShortcuts，且加粗/斜体/撤销/重做都显式注册', () => {
    expect(KEYMAP).toContain('addKeyboardShortcuts')
    for (const combo of ['Mod-b', 'Mod-i', 'Mod-z', 'Shift-Mod-z', 'Mod-y']) {
      expect(KEYMAP, `缺 ${combo}`).toContain(`'${combo}'`)
    }
  })

  it('撤销/重做走编辑器自己的历史（undo / redo），并且总是吞掉按键（不落回浏览器原生撤销）', () => {
    expect(KEYMAP).toMatch(/'Mod-z':\s*\(\)\s*=>\s*\{[\s\S]*?commands\.undo\(\)[\s\S]*?return true/)
    expect(KEYMAP).toMatch(/'Shift-Mod-z':\s*\(\)\s*=>\s*\{[\s\S]*?commands\.redo\(\)[\s\S]*?return true/)
    expect(KEYMAP).toMatch(/'Mod-y':\s*\(\)\s*=>\s*\{[\s\S]*?commands\.redo\(\)[\s\S]*?return true/)
  })

  it('加粗/斜体指向 toggleBold / toggleItalic', () => {
    expect(KEYMAP).toMatch(/'Mod-b':\s*\(\)\s*=>\s*this\.editor\.commands\.toggleBold\(\)/)
    expect(KEYMAP).toMatch(/'Mod-i':\s*\(\)\s*=>\s*this\.editor\.commands\.toggleItalic\(\)/)
  })

  it('Tab / Shift-Tab 已注册，并且无论如何都 return true（= 浏览器 preventDefault，焦点不跳走）', () => {
    expect(KEYMAP).toMatch(/\bTab:\s*\(\{\s*editor\s*\}\)\s*=>/)
    expect(KEYMAP).toContain("'Shift-Tab'")

    const tab = KEYMAP.slice(KEYMAP.indexOf('Tab:'))
    expect(tab, 'Tab 分支必须吞掉按键').toMatch(/return true/)
    // 不许往正文里塞制表符/空格来假冒缩进（首行缩进是文档级设置）
    expect(tab).not.toContain("insertContent('\\t')")
    expect(tab).not.toContain('insertText')
  })

  it('Tab 在列表里缩进、Shift-Tab 反缩进（不是一律什么都不做）', () => {
    expect(KEYMAP).toContain("sinkListItem('listItem')")
    expect(KEYMAP).toContain("liftListItem('listItem')")
  })

  it('快捷键扩展真的挂进了编辑器', () => {
    expect(EDITOR_CODE).toContain('WriteShortcuts,')
    expect(EDITOR_CODE).toMatch(/extensions:\s*\[[\s\S]*?WriteShortcuts/)
  })
})

describe('写作编辑器 · Ctrl+S（不许触发浏览器保存页面）', () => {
  it('编辑器内：preventDefault + emit("save") + 切断冒泡（避免页面级重复保存）', () => {
    expect(EDITOR_KEYDOWN).toMatch(/key === 's'/)
    expect(EDITOR_KEYDOWN).toContain('preventDefault()')
    expect(EDITOR_KEYDOWN).toContain("emit('save')")
    expect(EDITOR_KEYDOWN).toContain('stopPropagation()')
  })

  it('Mod-s 不在键盘映射里（否则会走两遍保存）', () => {
    expect(EDITOR_CODE).not.toContain("'Mod-s'")
  })

  it('页面级也有一条：焦点在标题栏/助手输入框时照样保存', () => {
    // 修饰键判断必须与 `s` 在**同一个 if** 里（否则单独按 s 也会被吞掉）
    expect(VIEW_KEYDOWN).toMatch(
      /if\s*\(\s*\(event\.ctrlKey \|\| event\.metaKey\)\s*&&\s*\(event\.key === 's' \|\| event\.key === 'S'\)\s*\)/,
    )
    expect(VIEW_KEYDOWN).toContain('preventDefault()')
    expect(VIEW_KEYDOWN).toContain('saveWithFeedback()')
    expect(VIEW_CODE).toContain("addEventListener('keydown', onWriteKeydown)")
    expect(VIEW_CODE).toContain("removeEventListener('keydown', onWriteKeydown)")
  })

  it('WriteView 里没有第二套 Ctrl+S 处理器（旧的 onEditorKeydown 已删）', () => {
    expect(VIEW_CODE).not.toContain('onEditorKeydown')
    expect(VIEW_CODE.match(/key === 's'/g) || []).toHaveLength(1)
  })
})

describe('写作编辑器 · 不抢键', () => {
  it('Ctrl+B 只加粗，不把外壳的「收/展左栏」一起触发', () => {
    expect(EDITOR_KEYDOWN).toMatch(/key === 'b'/)
    expect(EDITOR_KEYDOWN).toMatch(/key === 'b'[\s\S]{0,200}stopPropagation\(\)/)
    // 根节点挂 keydown：工具栏与正文里的 Ctrl+B 都在冒泡到 window 前被拦下
    expect(EDITOR_CODE).toContain('<div class="we" @keydown="onKeydown">')
  })

  it('复制 / 粘贴 / 剪切交给浏览器原生剪贴板，编辑器不接走', () => {
    for (const key of ['c', 'v', 'x']) {
      expect(EDITOR_KEYDOWN).not.toContain(`key === '${key}'`)
      expect(VIEW_KEYDOWN).not.toContain(`key === '${key}'`)
    }
    expect(EDITOR_CODE).not.toContain('handlePaste')
    expect(EDITOR_CODE).not.toContain('handleCopy')
    expect(EDITOR_CODE).not.toContain("addEventListener('paste'")
    expect(VIEW_CODE).not.toContain("addEventListener('paste'")
  })

  it('没有任何「不判修饰键就抢 s/v/z」的写法', () => {
    // 整条条件只有 event.key === 's' / 'v' / 'z'：浏览器会把它当成普通字母键吞掉
    expect(EDITOR_CODE).not.toMatch(/if\s*\(\s*event\.key\s*===\s*'[svz]'\s*\)/)
    expect(VIEW_CODE).not.toMatch(/if\s*\(\s*event\.key\s*===\s*'[svz]'\s*\)/)
    // 只按字母判 s 的处理函数，必须在**函数开头**先过修饰键
    expect(EDITOR_KEYDOWN).toMatch(
      /^\s*if\s*\(!\s*\(\s*event\.ctrlKey\s*\|\|\s*event\.metaKey\s*\)\s*\)\s*return/,
    )
  })

  it('Enter / Shift+Enter 不另立快捷键（用 ProseMirror 的段落/换行默认行为）', () => {
    expect(KEYMAP).not.toMatch(/\bEnter:/)
    expect(KEYMAP).not.toContain("'Shift-Enter'")
    // StarterKit 的 hardBreak / 段落不能被关掉
    expect(EDITOR_CODE).not.toContain('hardBreak: false')
    // 现有配置只关了代码块（它和等宽正文混淆），不影响 Enter
    expect(EDITOR_CODE).toMatch(/codeBlock:\s*false/)
  })

  it('StarterKit 的加粗/斜体/撤销没有被关掉（自注册的键位与它们一致）', () => {
    expect(EDITOR_CODE).not.toContain('bold: false')
    expect(EDITOR_CODE).not.toContain('italic: false')
    expect(EDITOR_CODE).not.toContain('undoRedo: false')
  })
})

describe('写作编辑器 · 粘贴后的存储形态（纯函数）', () => {
  it('富文本粘贴 → 存库是 Markdown，不是 HTML 源码', () => {
    const md = htmlToMd('<p>粘贴的<strong>富文本</strong>与<em>斜体</em></p>')
    expect(md).toContain('**富文本**')
    expect(md).toContain('*斜体*')
    expect(md).not.toContain('<strong>')
    expect(md).not.toContain('<p>')
  })

  it('纯文本粘贴 → 一字不差，不变成标签', () => {
    const md = htmlToMd(mdToHtml('粘贴的纯文本 100% 保留'))
    expect(md).toBe('粘贴的纯文本 100% 保留')
    expect(md).not.toContain('<p>')
  })

  it('纯文本里自带尖括号时按文字保存，不会被当成 HTML 结构', () => {
    const md = htmlToMd('<p>&lt;b&gt;只是文字&lt;/b&gt;</p>')
    expect(md).toBe('<b>只是文字</b>')
    // 存的是文字本身，不是一段可执行/可见的标记结构
    expect(md.startsWith('<p>')).toBe(false)
  })
})
