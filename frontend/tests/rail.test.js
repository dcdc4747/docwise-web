/**
 * M0 左栏骨架（issue #86 第 6 步 / 任务卡 R4）的用例。
 *
 * 左栏**没有"一眼看得见坏了"的白屏**：它塌了的时候页面照常能看，只是少了一列导航。
 * 所以这里的断言分两层：
 * ① **形状**——两段式三 + 七项、收起态、选中态（`AppRail` 是哑组件，断言它的 props / emits）；
 * ② **样式**——`260 ⇄ 58`、过渡 ≤200ms、tooltip 走 `data-tip` + `:focus-visible`
 *    这三条**都只写在 CSS 里**，单测挂载组件看不到，只能读源码钉住（与 R3 那两条用例同一个做法）。
 *
 * ⚠️ 断开"tooltip 用 CSS 而不是原生 `title`"这条：`title` 在 happy-dom 里能摸到属性，
 * 但"它会不会在悬停 1 秒后出现"测不出来——所以判据只能是**源码里按钮不许有 `title`，
 * 而 CSS 里有 `attr(data-tip)`**。这条正是 R1 点名要求的（演示视频里 `title` 来不及出现）。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AppRail from '../src/components/AppRail.vue'
import {
  RAIL_MIN_KEY,
  activeNav,
  loadRailMin,
  persistRailMin,
  railClass,
  railMin,
  toggleRail,
} from '../src/stores/useUi'

/** `bun run test` 的 cwd 是 `frontend/`（与 app.smoke.test.js 同一口径）。 */
const readStyle = () => readFileSync(resolve(process.cwd(), 'src/style.css'), 'utf8')

/** 把 CSS 里某条选择器后面那一整段规则抠出来（大括号配平）。 */
function ruleOf(css, selector) {
  const start = css.indexOf(selector)
  if (start < 0) return ''
  const open = css.indexOf('{', start)
  let depth = 0
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1
    else if (css[i] === '}') {
      depth -= 1
      if (depth === 0) return css.slice(open, i + 1)
    }
  }
  return css.slice(open)
}

beforeEach(() => {
  localStorage.clear()
  railMin.value = false
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('AppRail 左栏形状（R4 判据①）', () => {
  it('上段 3 个动作 + 下段 6 项 + 底部 2 条，全部是能点的按钮', () => {
    const wrapper = mount(AppRail)
    const items = wrapper.findAll('button.rail-item')

    // 3（读懂/起草/收口）+ 6（全部文献/集合/标签/待读/未归类/素材）+ 2（记忆/处理过程）
    // ⚠️ 2026-10-17：草稿/引用从这一组**拿掉**了（它们是写作资产，入口在「起草」页），
    //    换来「未归类」——点了只弹"还没做"的入口，比没有这个入口更伤。
    expect(items).toHaveLength(11)
    for (const item of items) {
      // 必须是真按钮：`<div @click>` 键盘用户按不动
      expect(item.element.tagName).toBe('BUTTON')
      expect(item.attributes('type')).toBe('button')
    }

    const labels = items.map((i) => i.find('.rail-lbl').text())
    expect(labels.slice(0, 3)).toEqual(['读懂', '起草', '收口'])
    expect(labels.slice(3, 9)).toEqual(['全部文献', '集合', '标签', '待读', '未归类', '素材'])
    expect(labels.slice(9)).toEqual(['记忆', '处理过程'])
  })

  it('两段的段标题是「做什么」与「历史记录」（上段动词、下段名词）', () => {
    const wrapper = mount(AppRail)

    expect(wrapper.findAll('.rail-sec-t').map((t) => t.text())).toEqual(['做什么', '历史记录'])
  })

  it('点一项 → emit select，带的是稳定 key（不是显示名）', async () => {
    const wrapper = mount(AppRail)
    const write = wrapper.findAll('button.rail-item').find((b) => b.text() === '起草')

    await write.trigger('click')

    expect(wrapper.emitted('select')).toHaveLength(1)
    expect(wrapper.emitted('select')[0]).toEqual(['write'])
  })

  it('选中态由 props 决定（组件自己不读地址、不知道自己"在哪一页"）', () => {
    const wrapper = mount(AppRail, { props: { activeNav: 'lib-tags' } })
    const on = wrapper.findAll('button.rail-item.on')

    expect(on).toHaveLength(1)
    expect(on[0].text()).toBe('标签')
  })

  it('⭐ 不许写假计数：本期一个徽章、一个数字都不渲染（真数据在 M1 的 N8/D4）', () => {
    const wrapper = mount(AppRail)

    expect(wrapper.findAll('.rail-badge')).toHaveLength(0)
    // 形态 §1.2 的布局图里每项后面都有计数（待读 3 / 素材 12 …）；
    // 本期拿不到真数，所以**一个数字都不印**——印 `0` 也是在编
    expect(wrapper.text()).not.toMatch(/\d/)
  })

  it('「本地优先 · 服务自持」是状态文字、不可点（R7 判据⑤：与账号区视觉可分）', () => {
    const wrapper = mount(AppRail)
    const sw = wrapper.find('.rail-sw')

    expect(sw.exists()).toBe(true)
    expect(sw.text()).toContain('本地优先')
    expect(sw.find('button').exists()).toBe(false)
    // ⚠️ 口径：不能说"数据不出本机"（三处仍调云端模型 API）
    expect(sw.text()).not.toContain('不出本机')
  })

  it('账号区位置留在最低处（R7 的 RailAccount 挂这个具名插槽；本卡不建组件）', () => {
    const wrapper = mount(AppRail, {
      slots: { account: '<div class="probe-account">账号</div>' },
    })

    const foot = wrapper.find('.rail-foot')
    expect(foot.find('.probe-account').exists()).toBe(true)
    // 插槽在 .rail-sw 之后 = 全栏最低处
    const order = foot.html()
    expect(order.indexOf('rail-sw')).toBeLessThan(order.indexOf('probe-account'))
  })
})

describe('AppRail 收起态（R4 判据②③）', () => {
  it('收起按钮：图标与可访问名跟着状态换（« ⇄ »）', async () => {
    const open = mount(AppRail, { props: { railMin: false } })
    expect(open.find('.rail-toggle use').attributes('href')).toBe('#i-chev-double-left')
    expect(open.find('.rail-toggle').attributes('aria-label')).toContain('收起左栏')

    const min = mount(AppRail, { props: { railMin: true } })
    expect(min.find('.rail-toggle use').attributes('href')).toBe('#i-chev-double-right')
    expect(min.find('.rail-toggle').attributes('aria-label')).toContain('展开左栏')

    await open.find('.rail-toggle').trigger('click')
    expect(open.emitted('toggle')).toHaveLength(1)
  })
})

describe('useUi 的收起态记忆（R4 判据③④）', () => {
  it('toggleRail 翻状态并写进 localStorage', () => {
    expect(railMin.value).toBe(false)

    toggleRail()
    expect(railMin.value).toBe(true)
    expect(localStorage.getItem(RAIL_MIN_KEY)).toBe('1')
    expect(railClass.value).toBe('rail-min')

    toggleRail()
    expect(railMin.value).toBe(false)
    expect(localStorage.getItem(RAIL_MIN_KEY)).toBe('0')
    expect(railClass.value).toBe('')
  })

  it('⭐ 刷新后仍是收起态：loadRailMin 把上次的值读回来', () => {
    localStorage.setItem(RAIL_MIN_KEY, '1')
    railMin.value = false // 模拟"刚刷新，状态是默认值"

    loadRailMin()

    expect(railMin.value).toBe(true)
  })

  it('没存过 / localStorage 读不出来时按展开渲染（不许因为读不到偏好就白屏）', () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError: 隐私模式')
    })

    railMin.value = true
    loadRailMin()

    expect(railMin.value).toBe(false)
    getItem.mockRestore()
  })

  it('写不进去也不报错（只影响"下次记住"，不影响本次交互）', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })

    railMin.value = false
    expect(() => toggleRail()).not.toThrow()
    expect(railMin.value).toBe(true)
    setItem.mockRestore()
    // 收尾：把 mock 掉的那次写入补回来，免得污染后面的用例
    persistRailMin()
  })
})

describe('左栏样式（R4 判据②⑤⑥）', () => {
  it('260 ⇄ 58 两个值都从 token 取（token 在 [R1] 段里已经落好）', () => {
    const css = readStyle()
    expect(ruleOf(css, '.dw {')).toContain('--rail-w: 260px')
    expect(ruleOf(css, '.dw {')).toContain('--rail-w-min: 58px')
    expect(ruleOf(css, '.dw .rail {')).toContain('var(--rail-w)')
    expect(ruleOf(css, '.dw .rail-min .rail {')).toContain('var(--rail-w-min)')
  })

  it('⭐ 收起态的开关是**后代**选择器（`.dw ` + `.rail-min …`），不是复合写法', () => {
    // 这一条是踩出来的：`rail-min` 挂在 `.dw-layout`（`.dw` 的子元素）上，
    // 复合写法（`.dw` 与 `.rail-min` 之间不加空格）在浏览器里**收起态一点效果都没有**
    // （类名在、宽度照旧 260px），而当时 207 条用例全绿 —— 因为用例只断言"类名挂上了"。
    const css = readStyle()
    // 注释里会提到坏写法，所以先去掉注释再数
    const code = css.replace(/\/\*[\s\S]*?\*\//g, '')

    expect(code).not.toMatch(/\.dw\.rail-min/)
    expect(code).toContain('.dw .rail-min .rail {')
    // 收起态的每一条都必须带 `.dw ` 前缀（不许漏掉命名空间去污染登录页）
    for (const line of code.split('\n')) {
      if (/^\.dw \.rail-min .*\{/.test(line.trim())) continue
      expect(line).not.toMatch(/^\.rail-min\b/)
    }
  })

  it('收起 / 展开只动宽度、≤200ms（§6.2 白名单 #3 + §6.3 禁止 transition:all）', () => {
    const rule = ruleOf(readStyle(), '.dw .rail {')

    expect(rule).toContain('flex-basis')
    expect(rule).toContain('--dur-base')
    expect(rule).not.toContain('transition: all')
    expect(rule).not.toMatch(/transition:[^;]*\b(height|padding|margin)\b/)
  })

  it('⭐ 收起态 tooltip 是 CSS 实现：内容来自 attr(data-tip)，不是原生 title', () => {
    const wrapper = mount(AppRail, { props: { railMin: true } })

    // ① 按钮上一个 title 都没有（原生 title 延迟不可控）
    for (const item of wrapper.findAll('button.rail-item')) {
      expect(item.attributes('title')).toBeUndefined()
      // ② 名字挂在 data-tip 上，收起态看不到 .rail-lbl 但内容还在
      expect(item.attributes('data-tip')).toBeTruthy()
    }

    // ③ CSS 真的把 data-tip 画出来了
    const css = readStyle()
    const tooltip = css.slice(css.indexOf('attr(data-tip)') - 400, css.indexOf('attr(data-tip)') + 400)
    expect(css).toContain('attr(data-tip)')
    expect(tooltip).toContain('position: absolute')
    expect(tooltip).toContain('content: attr(data-tip)')
  })

  it('⭐ tooltip 的 :hover 与 :focus-visible 两条都在（§7.6 第 5 条：键盘用户也要看得到）', () => {
    const css = readStyle()
    const start = css.indexOf('attr(data-tip)')
    expect(start).toBeGreaterThan(-1)

    // 往前找触发它的整条选择器
    const selectorStart = css.lastIndexOf('/*', start)
    const trigger = css.slice(selectorStart, css.indexOf('{', start))
    expect(trigger).toContain(':hover::after')
    expect(trigger).toContain(':focus-visible::after')

    // 键盘焦点环也在（§7.6 第 1 条：outline:none 必须配 :focus-visible 的可见替代）
    expect(css).toContain('.dw .rail-item:focus-visible')
    expect(ruleOf(css, '.dw .rail-item:focus-visible')).toContain('box-shadow')
  })

  it('收起态把名字 / 段标题 / 品牌副行藏起来——不是把它们挤没（§1.2b「只剩图标」）', () => {
    const css = readStyle()
    const start = css.indexOf('.dw .rail-min .rail-lbl,')
    expect(start).toBeGreaterThan(-1)
    // 从选择器列表到它后面第一条规则结尾
    const block = css.slice(start, css.indexOf('}', css.indexOf('{', start)) + 1)
    expect(block).toContain('display: none')
    expect(block).toContain('.rail-sec-t')
    expect(block).toContain('.rail-brand span')
  })
})
