/**
 * 卡④ 个人中心整页（`MeView.vue`，issue #112）的用例。
 *
 * 页面是**自己取数**的（四个 `me/*` 请求），所以这里把 `fetch` 换成一个显式的路由表：
 * 每条用例只声明"这一屏后端会返回什么"，不依赖真后端、也不依赖契约 mock 的开关。
 *
 * 六条纪律各有用例盯着：
 * ① 六个区块都在；
 * ② **一块挂了只让那块说原因**（不许整页白屏、不许拿假数据顶）；
 * ③ ⭐ 取不到的字段**不编**（`last_login_at` 就是"有地基没盖房"的那一处）；
 * ④ ⭐ **危险区三件套**（说清不可恢复 + 引导先导出 + 二次确认）一个都不能少；
 * ⑤ ⭐ **档位只有快 / 中两档**（精档已从界面撤下，写着"最准"属不实宣称）；
 * ⑥ 渲染出来的文本**不含源码痕迹、不含圈码与 emoji**。
 */

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import MeView from '../src/views/MeView.vue'

const ME = {
  id: 1,
  username: 'demo',
  display_name: '演示账号',
  role: 'admin',
  is_active: true,
  created_at: '2026-09-01T02:00:00Z',
}

const STORAGE = {
  total_bytes: 1288490188,
  by_kind: { uploads: 402653184, outputs: 805306368, backups: 67108864, db: 12582912 },
  location: 'data/',
}

const SESSIONS = {
  items: [
    { id: 1, created_at: '2026-10-01T02:00:00Z', last_seen_at: '2026-10-15T02:00:00Z', expires_at: '2026-11-13T02:00:00Z', user_agent: 'Chrome / Windows' },
    { id: 2, created_at: '2026-10-10T02:00:00Z', last_seen_at: '2026-10-14T02:00:00Z', expires_at: '2026-11-13T02:00:00Z', user_agent: 'Safari / iPhone' },
  ],
}

const LEDGER = {
  items: [
    { id: 1, task_id: 42, layer: 'L0', stage: 'extract', actor: 'local', tool: 'engine', summary: '本地取字：抽到 42 块', created_at: '2026-10-15T02:00:00Z' },
    { id: 2, task_id: 42, layer: 'L0', stage: 'translate', actor: 'api', tool: 'engine', summary: '正文发往模型 API 翻译：42 块', created_at: '2026-10-15T02:05:00Z' },
  ],
}

/** 一个极简的「后端」：`{ 'METHOD /path': (req) => [status, body] }`。 */
function stubApi(routes = {}, { user = ME } = {}) {
  const calls = []
  const table = {
    'GET /api/auth/me': () => [200, user],
    'GET /api/me/storage': () => [200, STORAGE],
    'GET /api/me/sessions': () => [200, SESSIONS],
    'GET /api/me/ledger': () => [200, LEDGER],
    'PATCH /api/me': ({ body }) => [200, { ...user, ...body }],
    'DELETE /api/me': () => [204, null],
    'DELETE /api/me/sessions/1': () => [200, { deleted: true, id: 1 }],
    'DELETE /api/me/sessions/2': () => [200, { deleted: true, id: 2 }],
    'POST /api/auth/password': () => [204, null],
    'GET /api/me/export': () => [200, 'zip-bytes'],
    'GET /api/me/ledger?format=csv': () => [200, 'stage,actor\n extract,local'],
    ...routes,
  }

  const fetchMock = vi.fn(async (url, options = {}) => {
    const method = (options.method || 'GET').toUpperCase()
    const path = String(url).replace(/^https?:\/\/[^/]+/, '')
    calls.push(`${method} ${path}`)
    const handler = table[`${method} ${path}`] || table[`${method} ${path.split('?')[0]}`]
    if (!handler) return { ok: false, status: 404, json: async () => ({ detail: '没这条路由' }), blob: async () => null }
    const [status, body] = handler({ body: options.body ? JSON.parse(options.body) : null, path })
    return {
      ok: status < 400,
      status,
      json: async () => body,
      blob: async () => ({ size: 1, type: 'application/octet-stream' }),
      text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
    }
  })

  vi.stubGlobal('fetch', fetchMock)
  return calls
}

async function mountMe(routes, options) {
  const calls = stubApi(routes, options)
  const wrapper = mount(MeView)
  await flushPromises()
  return { wrapper, calls }
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  // 下载那一步在 happy-dom 里没有实现，替换掉（同时盯住"确实走了一次下载"）
  URL.createObjectURL = vi.fn(() => 'blob:me-view')
  URL.revokeObjectURL = vi.fn()
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('MeView 个人中心', () => {
  it('六个区块都在：身份 / 账号安全 / 我的数据 / AI 使用台账 / 偏好 / 管理 · 危险区', async () => {
    const { wrapper } = await mountMe()

    const titles = wrapper.findAll('.me-sec-t').map((item) => item.text())
    expect(titles).toEqual(['身份', '账号安全', '我的数据', 'AI 使用台账', '偏好', '管理 · 危险区'])
  })

  it('① 身份：显示名能改，点保存真的 PATCH 出去，并给出结果', async () => {
    const { wrapper, calls } = await mountMe()

    const input = wrapper.find('#me-name')
    expect(input.element.value).toBe('演示账号')

    await input.setValue('时天赐')
    await wrapper.find('button.me-save').trigger('click')
    await flushPromises()

    expect(calls).toContain('PATCH /api/me')
    expect(wrapper.find('.me-hint').text()).toContain('已保存')
  })

  it('⭐ ① 上次登录取不到就说"暂未记录"——不拿创建时间冒充（契约 N30 还没落地）', async () => {
    const { wrapper } = await mountMe()

    const facts = wrapper.findAll('.me-fact')
    const lastLogin = facts.find((item) => item.find('dt').text() === '上次登录')
    expect(lastLogin.find('dd').text()).toBe('暂未记录')

    const note = wrapper.findAll('.hnote').map((item) => item.text()).join('\n')
    expect(note).toContain('不编一个时间')
    // 创建时间是有的，但它只能出现在"账号创建"那一格
    expect(facts.find((item) => item.find('dt').text() === '账号创建').find('dd').text()).not.toBe('—')
  })

  it('② 会话列表能逐个吊销：点一行，那一行就没了', async () => {
    const { wrapper, calls } = await mountMe()

    expect(wrapper.findAll('.me-kill')).toHaveLength(2)

    await wrapper.findAll('.me-kill')[0].trigger('click')
    await flushPromises()

    expect(calls).toContain('DELETE /api/me/sessions/1')
    expect(wrapper.findAll('.me-kill')).toHaveLength(1)
    expect(wrapper.text()).toContain('Safari / iPhone')
    expect(wrapper.text()).not.toContain('Chrome / Windows')
  })

  it('② 改密码：两次不一致 / 太短就点不动；对上了才发请求，并如实说"不踢设备"', async () => {
    const { wrapper, calls } = await mountMe()

    await wrapper.find('#me-old').setValue('old-pass-123')
    await wrapper.find('#me-new').setValue('short')
    await wrapper.find('#me-repeat').setValue('short')
    expect(wrapper.find('button.me-pwd').element.disabled).toBe(true)

    await wrapper.find('#me-new').setValue('new-password-1')
    await wrapper.find('#me-repeat').setValue('new-password-2')
    expect(wrapper.find('button.me-pwd').element.disabled).toBe(true)

    await wrapper.find('#me-repeat').setValue('new-password-1')
    expect(wrapper.find('button.me-pwd').element.disabled).toBe(false)

    await wrapper.find('button.me-pwd').trigger('click')
    await flushPromises()

    expect(calls).toContain('POST /api/auth/password')
    expect(wrapper.text()).toContain('其他设备上的会话仍然有效')
  })

  it('⭐ ③ 磁盘占用：条形图**带文字明细**（四类都有人话 + 字节数）', async () => {
    const { wrapper } = await mountMe()

    const kinds = wrapper.findAll('.me-kind')
    expect(kinds).toHaveLength(4)
    expect(wrapper.text()).toContain('上传的原始文献')
    expect(wrapper.text()).toContain('产物（译稿 / 导出）')
    expect(wrapper.text()).toContain('数据库备份')
    expect(wrapper.text()).toContain('数据库本体')

    const text = kinds.map((item) => item.find('.me-kind-num').text()).join(' ')
    expect(text).toContain('MB')
    // 条形只是"顺带看一眼"，文字才是信息本体
    expect(kinds[0].find('.me-kind-bar').exists()).toBe(true)
  })

  it('③ 一键导出与台账导出打到契约里那个端点（带 format）', async () => {
    const { wrapper, calls } = await mountMe()

    await wrapper.find('button.me-export').trigger('click')
    await flushPromises()
    expect(calls).toContain('GET /api/me/export?format=zip')

    await wrapper.find('button.me-ledger-csv').trigger('click')
    await flushPromises()
    expect(calls).toContain('GET /api/me/ledger?format=csv')

    await wrapper.find('button.me-ledger-md').trigger('click')
    await flushPromises()
    expect(calls).toContain('GET /api/me/ledger?format=md')
  })

  it('⭐ ④ 台账：环节 × 走了什么（本地 / 发往模型 API）都在，且有"暂无人改记录"诚实档', async () => {
    const { wrapper } = await mountMe()

    const rows = wrapper.findAll('.me-ledger tbody tr')
    expect(rows).toHaveLength(2)
    expect(wrapper.text()).toContain('取字')
    expect(wrapper.text()).toContain('逐段翻译')
    expect(wrapper.text()).toContain('本地处理')
    expect(wrapper.text()).toContain('发往模型 API')
    expect(wrapper.text()).toContain('正文发往模型 API 翻译：42 块')

    const notes = wrapper.findAll('.hnote').map((item) => item.text()).join('\n')
    expect(notes).toContain('暂无人改记录')
    expect(notes).toContain('M2 布点')
    // 口径红线：只说"服务自持 + 文献存本地"，不说"数据不出本机"
    expect(notes).toContain('服务自持')
    expect(wrapper.text()).not.toContain('数据不出本机')
  })

  it('⭐ ② 一块挂了只让那一块说原因：台账 500 不影响身份与其他块', async () => {
    const { wrapper } = await mountMe({
      'GET /api/me/ledger': () => [500, { detail: '台账服务不可用' }],
    })

    const notes = wrapper.findAll('.hnote').map((item) => item.text()).join('\n')
    expect(notes).toContain('AI 使用台账暂时取不到')
    expect(notes).toContain('台账服务不可用')

    // 别的块照常渲染（不是整页白屏）
    expect(wrapper.find('#me-name').element.value).toBe('演示账号')
    expect(wrapper.findAll('.me-kind')).toHaveLength(4)
  })

  it('⑤ 偏好：档位**只有快 / 中两档**（精档已撤下，不许出现"最准"这种不实宣称）', async () => {
    const { wrapper } = await mountMe()

    const radios = wrapper.findAll('.me-radio')
    expect(radios).toHaveLength(2)
    const text = radios.map((item) => item.text()).join(' ')
    expect(text).toContain('快档')
    expect(text).toContain('中档')
    expect(wrapper.text()).not.toContain('精档')
    expect(wrapper.text()).not.toContain('最准')
  })

  it('⑥ ⭐ 危险区三件套：说清不可恢复 + 引导先导出 + 二次确认（勾选 + 手打用户名）', async () => {
    const { wrapper } = await mountMe()

    const danger = wrapper.find('.me-danger')
    expect(danger.text()).toContain('无法恢复')
    expect(danger.find('button.me-export-first').exists()).toBe(true)

    const del = danger.find('button.me-delete')
    expect(del.element.disabled).toBe(true)

    // 只勾选 → 还是不能删
    await danger.find('input[type="checkbox"]').setValue(true)
    expect(del.element.disabled).toBe(true)

    // 打错用户名 → 仍然不能删
    await danger.find('#me-confirm-name').setValue('不是我的用户名')
    expect(del.element.disabled).toBe(true)

    // 勾选 + 打对用户名 → 才放行
    await danger.find('#me-confirm-name').setValue('demo')
    expect(del.element.disabled).toBe(false)
  })

  it('⑥ 管理入口只给管理员看；普通账号看到的是"不显示"的说明', async () => {
    const admin = await mountMe()
    expect(admin.wrapper.find('a.me-admin-link').attributes('href')).toBe('#/admin')

    const user = await mountMe({}, { user: { ...ME, role: 'user' } })
    expect(user.wrapper.find('a.me-admin-link').exists()).toBe(false)
    expect(user.wrapper.text()).toContain('不是管理员')
  })

  it('⑥ 删除账号：确认齐了才打 DELETE，删完清掉本机令牌', async () => {
    localStorage.setItem('docwise_token', 'token-before')
    const { wrapper, calls } = await mountMe()

    await wrapper.find('.me-danger input[type="checkbox"]').setValue(true)
    await wrapper.find('#me-confirm-name').setValue('demo')
    await wrapper.find('button.me-delete').trigger('click')
    await flushPromises()

    expect(calls).toContain('DELETE /api/me')
    expect(localStorage.getItem('docwise_token')).toBeNull()
    expect(wrapper.text()).toContain('账号已删除')
  })

  it('渲染出来的文本不含源码痕迹、不含圈码与 emoji', async () => {
    const { wrapper } = await mountMe()

    const text = wrapper.text()
    expect(text).not.toContain('function ')
    expect(text).not.toContain('=>')
    expect(text).not.toContain('{{')
    expect(text).not.toMatch(/[\u2460-\u2473]/) // ①②③… 圈码不上屏
    expect(text).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u)
  })
})
