/**
 * Agent 面板（读懂侧）——两条底线：
 * 1. 没配模型时要**先说得出来**（不能让用户打完字才发现用不了）；
 * 2. 轨迹里"它查了什么"只算工具调用，**收尾那条 `final_result` 不算查**。
 */

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../src/auth', () => ({
  authFetch: vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      configured: false,
      key_set: false,
      server_default: false,
      providers: [
        { id: 'deepseek', name: 'DeepSeek', base_url: 'https://api.deepseek.com/v1' },
      ],
      tier_models: { deepseek: { standard: 'deepseek-chat' } },
      model: '',
      tier: 'standard',
    }),
  })),
}))

import AgentChat from '../src/components/AgentChat.vue'
import { agentMessages, toolStepsOf } from '../src/stores/useAgent'

describe('AgentChat（读懂侧）', () => {
  beforeEach(() => {
    agentMessages.value.length = 0
  })

  it('没配模型时，顶部直接说「未配置模型」（不是等打完字才 500）', async () => {
    const wrapper = mount(AgentChat, { props: { scope: { task_id: 41 } } })
    await flushPromises()
    expect(wrapper.find('.agent-model').text()).toContain('未配置模型')
    expect(wrapper.find('.agent-model').classes()).toContain('warn')
  })

  it('点齿轮能打开设置：有厂商下拉、强度、密钥输入（密钥不回显）', async () => {
    const wrapper = mount(AgentChat, { props: { scope: {} } })
    await flushPromises()
    expect(wrapper.find('.agent-config').exists()).toBe(false)
    await wrapper.find('.agent-gear').trigger('click')
    expect(wrapper.find('.agent-config').exists()).toBe(true)
    const labels = wrapper.findAll('.agent-config label > span').map((n) => n.text())
    expect(labels).toContain('厂商')
    expect(labels).toContain('强度')
    expect(labels).toContain('API Key')
    const keyInput = wrapper
      .findAll('.agent-config input')
      .find((node) => node.attributes('type') === 'password')
    expect(keyInput, '没找到密钥输入框').toBeTruthy()
    expect(keyInput.attributes('type')).toBe('password')
  })

  it('空态给一句能照做的示例问题', async () => {
    const wrapper = mount(AgentChat, { props: { scope: {} } })
    await flushPromises()
    expect(wrapper.find('.agent-empty').text()).toContain('我库里有哪些讲手性的文献')
  })

  it('轨迹只算工具调用：`final_result` 那条被剔掉', () => {
    const turn = {
      steps: [
        { kind: 'tool_call', name: 'search_library', args: { query: '手性' } },
        { kind: 'tool_result', name: 'search_library', ok: true, excerpt: 'p0_b3' },
        { kind: 'tool_call', name: 'final_result', args: {} },
        { kind: 'tool_result', name: 'final_result', ok: true, excerpt: 'ok' },
      ],
    }
    const steps = toolStepsOf(turn)
    expect(steps).toHaveLength(2)
    expect(steps.every((s) => s.name === 'search_library')).toBe(true)
  })
})
