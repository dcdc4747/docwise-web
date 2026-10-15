/**
 * 起草页文本层（`src/writeText.js`）的用例。
 *
 * 这一层全是"把用户已经写下的字切开/排好"的纯函数——**它不生成任何内容**。
 * 判据只有一条：切开的位置必须准（错了会把高亮/光标放到别的句子上去，而且不报错）。
 */

import { describe, expect, it } from 'vitest'

import {
  TEMPLATE_ID_MAX,
  citeSegments,
  insertMarker,
  outlineOf,
  previewBlocks,
  uploadTemplateId,
} from '../src/writeText'

describe('outlineOf：把 # 标题行读成提纲', () => {
  it('读出层级、文字与行首下标（点提要能把光标放到那一行）', () => {
    const body = '# 题目\n\n正文一句\n\n## 一、引言\n### 细节\n'
    const items = outlineOf(body)
    expect(items.map((item) => [item.level, item.text])).toEqual([
      [1, '题目'],
      [2, '一、引言'],
      [3, '细节'],
    ])
    // 第二个标题（`## 一、引言`）的行首下标 = 前面那些字符的长度
    const expectOffset = body.indexOf('## 一、引言')
    expect(items[1].offset).toBe(expectOffset)
    // 光标落到那一行时，切出来的正是这一行
    expect(body.slice(items[1].offset, items[1].offset + items[1].text.length + 3)).toBe('## 一、引言')
  })

  it('只认「# 空格 文字」：井号没空格、纯井号、正文里的井号都不算标题', () => {
    const body = '#题目\n#\n这是正文里的 # 号\n#### 四级\n'
    expect(outlineOf(body).map((item) => item.text)).toEqual(['四级'])
  })

  it('空正文 → 空提纲（不编一个默认结构出来）', () => {
    expect(outlineOf('')).toEqual([])
    expect(outlineOf(null)).toEqual([])
  })
})

describe('citeSegments：把 [n] 切开', () => {
  it('文字与标记分段，顺序不变', () => {
    expect(citeSegments('前一句 [1] 中间 [12] 末句')).toEqual([
      { kind: 'text', text: '前一句 ' },
      { kind: 'cite', text: '[1]', order: 1 },
      { kind: 'text', text: ' 中间 ' },
      { kind: 'cite', text: '[12]', order: 12 },
      { kind: 'text', text: ' 末句' },
    ])
  })

  it('没有标记 → 一整段文字；标记在开头/结尾也能切对', () => {
    expect(citeSegments('就一句话')).toEqual([{ kind: 'text', text: '就一句话' }])
    expect(citeSegments('[1]开头')).toEqual([
      { kind: 'cite', text: '[1]', order: 1 },
      { kind: 'text', text: '开头' },
    ])
    expect(citeSegments('结尾[2]')).toEqual([
      { kind: 'text', text: '结尾' },
      { kind: 'cite', text: '[2]', order: 2 },
    ])
  })

  it('全角括号不当标记（那多半是用户自己写的字，不是引文编号）', () => {
    expect(citeSegments('［1］不是标记')).toEqual([{ kind: 'text', text: '［1］不是标记' }])
  })

  it('同一个标记连着出现两次也各算一条（连着插两条引文真会发生）', () => {
    expect(citeSegments('[1][2]').map((seg) => seg.order)).toEqual([1, 2])
  })
})

describe('previewBlocks：预览用的最小分块', () => {
  it('标题各自成块、其余按空行分段，段落里的 [n] 单独成段', () => {
    const blocks = previewBlocks('# 题目\n\n第一段 [1]\n还是第一段\n\n## 二\n第二段\n')
    expect(blocks.map((blk) => blk.kind)).toEqual(['heading', 'paragraph', 'heading', 'paragraph'])
    expect(blocks[0]).toMatchObject({ kind: 'heading', level: 1 })
    expect(blocks[0].segments).toEqual([{ kind: 'text', text: '题目' }])
    expect(blocks[1].segments.map((seg) => seg.kind)).toEqual(['text', 'cite', 'text'])
    expect(blocks[1].segments[0].text).toBe('第一段 ')
    expect(blocks[1].segments[1].order).toBe(1)
    expect(blocks[1].segments[2].text).toBe('\n还是第一段')
    expect(blocks[3].segments[0].text).toBe('第二段')
  })

  it('空正文 → 没有块（不是"一个空段落"）', () => {
    expect(previewBlocks('   \n\n')).toEqual([])
  })

  it('连续空行不会切出空段落', () => {
    expect(previewBlocks('甲\n\n\n\n乙').map((blk) => blk.segments[0].text)).toEqual(['甲', '乙'])
  })
})

describe('insertMarker：在某处插入 [n]', () => {
  it('插在 offset 处，并给出插完后的光标位置', () => {
    const result = insertMarker('出处的意义。', 5, 3)
    expect(result.text).toBe('出处的意义[3]。')
    expect(result.caret).toBe(8)
  })

  it('offset 越界时夹到两端（不抛错、不吞字）', () => {
    expect(insertMarker('abc', 99, 1)).toEqual({ text: 'abc[1]', caret: 6 })
    expect(insertMarker('abc', -5, 2)).toEqual({ text: '[2]abc', caret: 3 })
    expect(insertMarker('', null, 4)).toEqual({ text: '[4]', caret: 3 })
  })
})

describe('uploadTemplateId：模板标识', () => {
  it('加 upload: 前缀，空名字兜底', () => {
    expect(uploadTemplateId('我的模板.md')).toBe('upload:我的模板.md')
    expect(uploadTemplateId('  ')).toBe('upload:未命名模板')
  })

  it('超过 64 字符要截断（后端列宽是 str(64)，别让请求 422）', () => {
    const long = `${'模'.repeat(200)}.md`
    const id = uploadTemplateId(long)
    expect(id.length).toBe(TEMPLATE_ID_MAX)
    expect(id.startsWith('upload:')).toBe(true)
  })
})
