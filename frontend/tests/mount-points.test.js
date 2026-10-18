/**
 * M0 第 7 步（issue #86）——**预留挂载点**的用例。
 *
 * 这一步交的是"座位"，不是"功能"：`AppTabbar` 的 5 个标签是 R6 的活、
 * `AppStatusBar` 的三个信息位是 R8 的活（还依赖后端 B2 的 `memory_events`）。
 *
 * 所以这里要钉住的恰好是那两件**看起来什么都没做、但最容易被后人破坏**的事：
 * ① ⭐ **自门控**：不传数据时**整条不渲染** —— 既不占屏幕，也不算"提前招认没做的能力"。
 *    这条一旦被破坏（比如有人给个 `default: () => [ {...} ]`），屏幕上会多出一条假导航栏，
 *    而且是**静默**多出来的（用例与 build 都不会红）。
 * ② ⭐ **挂载点真的在 `App.vue` 里**：第 7 步的全部价值就在这一条 ——
 *    如果 R6/R8 之后还得回来改外壳，那这一步等于白做。所以按源码钉住"import 了 + 挂上了"。
 *
 * ⚠️ 为什么不像 R4 那样在 `app.smoke.test.js` 里挂整个 App 来断言？
 * 因为"没渲染出东西"这种否定断言，挂在整页上会把别处的同类类名也算进来；
 * 这里**单独挂组件**反而更准。App 那一侧只钉"挂载点接线存在"。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AppStatusBar from '../src/components/AppStatusBar.vue'
import AppTabbar from '../src/components/AppTabbar.vue'

/** `bun run test` 的 cwd 是 `frontend/`（与 app.smoke.test.js 同一口径）。 */
const srcText = (rel) => readFileSync(resolve(process.cwd(), 'src', rel), 'utf8')

/** R6 之后要传进来的 5 个标签（形态 §3.4：库 / 写作 / 检查 / 记忆 / 我的）。 */
const FIVE_TABS = [
  { key: 'library', label: '库', icon: 'layers' },
  { key: 'write', label: '写作', icon: 'pen' },
  { key: 'check', label: '检查', icon: 'check-search' },
  { key: 'memory', label: '记忆', icon: 'gear' },
  { key: 'me', label: '我的', icon: 'user' },
]

describe('AppTabbar 底部标签栏（座位）', () => {
  it('⭐ 不传 tabs 时整条不渲染（自门控：不占屏幕、不招认没做的能力）', () => {
    const wrapper = mount(AppTabbar)

    expect(wrapper.find('.tabbar').exists()).toBe(false)
    expect(wrapper.html()).not.toContain('<nav')
  })

  it('⭐ 传空数组同样不渲染（拿不到数据不许硬编一个默认标签集）', () => {
    const wrapper = mount(AppTabbar, { props: { tabs: [] } })

    expect(wrapper.find('.tabbar').exists()).toBe(false)
  })

  it('⚠️ 源码里不许给 tabs 塞默认标签 —— 那会让自门控静默失效', () => {
    const src = srcText('components/AppTabbar.vue')

    // 默认值必须是空数组；写成字面量标签数组就是"硬编了一份没做的导航"
    expect(src).toMatch(/tabs:\s*\{\s*type:\s*Array,\s*default:\s*\(\)\s*=>\s*\[\]\s*\}/)
    // 5 个标签的文案不许出现在这个文件里（它们属于 R6 的数据源）
    for (const label of ['库', '写作', '检查', '记忆', '我的']) {
      expect(src).not.toContain(`label: '${label}'`)
    }
  })

  it('R6 接上数据后就出来：5 个标签、选中态、点一项 emit select', async () => {
    const wrapper = mount(AppTabbar, { props: { tabs: FIVE_TABS, active: 'memory' } })

    const items = wrapper.findAll('button.tabbar-item')
    expect(items).toHaveLength(5)
    expect(items.map((i) => i.find('.tabbar-lbl').text())).toEqual(['库', '写作', '检查', '记忆', '我的'])
    // 第一个是「库」不是「读懂」（R6 判据①点名）
    expect(items[0].text()).not.toContain('读懂')

    expect(items.filter((i) => i.classes().includes('on'))).toHaveLength(1)
    expect(items[3].classes()).toContain('on')

    await items[1].trigger('click')
    expect(wrapper.emitted('select')).toHaveLength(1)
    expect(wrapper.emitted('select')[0]).toEqual(['write'])
  })

  it('是导航、且每个标签都是真按钮（键盘可达）', () => {
    const wrapper = mount(AppTabbar, { props: { tabs: FIVE_TABS } })

    const nav = wrapper.find('nav.tabbar')
    expect(nav.exists()).toBe(true)
    expect(nav.attributes('aria-label')).toBeTruthy()
    for (const item of wrapper.findAll('button.tabbar-item')) {
      expect(item.element.tagName).toBe('BUTTON')
      expect(item.attributes('type')).toBe('button')
    }
  })
})

describe('AppStatusBar 底部状态条（座位）', () => {
  it('⭐ 不传 slots 时整条不渲染（R8 判据③：取不到数据不许写假数据）', () => {
    const wrapper = mount(AppStatusBar)

    expect(wrapper.find('.sbar').exists()).toBe(false)
  })

  it('⭐ 三个信息位一个都没有时也不渲染（不补空壳）', () => {
    const wrapper = mount(AppStatusBar, { props: { slots: {} } })

    expect(wrapper.find('.sbar').exists()).toBe(false)
  })

  it('⚠️ 源码里不许写死"本次用了某模型"这类假数据（R8 不许做第②条）', () => {
    const src = srcText('components/AppStatusBar.vue')

    // 只许有三把钥匙（形状），不许有值
    expect(src).toMatch(/const SLOT_KEYS = \['flow', 'model', 'todo'\]/)
    expect(src).not.toMatch(/text:\s*'[^']+'/)
    // 模型名只能从 memory_events.tool 来 —— 这里不许出现任何具体模型名
    expect(src).not.toMatch(/(deepseek|gpt|claude|qwen|glm)/i)
  })

  it('R8 接上数据后就出来：按固定顺序显示三个信息位，缺的位不显示', () => {
    const wrapper = mount(AppStatusBar, {
      props: {
        slots: {
          todo: { icon: 'listcheck', text: '待处理 3 处' },
          // ⚠️ 故意把 todo 写在 flow 前面：显示顺序必须按 SLOT_KEYS，不按对象键序
          flow: { icon: 'lock', text: '不出本机' },
          model: null,
        },
      },
    })

    const texts = wrapper.findAll('.sbar-item').map((i) => i.text())
    expect(texts).toEqual(['不出本机', '待处理 3 处'])
    // 缺的那一位不留空壳
    expect(texts).not.toContain('')
  })

  it('信息位的文字走 --ink 体系、不写死颜色（R8 判据②的色盲安全靠图标形状+位置）', () => {
    const wrapper = mount(AppStatusBar, { props: { slots: { flow: { icon: 'lock', text: '不出本机' } } } })

    // 图标从 sprite 取（不是 emoji），且形状由调用方给不同名字
    const use = wrapper.find('.sbar-item svg use')
    expect(use.exists()).toBe(true)
    expect(use.attributes('href')).toBe('#i-lock')
  })
})

describe('挂载点真的钉在外壳里（第 7 步的全部价值）', () => {
  const app = srcText('App.vue')

  it('两个组件都被 import 了', () => {
    expect(app).toContain("import AppStatusBar from './components/AppStatusBar.vue'")
    expect(app).toContain("import AppTabbar from './components/AppTabbar.vue'")
  })

  it('两个组件都在模板里挂上了（不是只 import 不用）', () => {
    expect(app).toMatch(/<AppStatusBar\s*\/>/)
    // ⚠️ R6（2026-10-16）起标签栏**收参数**了，所以不再匹配 `<AppTabbar />` 这种裸写法
    expect(app).toMatch(/<AppTabbar[^>]*\/>/)
  })

  it('⭐ 状态条仍是"不传数据"的座位；标签栏自 R6 起改为外壳传参（口径已改，见理由）', () => {
    // 座位期口径（第 7 步）：挂载处不许传数据，R6/R8 只改自己的文件就能放出来。
    // ⚠️ R6 落地时**有意改了这条**：标签栏要的导航地址表就在本文件里（`RAIL_TARGETS` 是唯一真源），
    //    复用同一份表比让标签栏再存一份地址更不容易漂移 —— 代价是**以后动 App.vue 要留意这一处**。
    //    状态条（R8）不受影响，继续按座位口径钉住。
    expect(app).not.toMatch(/<AppStatusBar[^>]*\sslots=/)
    // 绑定写法是 `:tabs="MOBILE_TABS"`（带冒号），别漏了它
    expect(app).toMatch(/<AppTabbar[^>]*\s:tabs=/)
  })

  it('⭐ 账号区插槽**已被 R7 填上**（座位期那条"保持空插槽"的口径到此结束）', () => {
    // 座位期（第 6/7 步）要求这里是**空插槽**，理由是"空插槽才不多出一个空的按钮"。
    // ⚠️ R7 落地后这条**有意作废**：账号区就是要那个按钮（形态 v2 §1.2 第 60 行：
    //    「账号区（点进个人中心，进入后高亮）」；M0 判据同款）。
    // **不会多出空的 Tab 停靠点**：整个外壳只在已登录时渲染（`!authUser` 走 `LoginView`，压根没有左栏）。
    expect(app).toMatch(/<template #account>[\s\S]{0,160}<RailAccount/)
    expect(app).toContain("import RailAccount from './components/RailAccount.vue'")
  })

  it('三个挂载点在结构上的位置写对了：状态条在内容列内、标签栏在布局之外', () => {
    const layoutStart = app.indexOf('class="dw-layout"')
    const mainStart = app.indexOf('class="dw-main"')
    const statusBar = app.indexOf('<AppStatusBar')
    const layoutEnd = app.indexOf('<AppTabbar')
    expect(layoutStart).toBeGreaterThan(-1)
    expect(mainStart).toBeGreaterThan(layoutStart)
    // 状态条在 .dw-main 之后（内容列底部），标签栏在它之后（.dw-layout 外的整屏宽位置）
    expect(statusBar).toBeGreaterThan(mainStart)
    expect(layoutEnd).toBeGreaterThan(statusBar)
  })
})
