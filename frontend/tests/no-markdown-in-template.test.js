/**
 * 页面文字里**不许出现 markdown 的 `**`**——Vue 不渲染 markdown，写了就是"星号上屏"。
 *
 * 为什么值得一条用例：这个错已经在三个页面出现过（集合 / 标签 / 回收站），
 * 单看代码很像"加粗了"，只有真渲染出来才发现是 `**随时能恢复**`。
 * 注释里的 `**强调**` 不算（不上屏），所以要先把 `<!-- -->` 剥掉再判。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const VIEWS = [
  'src/views/CollectionsView.vue',
  'src/views/TagsView.vue',
  'src/views/TrashView.vue',
  'src/views/LibraryView.vue',
  'src/views/ReadHomeView.vue',
  'src/views/WriteView.vue',
  'src/views/MaterialsView.vue',
]

function templateBody(rel) {
  const text = readFileSync(resolve(process.cwd(), rel), 'utf8')
  const match = text.match(/<template>([\s\S]*?)<\/template>/)
  return match ? match[1] : ''
}

describe('模板里不许写 markdown 加粗', () => {
  for (const rel of VIEWS) {
    it(`${rel}：上屏文字里没有 **`, () => {
      const body = templateBody(rel)
      const withoutComments = body.replace(/<!--[\s\S]*?-->/g, '')
      const hits = withoutComments
        .split('\n')
        .filter((line) => line.includes('**'))
        .map((line) => line.trim().slice(0, 80))
      expect(hits, `这些行会把星号印在页面上：\n${hits.join('\n')}`).toEqual([])
    })
  }
})
