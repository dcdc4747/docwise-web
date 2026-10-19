/**
 * 从 HTML 加载时，图片必须留在编辑器里（2026-10-19 真页面 bug）。
 *
 * 现象：粘贴/插入图片正常，但重新打开一份 body_html 里带 `<img>` 的稿子，
 * 编辑器里图片消失、文字还在；再保存一次就把图从正文抹掉了。
 * 这条用例直接挂载 WriteEditor，喂一段带 img 的 modelValue，断言编辑器里真有 img。
 */
import { mount } from '@vue/test-utils'

import { describe, expect, it } from 'vitest'

import WriteEditor from '../src/components/WriteEditor.vue'

const PNG =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='

describe('编辑器加载带图片的 HTML', () => {
  it('modelValue 里的 <img> 不会被丢掉', async () => {
    const wrapper = mount(WriteEditor, {
      props: {
        modelValue: `<p>这段是文字。</p><img src="${PNG}" alt="测试图"><p>图注</p>`,
      },
      attachTo: document.body,
    })
    await new Promise((r) => setTimeout(r, 120))

    const html = wrapper.find('.we-prose').element.innerHTML
    expect(html).toContain('<img')
    expect(html).toContain('测试图')
    wrapper.unmount()
  })
})
