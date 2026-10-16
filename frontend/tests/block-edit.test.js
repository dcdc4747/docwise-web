/**
 * 埋点 1 的前端侧：译文改动（契约 §2.9 / N33）与台账逐条 diff。
 *
 * 盯四件事（与后端那 9 条对应）：
 *
 * 1. ⭐ **入口只在"有译文"的块上给**（没有译文的块是"暂无块级译文"的诚实档，不给编辑）；
 * 2. ⭐ **只有服务端真存下了才动界面**：成功后界面是新译文 + 打「已人工修改」标记；
 * 3. ⭐ **失败如实报错、界面仍是旧译文**（不做乐观更新，假装成功比报错更糟）；
 * 4. ⭐ **台账里"译文编辑"那一条能展开看到改前 / 改后**（拿不到明细不许编）。
 *
 * ⚠️ ReadView 那一半用 **store 层真跑 + 模板源码断言**（挂整个阅读页要摆的桩太多，
 *    与 app.smoke 重复）；模板断言盯的是"门在不在"——`v-if` 挂错就会红。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const authFetch = vi.fn()
vi.mock('../src/auth', () => ({
  authFetch: (...args) => authFetch(...args),
  urlWithTicket: (url) => url,
}))

const reader = await import('../src/stores/useReader')
const { editDiff } = await import('../src/ledgerText')

/**
 * 读源码做结构断言（只用来验"门在不在"这类判据）。
 *
 * ⚠️ **不用 `new URL(..., import.meta.url)`、也不用 `fileURLToPath`**：
 * happy-dom 环境里 `import.meta.url` 不是 `file:` URL，两条路都会抛
 * （`app.smoke.test.js` 第 173 行已把这个坑写下来过；`mount-points.test.js` /
 * `common-components.test.js` 也都是 `resolve(process.cwd(), ...)` 这么读的）。
 * vitest 的 cwd 就是 `frontend/`，所以调用处一律传**相对 `frontend/`** 的路径。
 */
const readSrc = (rel) => readFileSync(resolve(process.cwd(), rel), 'utf8')

function ok(body, status = 200) {
  return { ok: status < 400, status, json: async () => body }
}

beforeEach(() => {
  authFetch.mockReset()
  reader.currentTask.value = { id: 7, filename: 'math.pdf' }
  reader.blocks.value = [
    { block_id: 'p0_b1', text: 'Original sentence.', translated: '模型译文' },
    { block_id: 'p0_b2', text: 'No translation here.', translated: null },
  ]
  reader.editedBlockIds.value = new Set()
})

describe('E6 译文改动（N33）', () => {
  it('入口只在"有译文"的块上给（没有译文的块是诚实档，不给编辑）', () => {
    expect(reader.blockHasTranslated({ translated: '有译文' })).toBe(true)
    expect(reader.blockHasTranslated({ translated: '   ' })).toBe(false)
    expect(reader.blockHasTranslated({ translated: null })).toBe(false)
    expect(reader.blockHasTranslated({})).toBe(false)

    // 模板里那个入口必须真挂在这个判据上（挂错地方 = 给"暂无译文"的块开了编辑框）
    const src = readSrc('src/views/ReadView.vue')
    expect(src).toMatch(/v-if="blockHasTranslated\(row\.block\)"/)
  })

  it('存成功：返回 null、界面变成新译文、并打上「已人工修改」标记', async () => {
    authFetch.mockResolvedValueOnce(ok({ id: 1, block_id: 'p0_b1', edited: true }, 201))

    const failure = await reader.saveBlockEdit('p0_b1', '人工润色后的译文')

    expect(failure).toBeNull()
    expect(reader.blocks.value[0].translated).toBe('人工润色后的译文')
    expect(reader.editedBlockIds.value.has('p0_b1')).toBe(true)
    // 请求体带上了"改前"（第一次改动时就是模型译文）——台账 diff 靠它
    const [url, init] = authFetch.mock.calls[0]
    expect(url).toBe('/api/block-edits')
    expect(JSON.parse(init.body)).toEqual({
      task_id: 7,
      block_id: 'p0_b1',
      before: '模型译文',
      after: '人工润色后的译文',
    })
  })

  it('存失败：如实报错、界面**仍是旧译文**（不做乐观更新）', async () => {
    authFetch.mockResolvedValueOnce(
      ok({ detail: '改动没写进去（服务端写入失败），这段译文没有被记录' }, 503),
    )

    const failure = await reader.saveBlockEdit('p0_b1', '改了半天')

    expect(failure).toContain('改动没写进去')
    // ⭐ 这两条是"不假装成功"的判据
    expect(reader.blocks.value[0].translated).toBe('模型译文')
    expect(reader.editedBlockIds.value.has('p0_b1')).toBe(false)
  })

  it('网络炸了也给一句人话（不是空白，也不是"成功"）', async () => {
    authFetch.mockRejectedValueOnce(new Error('offline'))

    const failure = await reader.saveBlockEdit('p0_b1', '新译文')

    expect(failure).toContain('没存上')
    expect(failure).toContain('还是原来那一版')
    expect(reader.blocks.value[0].translated).toBe('模型译文')
  })

  it('拿不到块就别硬存（宁可让人重开这一段）', async () => {
    const failure = await reader.saveBlockEdit('p9_b9', '新译文')
    expect(failure).toContain('找不到要改的那一段')
    expect(authFetch).not.toHaveBeenCalled()
  })

  it('读改动记录：读不到就退回空集（少一个标记，也绝不编一个"改过"）', async () => {
    authFetch.mockResolvedValueOnce(ok({ items: [{ block_id: 'p0_b1' }] }))
    await reader.loadBlockEdits(7)
    expect(reader.editedBlockIds.value.has('p0_b1')).toBe(true)

    authFetch.mockRejectedValueOnce(new Error('boom'))
    await reader.loadBlockEdits(7)
    expect(reader.editedBlockIds.value.size).toBe(0)
  })

  it('⭐ 标记要挂在**两条渲染路径**上（桌面 `.page .cols p` / 手机 `.pdoc .zh`）', () => {
    // 段落精读有两条渲染路径，而这段模板**没有共同的子组件**，所以两边得各写一遍。
    // ⚠️ 这条守卫原来只判"文件里有没有『已人工修改』"——**只接一条也能过**，
    //    于是真漏了桌面那条（手机看得到、桌面看不到），是抓提交材料截图时才发现的。
    //    现在改成**两条路径各一次**：少任何一条就红。
    const src = readSrc('src/views/ReadView.vue')
    const at1 = src.indexOf('class="cols"')
    const atZh = src.indexOf('class="zh"')
    expect(at1, '找不到桌面那条渲染路径（class="cols"）').toBeGreaterThan(-1)
    expect(atZh, '找不到手机那条渲染路径（class="zh"）').toBeGreaterThan(-1)
    expect(at1, '两条路径的先后顺序变了，这条守卫要跟着改').toBeLessThan(atZh)
    const desktop = src.slice(at1, atZh)
    const mobile = src.slice(atZh)
    for (const [name, block] of [
      ['桌面 .page .cols p', desktop],
      ['手机 .pdoc .zh', mobile],
    ]) {
      expect(block, `${name} 缺「已人工修改」标记`).toContain('class="pg-edited"')
      expect(block, `${name} 的判据与另一条不一致`).toContain('editedBlockIds.has(row.block.block_id)')
      expect(block, `${name} 缺标记文案`).toContain('已人工修改')
    }
    // 编辑框只在"正在改的那一块"下面出现
    expect(src).toMatch(/v-if="editFor === row\.block\.block_id"/)
  })

  it('⭐ 打开阅读页时就要读改动记录（不能只跟着懒加载的 blocks 走）', () => {
    // ⚠️ 真踩过：`loadBlockEdits` 原来只挂在 `loadBlocks` 里，而 `loadBlocks` 是**懒的**
    //    （只在"术语定位 / PDF 定位"时触发）→ **打开阅读页根本不请求这条接口** →
    //    `editedBlockIds` 一直是空集 → **两条渲染路径上的「已人工修改」标记都不出现**。
    //    既有用例抓不到它，是因为它们只测"函数算得对"和"模板里有那个字符串"，
    //    **没有一条管"该读的时候读没读"**——这条补的就是它。
    const src = readSrc('src/stores/useReader.js')
    const at = src.indexOf('export async function openTask(')
    expect(at, '找不到 openTask').toBeGreaterThan(-1)
    const nextExport = src.indexOf('\nexport ', at + 10)
    const body = src.slice(at, nextExport > 0 ? nextExport : at + 4000)
    expect(body, 'openTask 里没有读改动记录').toMatch(/loadBlockEdits\(task\.id\)/)
    // 而且是在"进阅读工作台"那条路径上，不是被包在条件里（条件为假就又漏了）
    expect(body).toContain('await refreshWorkbench(task.id)')
  })
})

describe('E14 台账逐条 diff', () => {
  it('只有"译文编辑"那一条才有 diff；拿不到明细就是 null（不许编）', () => {
    const row = {
      stage: 'edit',
      payload: { block_id: 'p0_b1', before: '模型译文', after: '人工译文' },
    }
    expect(editDiff(row)).toEqual({
      before: '模型译文',
      after: '人工译文',
      blockId: 'p0_b1',
    })
    // 不是编辑事件 / 没有 payload / payload 形状不对 → 一律 null
    expect(editDiff({ stage: 'ask', payload: row.payload })).toBeNull()
    expect(editDiff({ stage: 'edit' })).toBeNull()
    expect(editDiff({ stage: 'edit', payload: { before: 'x' } })).toBeNull()
    expect(editDiff(null)).toBeNull()
  })

  it('「处理过程」一屏把 diff 摆出来（改前 / 改后两块），并保留原始 JSON 的退路', () => {
    const src = readSrc('src/views/ProcessView.vue')
    expect(src).toContain('proc-diff-before')
    expect(src).toContain('proc-diff-after')
    // 拿不到 diff 的行走原始 JSON（回过头的诚实退路）
    expect(src).toContain('proc-json')
    // 逐条 diff 的样式段在（否则两栏会挤成一坨）
    const css = readSrc('src/style.css')
    expect(css).toContain('[E6] 译文编辑与埋点')
    expect(css).toContain('.proc-diff-side')
    expect(css).toContain('.pg-edited')
  })
})
