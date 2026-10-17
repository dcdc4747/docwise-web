/**
 * 个人偏好（F 卡 N40/N41）：服务端权威、`localStorage` 降级为缓存。
 *
 * 这一条要挡的错法都很具体：
 *
 * 1. ⭐ **服务端有就以它为准**（不许本机旧值把它盖回去）；
 * 2. ⭐ **一次性迁移**：服务端空、本机有（老用户）→ 必须把本机那份推上去，
 *    否则老用户第一次登录就"偏好被清空"；
 * 3. ⭐ **网络挂了不挡人**：取失败按本机用、存失败也先在本机生效，只**如实报一句**；
 * 4. ⭐ **只认已知键与合法值**（脏数据不许把界面顶到未定义分支）；
 * 5. ⭐ **阅读页仍同步读缓存**（它等不了网络往返）——缓存必须被写入。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  DEFAULT_PREFS,
  PREFS_KEY,
  loadPrefs,
  prefs,
  prefsError,
  prefsLoaded,
  readLocalPrefs,
  resetPrefs,
  sanitizePrefs,
  savePrefs,
  writeLocalPrefs,
} from '../src/stores/usePrefs'

const readSrc = (rel) => readFileSync(resolve(process.cwd(), rel), 'utf8')

const json = (status, body) => ({
  ok: status < 400,
  status,
  json: async () => body,
  text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
})

/** 极简「后端」：只认偏好那两条路；`server` 是服务端当前那份（`null` = 空）。 */
function stubApi({ server = {}, failGet = false, failPut = false } = {}) {
  const calls = []
  const fetchMock = vi.fn(async (url, init = {}) => {
    const path = String(url).split('?')[0]
    const method = (init.method || 'GET').toUpperCase()
    calls.push({
      path,
      method,
      headers: init.headers || {},
      body: init.body ? JSON.parse(init.body) : null,
    })
    if (!path.endsWith('/api/me/preferences')) return json(404, { detail: '没这条路由' })
    if (method === 'GET') {
      if (failGet) return json(500, { detail: '炸了' })
      return json(200, { prefs: server })
    }
    if (failPut) return json(500, { detail: '存不下' })
    return json(200, { prefs: JSON.parse(init.body).prefs, updated_at: '2026-10-17T00:00:00Z' })
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

const puts = (calls) => calls.filter((c) => c.method === 'PUT')

beforeEach(() => {
  localStorage.clear()
  resetPrefs()
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('偏好的纯逻辑', () => {
  it('只认已知键与合法值（不认识的回落默认、未知键丢掉）', () => {
    expect(sanitizePrefs({})).toEqual(DEFAULT_PREFS)
    expect(sanitizePrefs({ defaultView: 'nope' }).defaultView).toBe('blocks')
    expect(sanitizePrefs({ tier: 'precise' }).tier).toBe('medium') // 精档早撤了
    expect(sanitizePrefs({ readingSize: 'huge' }).readingSize).toBe('normal')
    expect(sanitizePrefs({ reducedMotion: 'yes' }).reducedMotion).toBe(false)
    expect(sanitizePrefs({ evil: 1 })).toEqual(DEFAULT_PREFS)
    expect(sanitizePrefs(null)).toEqual(DEFAULT_PREFS)
  })

  it('本机缓存读坏数据也回落默认（它是缓存，不是权威）', () => {
    expect(readLocalPrefs()).toEqual(DEFAULT_PREFS)
    localStorage.setItem(PREFS_KEY, '{坏掉的')
    expect(readLocalPrefs()).toEqual(DEFAULT_PREFS)
    writeLocalPrefs({ defaultView: 'dual', tier: 'fast' })
    expect(readLocalPrefs()).toMatchObject({ defaultView: 'dual', tier: 'fast' })
  })
})

describe('loadPrefs：跟服务端对一次', () => {
  it('⭐ 服务端有 → 以它为准，并反写本机缓存', async () => {
    writeLocalPrefs({ defaultView: 'mono', tier: 'fast' })
    stubApi({ server: { defaultView: 'dual', tier: 'medium', readingSize: 'large' } })
    await loadPrefs()
    expect(prefs.value).toMatchObject({
      defaultView: 'dual',
      tier: 'medium',
      readingSize: 'large',
    })
    // 阅读页同步读的就是这份缓存
    expect(readLocalPrefs()).toMatchObject({ defaultView: 'dual', readingSize: 'large' })
    expect(prefsLoaded.value).toBe(true)
    expect(prefsError.value).toBe('')
  })

  it('⭐ 服务端空 + 本机有 → 一次性迁移（把本机那份推上去）', async () => {
    writeLocalPrefs({ defaultView: 'dual', tier: 'fast' })
    const calls = stubApi({ server: {} })
    await loadPrefs()
    const pushed = puts(calls)
    expect(pushed).toHaveLength(1)
    expect(pushed[0].body).toEqual({ prefs: { ...DEFAULT_PREFS, defaultView: 'dual', tier: 'fast' } })
    expect(prefs.value).toMatchObject({ defaultView: 'dual', tier: 'fast' })
  })

  it('⭐ 服务端空 + 本机也空 → 不瞎推（别拿默认值覆盖服务端）', async () => {
    const calls = stubApi({ server: {} })
    await loadPrefs()
    expect(puts(calls)).toHaveLength(0)
    expect(prefs.value).toEqual(DEFAULT_PREFS)
    // 也**不许**顺手把默认值写进缓存：否则下次加载会把它当"用户设置"迁移上去（自我播种）
    expect(localStorage.getItem(PREFS_KEY)).toBeNull()
  })

  it('⭐ 本机只有 "{}" 也不算"存过"（否则空库用户一登录就被推默认值）', async () => {
    localStorage.setItem(PREFS_KEY, '{}')
    const calls = stubApi({ server: {} })
    await loadPrefs()
    expect(puts(calls)).toHaveLength(0)
  })

  it('⭐ 取失败 → 按本机用，并如实说一句', async () => {
    writeLocalPrefs({ defaultView: 'mono' })
    stubApi({ failGet: true })
    await loadPrefs()
    expect(prefs.value.defaultView).toBe('mono')
    expect(prefsError.value).toContain('没从服务端取到')
    expect(prefsError.value).toContain('本机')
  })
})

describe('savePrefs：先落缓存再推服务端', () => {
  it('合并 + 校验 + PUT，并写进本机缓存', async () => {
    const calls = stubApi({})
    const result = await savePrefs({ defaultView: 'dual' })
    expect(result.ok).toBe(true)
    expect(puts(calls)).toHaveLength(1)
    expect(puts(calls)[0].body.prefs).toMatchObject({ defaultView: 'dual' })
    expect(readLocalPrefs().defaultView).toBe('dual')
    expect(prefsError.value).toBe('')
  })

  it('⭐ PUT 必须带 Content-Type: application/json（少了它 FastAPI 回 422，实拍踩过）', async () => {
    const calls = stubApi({})
    await savePrefs({ defaultView: 'dual' })
    const put = puts(calls)[0]
    expect(put.headers['Content-Type']).toBe('application/json')
  })

  it('⭐ 推失败也先在本机生效，只如实说明"换设备不会带上"', async () => {
    stubApi({ failPut: true })
    const result = await savePrefs({ readingSize: 'large' })
    expect(result.ok).toBe(false)
    expect(prefs.value.readingSize).toBe('large')
    expect(readLocalPrefs().readingSize).toBe('large')
    expect(prefsError.value).toContain('没存到服务端')
    expect(prefsError.value).toContain('换设备')
  })
})

describe('接线', () => {
  it('个人中心：读走 usePrefs、写走 savePrefs，错误如实显示', () => {
    const view = readSrc('src/views/MeView.vue')
    expect(view).toContain("from '../stores/usePrefs'")
    expect(view).toContain('savePrefs(')
    expect(view).toContain('loadPrefs(')
    expect(view).toContain('prefsError')
    // 不许再自己直接写 localStorage（键名已经收进 store）
    expect(view).not.toContain("localStorage.setItem(PREFS_KEY")
    expect(view).not.toContain("const PREFS_KEY")
  })

  it('外壳：启动时拉一次偏好（上传卡默认档位/字号/动效都吃这份）', () => {
    const app = readSrc('src/App.vue')
    expect(app).toContain("from './stores/usePrefs'")
    expect(app).toContain('await loadPrefs()')
    expect(app).toContain('reloadShellPrefs()')
  })

  it('⭐ 阅读页仍然同步读缓存（它等不了网络往返）——那条路不许改成异步', () => {
    const reader = readSrc('src/stores/useReader.js')
    expect(reader).toContain('localStorage.getItem')
    expect(reader).toContain('docwise_prefs')
  })
})
