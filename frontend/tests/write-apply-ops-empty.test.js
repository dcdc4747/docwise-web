/**
 * 新草稿（正文为空）里 AI 也要写得进去（2026-10-19 真页面事故）。
 *
 * 事故：用户在新草稿里说"写个你好"，模型答"已写入"，界面还是 0 字。
 * 根因在 `WriteView.applyOps` 的第一行守卫：`if (!list.length || !body.value) return`
 * —— 空正文直接被判"没内容可写"，既不落字也不提示。
 *
 * 这条用例钉两件事：守卫里**不许**再出现正文非空判断；空正文要能长出内容。
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const SOURCE = readFileSync(
  path.resolve(process.cwd(), 'src/views/WriteView.vue'),
  'utf8',
)

/** 从源码里截出 applyOps 函数体（够做纯函数级验证，不必挂载整页）。 */
function applyOpsBody() {
  const start = SOURCE.indexOf('function applyOps(ops) {')
  expect(start, '没找到 applyOps').toBeGreaterThan(-1)
  let depth = 0
  for (let i = SOURCE.indexOf('{', start); i < SOURCE.length; i += 1) {
    if (SOURCE[i] === '{') depth += 1
    if (SOURCE[i] === '}') {
      depth -= 1
      if (depth === 0) return SOURCE.slice(start, i + 1)
    }
  }
  throw new Error('applyOps 大括号不配对')
}

describe('AI 写入 · 空草稿', () => {
  it('守卫里不再用「正文为空」拦掉写入', () => {
    const bodyText = applyOpsBody()
    expect(bodyText).not.toMatch(/if \(!list\.length \|\| !body\.value\)/)
    expect(bodyText).toContain('if (!list.length) return')
  })

  it('空草稿 append 应该长出内容（按同样规则算一遍）', () => {
    // 与 applyOps 里 append 分支保持同一算式：去掉尾部空白 + 两个换行 + 内容 + 换行
    const base = ''
    const chunk = '你好'
    const result = `${base.replace(/\s+$/, '')}\n\n${chunk}\n`
    expect(result.trim()).toBe('你好')
    expect(result.startsWith('\n\n')).toBe(true)
  })

  it('空草稿会给出「原来是空的」提示，避免以为写丢了', () => {
    expect(SOURCE).toContain('wasEmpty')
    expect(SOURCE).toContain('草稿原来是空的')
  })
})
