/**
 * 测试自身的"卫生"守卫。
 *
 * 目前只管一条，但它踩过不止一次：
 *
 * ⚠️ **测试里不许用 `new URL(rel, import.meta.url)` / `fileURLToPath` 读源码**。
 * happy-dom 环境里 `import.meta.url` 不是 `file:` URL，这两条路会直接抛；
 * 就算某台机器上没抛，行为也不稳定（取决于 vitest 的池与 transform 结果）。
 * 正确写法是 `readFileSync(resolve(process.cwd(), …), 'utf8')` —— vitest 的 cwd 就是
 * `frontend/`，所以路径一律**相对 `frontend/`** 写（如 `'src/style.css'`）。
 *
 * 这条守卫读的是**去掉注释后**的源码：`block-edit.test.js` / `app.smoke.test.js` 里
 * 都有大段注释在解释"为什么不要用"，不剥注释就会把它们自己判成违规。
 */

import { readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const TESTS_DIR = resolve(process.cwd(), 'tests')

/** 剥掉块注释与行注释（够用即可：这些测试文件里没有靠 `//` 拼 URL 的花活）。 */
function stripComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')
}

describe('测试文件卫生', () => {
  it('⭐ 不许用 import.meta.url 读源码（happy-dom 下会抛，已踩过两次）', () => {
    const offenders = []
    for (const name of readdirSync(TESTS_DIR)) {
      if (!name.endsWith('.test.js')) continue
      // ⚠️ **跳过守卫自己**：它必须在代码里写出那个模式才可能检出别人
      // （第一版忘了排除，于是它把自己判成违规）。
      if (name === 'test-hygiene.test.js') continue
      const code = stripComments(readFileSync(resolve(TESTS_DIR, name), 'utf8'))
      for (const [index, line] of code.split('\n').entries()) {
        if (/import\.meta\.url/.test(line) || /fileURLToPath/.test(line)) {
          offenders.push(`${name}:${index + 1}  ${line.trim().slice(0, 80)}`)
        }
      }
    }
    expect(offenders, `这些地方要改成 resolve(process.cwd(), …)：\n${offenders.join('\n')}`).toEqual([])
  })

  it('读源码的辅助函数都用 resolve(process.cwd(), …)', () => {
    // 只做一个存在性检查：仓库里确实有这套写法在用（防止有人把标准答案删了却没留新写法）
    const hit = readdirSync(TESTS_DIR)
      .filter((name) => name.endsWith('.test.js'))
      .some((name) =>
        readFileSync(resolve(TESTS_DIR, name), 'utf8').includes('resolve(process.cwd()'),
      )
    expect(hit).toBe(true)
  })
})
