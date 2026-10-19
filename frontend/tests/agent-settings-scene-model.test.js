/**
 * 设置弹窗里的「按板块指定模型」（2026-10-19）。
 *
 * 为什么值得一条用例：这是**唯一会让账单变贵**的开关。
 * 它必须满足三条：默认留空（跟随全局）、空值不落库、代价写在界面上。
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const SOURCE = readFileSync(
  path.resolve(process.cwd(), 'src/components/AgentSettings.vue'),
  'utf8',
)

describe('设置 · 按板块换模型', () => {
  it('两个板块都有下拉（读懂 / 写作），且默认「跟随全局」', () => {
    expect(SOURCE).toContain('form.sceneModels.read_ask')
    expect(SOURCE).toContain('form.sceneModels.write_compose')
    // 默认值为空串 = 跟随全局，不能一开就换贵模型
    expect(SOURCE).toMatch(/sceneModels:\s*\{\s*read_ask:\s*''/)
    expect(SOURCE).toContain('<option value="">跟随全局</option>')
  })

  it('空值不提交（否则会存成脏数据）', () => {
    expect(SOURCE).toMatch(/filter\(\(\[, v\]\) => String\(v \|\| ''\)\.trim\(\)\)/)
    expect(SOURCE).toContain('scene_models')
  })

  it('界面上写清了代价（更贵更慢），不是偷偷换', () => {
    expect(SOURCE).toContain('更贵更慢')
    expect(SOURCE).toContain('deepseek-reasoner')
  })
})
