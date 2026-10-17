/**
 * 登录页重写（E17）的用例。
 *
 * 契约 `契约_前端命名与拆分` §7 把重写的**风险**点得很清楚：
 * > 风险不在视觉，在测试与校验（Naive UI 自带校验与 a11y 要自己补）。
 *
 * 所以这里分两段：
 * 1. **校验**（纯函数，`src/authForm.js`）——**逐条镜像后端** `auth.py` 的字段限制；
 * 2. **接线**（结构断言）——登录逻辑一个都没换、Naive UI 在登录页彻底退场、
 *    手写控件的语义（role / aria / 显隐密码 / 提交中禁用）都在。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  AUTH_HINTS,
  PASSWORD_MIN_REGISTER,
  USERNAME_MAX,
  USERNAME_MIN_REGISTER,
  isSubmitDisabled,
  validateCredentials,
} from '../src/authForm'

const readSrc = (rel) => readFileSync(resolve(process.cwd(), rel), 'utf8')

describe('登录 / 注册校验（镜像后端）', () => {
  it('空用户名或空密码 → 一句人话（登录与注册都一样）', () => {
    expect(validateCredentials({ mode: 'login', username: '', password: 'x' })).toEqual({
      ok: false,
      error: '请填写用户名和密码',
    })
    expect(
      validateCredentials({ mode: 'register', username: '  ', password: '12345678' }).ok,
    ).toBe(false)
  })

  it('⭐ 登录故意宽松：1 位用户名也放行（老账号可能不合新规则，别把人锁在门外）', () => {
    expect(validateCredentials({ mode: 'login', username: 'a', password: 'b' })).toEqual({
      ok: true,
      username: 'a',
      password: 'b',
    })
  })

  it('注册：用户名至少 3 位、密码至少 8 位（与后端字段限制一致）', () => {
    expect(
      validateCredentials({ mode: 'register', username: 'ab', password: '12345678' }).error,
    ).toBe(`用户名至少 ${USERNAME_MIN_REGISTER} 位`)
    expect(
      validateCredentials({ mode: 'register', username: 'abc', password: '1234567' }).error,
    ).toBe(`密码至少 ${PASSWORD_MIN_REGISTER} 位`)
    expect(validateCredentials({ mode: 'register', username: 'abc', password: '12345678' }).ok).toBe(
      true,
    )
  })

  it('上限也照后端：用户名 32 / 密码 128', () => {
    const long = 'a'.repeat(USERNAME_MAX + 1)
    expect(validateCredentials({ mode: 'register', username: long, password: '12345678' }).error).toBe(
      `用户名最多 ${USERNAME_MAX} 位`,
    )
    expect(
      validateCredentials({ mode: 'login', username: 'demo', password: 'x'.repeat(129) }).error,
    ).toBe('密码最多 128 位')
  })

  it('⭐ 不自己发明规则：后端只限长度，"字母/数字/下划线"那句提示不是限制', () => {
    // 中文用户名、带点的用户名后端都收（Field 只限 min/max_length）→ 前端不许拦
    expect(validateCredentials({ mode: 'register', username: '张三丰', password: '12345678' }).ok).toBe(
      true,
    )
    expect(validateCredentials({ mode: 'register', username: 'a.b-c', password: '12345678' }).ok).toBe(
      true,
    )
  })

  it('⭐ 回来的用户名是 trim 过的（模板不要再自己 trim 一遍）', () => {
    const result = validateCredentials({ mode: 'login', username: '  demo  ', password: 'x' })
    expect(result.username).toBe('demo')
  })

  it('提交中禁用；空输入也能点（点了才看到提示，而不是点不动）', () => {
    expect(isSubmitDisabled({ loading: true })).toBe(true)
    expect(isSubmitDisabled({ loading: false })).toBe(false)
  })

  it('两种模式的提示文案不同（注册页要说清位数要求）', () => {
    expect(AUTH_HINTS.login.submit).toBe('登录')
    expect(AUTH_HINTS.register.submit).toBe('注册并进入')
    expect(AUTH_HINTS.register.password).toContain(String(PASSWORD_MIN_REGISTER))
    expect(AUTH_HINTS.login.username).toBe('用户名')
  })
})

describe('登录页接线（E17）', () => {
  it('⭐ Naive UI 在登录页彻底退场（要么保留要么手写，不许半重写）', () => {
    const view = readSrc('src/components/LoginView.vue')
    expect(view).not.toContain('naive-ui')
    expect(view).not.toMatch(/<n-/)
  })

  it('⭐ 登录逻辑一个都没换：还是调 auth 里那三个', () => {
    const view = readSrc('src/components/LoginView.vue')
    expect(view).toContain("import { login, register, demoLogin } from '../auth'")
    expect(view).toContain('await login(checked.username, checked.password)')
    expect(view).toContain('await register(checked.username, checked.password)')
    expect(view).toContain('await demoLogin()')
    expect(view).toContain("emit('success'")
  })

  it('校验走 authForm（模板里不自己判断位数）', () => {
    const view = readSrc('src/components/LoginView.vue')
    expect(view).toContain("from '../authForm'")
    expect(view).toContain('validateCredentials(')
    // 模板不该再出现硬编码的长度判断
    expect(view).not.toContain('password.length <')
    expect(view).not.toContain('length < 8')
  })

  it('手写的无障碍与交互：页签 semantic、错误 role=alert、密码可显隐、Enter 可提交', () => {
    const view = readSrc('src/components/LoginView.vue')
    expect(view).toContain('role="tablist"')
    expect(view).toContain(':aria-selected')
    expect(view).toContain('role="alert"')
    expect(view).toContain(':aria-label="showPassword')
    expect(view).toContain("showPassword ? 'text' : 'password'")
    expect(view).toMatch(/@keydown\.enter="submit"/)
  })

  it('切页签只清错误、不清输入（输了半天的用户名不该白输）', () => {
    const form = readSrc('src/authForm.js')
    expect(form).toContain('export function errorAfterSwitch')
    const view = readSrc('src/components/LoginView.vue')
    expect(view).toContain('error.value = errorAfterSwitch()')
    // 不许在切页签时清空 username/password
    expect(view).not.toMatch(/switchMode[\s\S]{0,200}username\.value = ''/)
  })

  it('结构类名仍是 auth-*（登录页在 .dw 之外，样式互不污染）', () => {
    const view = readSrc('src/components/LoginView.vue')
    expect(view).toContain('class="auth-page"')
    expect(view).toContain('class="auth-card"')
    expect(view).toContain('auth-submit')
    // 新控件的样式也在 .dw 之外（style.css 里这些选择器不带 .dw 前缀）
    const css = readSrc('src/style.css')
    expect(css).toMatch(/\n\.auth-tabs \{/)
    expect(css).toMatch(/\n\.auth-submit \{/)
    expect(css).not.toMatch(/\.dw \.auth-submit/)
  })
})
