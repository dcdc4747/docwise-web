/**
 * 收尾校验的 note 要分两排显示（2026-10-19）。
 *
 * 为什么：`出处可定位率 75%（3/4）` 这种**能核对可信度**的数字，
 * 现在和"编号格式不对已剔除"挤在一行灰字里，用户看不出这次回答有多可信。
 * 指标要突出、提醒要看得见——所以按"带不带数字"分类。
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const SOURCE = readFileSync(
  path.resolve(process.cwd(), 'src/components/AgentChat.vue'),
  'utf8',
)

describe('结果指标的可视化', () => {
  it('notes 分成指标与提醒两排', () => {
    expect(SOURCE).toContain('classifiedNotes')
    expect(SOURCE).toContain('agent-note-metric')
    expect(SOURCE).toContain('agent-note-warn')
  })

  it('分类判据是"带数字"而不是写死的文案', () => {
    // 用正则匹配百分比/分数/率，这样以后新加的 note 会自动归类
    expect(SOURCE).toMatch(/METRIC_RE\s*=\s*\/.*%/)
    expect(SOURCE).toContain('率')
  })

  it('指标样式做成芯片（可扫读），不是又一行灰字', () => {
    expect(SOURCE).toMatch(/\.agent-note-metric\s*\{[^}]*border-radius/)
  })
})
