/**
 * AI 标识（合规卡 #147）的用例。
 *
 * 分两张桌子，因为责任不同：
 * ① **组件层** —— 文案与图标要真渲染出来，而且**文案只有这一份**
 *    （四个位置都从 `AiBadge.vue` 取字，各页面自己写一句迟早漂成好几种说法）；
 * ② **位置层** —— `ReadView` 依赖整条阅读链路的状态，为它搭一套完整 mount 得不偿失
 *    （照 `block-edit.test.js` / `materials-entry.test.js` 的既有做法：模板源码断言位置），
 *    并钉住两条最容易做歪的：**译文那颗必须与「已人工修改」互斥**、**术语那颗在表头**。
 *
 * ⚠️ 口径红线：**绝不许出现"数据不出本机"**——外文翻译 / 扫描件逐段翻译 / 导读问答
 * 三处仍调云端模型 API，准确口径是「服务自持 + 文献存本地」。
 */

import { readFileSync } from 'node:fs'
import path from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AiBadge from '../src/components/AiBadge.vue'

const KINDS = ['translate', 'answer', 'guide', 'terms']

function readSrc(rel) {
  return readFileSync(path.resolve(process.cwd(), rel), 'utf8')
}

// ============================================================ ① 组件层

describe('AiBadge：一颗芯片、一份文案', () => {
  it('四个位置各有文案，且说明里给了"怎么核"（不只写一句 AI 生成）', () => {
    for (const kind of KINDS) {
      const wrapper = mount(AiBadge, { props: { kind } })
      expect(wrapper.find('.ai-badge').exists()).toBe(true)
      expect(wrapper.text()).toMatch(/AI (翻译|生成)/)

      const title = wrapper.find('.ai-badge').attributes('title')
      expect(title).toBeTruthy()
      // 只说"AI 生成"而不给核对路径 = 用户既不能判断该不该信，也不知道下一步做什么
      expect(title).toMatch(/核|校对|回填/)
    }
  })

  it('译文说「AI 翻译」、问答/导读/术语说「AI 生成」（两种口径不许混用）', () => {
    expect(mount(AiBadge, { props: { kind: 'translate' } }).text()).toContain('AI 翻译')
    for (const kind of ['answer', 'guide', 'terms']) {
      expect(mount(AiBadge, { props: { kind } }).text()).toContain('AI 生成')
    }
  })

  it('⭐ 文案里不许出现"数据不出本机"（三处仍调云端模型 API）', () => {
    // ⚠️ 判的是**用户能看见的字符串**：注释里为了立规矩会引用这句话本身，
    // 所以先把注释剥掉再查——否则这条守卫会被自己的文档顶红。
    const code = readSrc('src/components/AiBadge.vue')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/<!--[\s\S]*?-->/g, '')
      .replace(/\/\/.*$/gm, '')
    expect(code).not.toContain('数据不出本机')

    for (const kind of KINDS) {
      const wrapper = mount(AiBadge, { props: { kind } })
      expect(wrapper.text()).not.toContain('数据不出本机')
      expect(wrapper.find('.ai-badge').attributes('title')).not.toContain('数据不出本机')
    }
  })

  it('用 sprite 里的"生成"图标（不是 emoji），并带上无障碍属性', () => {
    const wrapper = mount(AiBadge, { props: { kind: 'guide' } })
    expect(wrapper.find('svg use').attributes('href')).toBe('#i-spark')
    expect(wrapper.find('svg').attributes('aria-hidden')).toBe('true')
    // 界面上不许再冒 emoji 出来（R3 清过一次，这里加一道新守卫）
    expect(/\p{Extended_Pictographic}/u.test(wrapper.text())).toBe(false)
  })

  it('没见过的位置退回「AI 生成」，不渲染一颗没有文案的空壳', () => {
    const wrapper = mount(AiBadge, { props: { kind: 'nope' } })
    expect(wrapper.text()).toContain('AI 生成')
    expect(wrapper.find('.ai-badge-t').text().trim()).not.toBe('')
  })

  it('样式挂在 `.dw` 命名空间里（不污染登录页 / 管理后台）', () => {
    const css = readSrc('src/style.css')
    expect(css).toContain('.dw .ai-badge {')
    expect(css).toContain('var(--ai-bg)')
    expect(css).toContain('var(--ai-line)')
    // 裸的 `.ai-badge` 选择器 = 跑到 `.dw` 外面去了
    expect(/(^|\n)\.ai-badge\s*\{/.test(css)).toBe(false)
  })
})

// ============================================================ ② 出现位置

describe('出现位置：至少三处可见标注', () => {
  const src = readSrc('src/views/ReadView.vue')

  it('四处都在：段落精读译文 / 问答答案 / 导读要点 / 术语表', () => {
    expect(src).toContain("import AiBadge from '../components/AiBadge.vue'")
    for (const kind of KINDS) {
      expect(src).toContain(`kind="${kind}"`)
    }
  })

  it('⭐ 译文那颗与「已人工修改」互斥：人改过的句子不许被说成模型译的', () => {
    expect(src).toMatch(
      /v-if="blockHasTranslated\(row\.block\) && !editedBlockIds\.has\(row\.block\.block_id\)"/,
    )
  })

  it('问答那颗贴在回答气泡里、导读那颗贴在导读面板里（标注要挨着内容）', () => {
    const bubble = src.slice(
      src.indexOf('<div class="bubble-a">'),
      src.indexOf('<div class="a-tools">'),
    )
    expect(bubble).toContain('kind="answer"')

    // ⚠️ 导读那颗走**面板头**（不是每张卡片的 `.k` 里）：`app.smoke` 把 `.k` 的文本
    // 锁成 ['研究问题','方法',…]，塞进去会把老用例顶红，也没必要糊满芯片。
    const guide = src.slice(
      src.indexOf("assistTab === 'guide'"),
      src.indexOf("assistTab === 'terms'"),
    )
    expect(guide).toContain('kind="guide"')
    expect(guide.indexOf('kind="guide"')).toBeLessThan(guide.indexOf('class="guide-card"'))
    // 卡片标题仍然是纯要点名（标识别占用户读的那一行）
    expect(guide).toContain('<div class="k">{{ point.label }}</div>')
  })

  it('术语那颗在表头（`.termlist` 之前），不是每行挂一颗', () => {
    const terms = src.slice(src.indexOf("assistTab === 'terms'"))
    expect(terms.indexOf('kind="terms"')).toBeGreaterThan(-1)
    expect(terms.indexOf('kind="terms"')).toBeLessThan(terms.indexOf('class="termlist"'))
  })

  it('起草页不代写正文（一个字都不生成），所以那里不该出现 AI 标识', () => {
    expect(readSrc('src/views/WriteView.vue')).not.toContain('AiBadge')
    // 顺带锁住那句红线注释：起草页没有任何"生成/续写/润色"入口
    expect(readSrc('src/views/WriteView.vue')).toContain('本页一个字都不替用户生成正文')
  })
})
