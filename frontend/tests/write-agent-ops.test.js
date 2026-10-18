/**
 * AI 直接写正文（2026-10-19 取消"不代写"红线）。
 *
 * 判据三层：
 *  ① 后端给的 ops 一到，正文**真的变了**（不需要用户逐条点）；
 *  ② 四种 mode 行为正确（append / prepend / replace / insert_after）；
 *  ③ 有退路：撤销回到写入前那一版；锚点找不到就跳过并提示。
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const SRC = readFileSync(
  path.resolve(process.cwd(), 'src/views/WriteView.vue'),
  'utf8',
)

describe('写作页 · AI 直接写正文', () => {
  it('页面订阅了 apply-ops（不是让用户逐条点）', () => {
    expect(SRC).toContain('@apply-ops="applyOps"')
    expect(SRC).toContain('function applyOps(ops)')
  })

  it('四种写入模式都实现了', () => {
    for (const mode of ['append', 'prepend', 'replace', 'insert_after']) {
      expect(SRC, `缺少 ${mode}`).toContain(`'${mode}'`)
    }
  })

  it('锚点找不到时跳过并提示，不糊弄成"已写入"', () => {
    expect(SRC).toMatch(/skipped\.push\('原文没找到'\)/)
    expect(SRC).toMatch(/没能写进正文/)
  })

  it('写进正文后标 dirty，并给一次撤销', () => {
    expect(SRC).toMatch(/saveState\.value = 'dirty'/)
    expect(SRC).toContain('function revertOps(')
    expect(SRC).toMatch(/label: '撤销', run: \(\) => revertOps\(before\)/)
  })

  it('前端 store 会把 ops 收进这一轮回答', () => {
    const store = readFileSync(
      path.resolve(process.cwd(), 'src/stores/useAgent.js'),
      'utf8',
    )
    expect(store).toContain('turn.ops = event.ops || []')
  })
})
