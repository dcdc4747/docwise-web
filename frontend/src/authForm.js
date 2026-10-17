/**
 * 登录 / 注册的**校验**（E17）。
 *
 * ## 为什么单独一个文件
 *
 * 契约（`契约_前端命名与拆分` §7）把登录页重写的**风险**写得很明白：
 * > 风险不在视觉，在测试与校验（Naive UI 自带校验与 a11y 要自己补）……
 * > **缓解：校验抽成 composable 先行单测，模板只动表现层。**
 *
 * 所以这里只放**纯函数**：给定输入回"能不能提交、不能的话给人看哪句话"。
 * 模板那边只管摆，不含任何判断。
 *
 * ## 判据一律**镜像后端**（`backend/app/routers/auth.py`）
 *
 * - 注册：`username` 3–32 字、`password` 8–128 字；
 * - 登录：`username` 1–32 字、`password` 1–128 字（**故意宽松**——老账号可能不合新规则，
 *   登录时多一道"格式不对"只会把人锁在门外）。
 *
 * ⚠️ **不自己发明规则**：注册页那句提示原写"字母/数字/下划线"，但**后端并没有这条限制**。
 * 前端要是照那句加一条正则，就会拒掉后端明明接受的用户名——**校验不许比后端严**。
 */

export const USERNAME_MIN_REGISTER = 3
export const USERNAME_MAX = 32
export const PASSWORD_MIN_REGISTER = 8
export const PASSWORD_MAX = 128

/** 两种模式的提示文案（模板直接取，别在模板里写死一串字）。 */
export const AUTH_HINTS = {
  login: {
    username: '用户名',
    password: '密码',
    submit: '登录',
  },
  register: {
    username: `用户名（${USERNAME_MIN_REGISTER}–${USERNAME_MAX} 位）`,
    password: `密码（至少 ${PASSWORD_MIN_REGISTER} 位）`,
    submit: '注册并进入',
  },
}

/**
 * 校验一次提交。
 *
 * @returns `{ ok: true, username, password }` 或 `{ ok: false, error }`
 *   —— ⚠️ `ok` 为真时**带回 trim 过的用户名**，模板不要再自己 trim（两处 trim 容易漏一处）。
 */
export function validateCredentials({ mode = 'login', username = '', password = '' } = {}) {
  const name = String(username ?? '').trim()
  const pass = String(password ?? '')
  const isRegister = mode === 'register'

  if (!name || !pass) return { ok: false, error: '请填写用户名和密码' }

  if (name.length > USERNAME_MAX) {
    return { ok: false, error: `用户名最多 ${USERNAME_MAX} 位` }
  }
  if (pass.length > PASSWORD_MAX) {
    return { ok: false, error: `密码最多 ${PASSWORD_MAX} 位` }
  }

  if (isRegister) {
    if (name.length < USERNAME_MIN_REGISTER) {
      return { ok: false, error: `用户名至少 ${USERNAME_MIN_REGISTER} 位` }
    }
    if (pass.length < PASSWORD_MIN_REGISTER) {
      return { ok: false, error: `密码至少 ${PASSWORD_MIN_REGISTER} 位` }
    }
  }

  return { ok: true, username: name, password: pass }
}

/** 切换页签时该不该清掉上一次的错误（清了才不吓人，但**不清输入**）。 */
export function errorAfterSwitch() {
  return ''
}

/** 提交按钮该不该禁用（⚠️ 只在**提交中**禁用：空输入要让用户点了看到那句提示，而不是点不动）。 */
export function isSubmitDisabled({ loading = false } = {}) {
  return Boolean(loading)
}
