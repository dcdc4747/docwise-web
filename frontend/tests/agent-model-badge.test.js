/**
 * 输入框旁边的模型标签要显示**这个板块实际会用**的模型（2026-10-19）。
 *
 * 事故类型与之前一样：后端按板块取模型，界面只显示全局那个 →
 * 用户在设置里把写作切成 reasoner，标签还写着 chat，看着像"改了没生效"。
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const SOURCE = readFileSync(
  path.resolve(process.cwd(), 'src/components/AgentChat.vue'),
  'utf8',
)

describe('模型标签 · 按板块', () => {
  it('标签优先取板块指定，其次全局', () => {
    expect(SOURCE).toContain('sceneModelOf')
    expect(SOURCE).toMatch(/sceneModelOf\.value \|\| config\.value\.model/)
  })

  it('来自板块指定时有个小标（免得以为全局改了）', () => {
    expect(SOURCE).toContain('modelIsSceneOwn')
    expect(SOURCE).toContain('本板块')
  })
})
