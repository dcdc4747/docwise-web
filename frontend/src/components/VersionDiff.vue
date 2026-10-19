<template>
  <div class="vd">
    <div class="vd-head">
      <span class="vd-summary" :class="{ 'is-same': !hasChanges }" role="status">
        {{ summary }}
      </span>
      <span v-if="showLineNumbers && !fallback" class="vd-hint" aria-hidden="true">
        行号：改动前 / 改动后
      </span>
    </div>

    <!-- 超长正文：不做逐行比对，直接前后两栏。理由写在 script 的常量注释里。 -->
    <p v-if="fallback" class="vd-note">{{ fallbackNote }}</p>

    <div v-if="fallback" class="vd-columns">
      <section class="vd-col">
        <div class="vd-colhead">改动前 · {{ fallbackBeforeCount }} 行</div>
        <pre class="vd-pre">{{ fallbackColumns.before }}</pre>
      </section>
      <section class="vd-col">
        <div class="vd-colhead">改动后 · {{ fallbackAfterCount }} 行</div>
        <pre class="vd-pre">{{ fallbackColumns.after }}</pre>
      </section>
    </div>

    <p v-else-if="!rows.length" class="vd-empty">两边都没有正文。</p>

    <div v-else class="vd-body" data-testid="version-diff-lines">
      <div
        v-for="(row, index) in numberedRows"
        :key="index"
        class="vd-line"
        :class="`vd-line-${row.type}`"
        :data-type="row.type"
      >
        <template v-if="showLineNumbers">
          <span class="vd-no" aria-hidden="true">{{ row.beforeNo ?? '' }}</span>
          <span class="vd-no" aria-hidden="true">{{ row.afterNo ?? '' }}</span>
        </template>
        <span class="vd-sign">{{ signOf(row.type) }}</span>
        <span class="vd-text">{{ row.text }}</span>
      </div>
    </div>
  </div>
</template>

<script>
/**
 * 行级 diff —— 纯函数，放在普通 `<script>` 里导出，供单测直接 import
 * （`<script setup>` 不许有 ES 导出；同一写法见 `MatrixTable.vue`）。
 *
 * 只做两件事：按行切、按 LCS 找公共行。**不引入依赖、不访问接口、不碰 store。**
 */

/**
 * 逐行比对的行数上限。超过就退化成"整段前 / 整段后"两栏。
 *
 * 为什么是 3000：LCS 是 O(n·m)，3000 × 3000 已经接近千万级格子（还要记回溯方向），
 * 在手机上再往上就会卡住主线程。真实稿件通常几百行，3000 只用来兜住"有人粘了整本书"。
 * 退化路径**不做 LCS**，只把两侧按原顺序标成 del / add，所以上万行也不会崩。
 */
export const MAX_DIFF_LINES = 3000

/** 把行映射成 `{type, text}`；行号由渲染层按显示顺序现算（见 `<script setup>`）。 */
function makeRow(type, text) {
  return { type, text }
}

/** 空字符串、纯空白串在去首尾空行时都算"空行"。 */
function isBlank(line) {
  return line.trim() === ''
}

/** 逐行相等检查：O(n)，用来免掉"其实一模一样"时的 LCS。 */
function sameLines(left, right) {
  return left.length === right.length && left.every((line, index) => line === right[index])
}

/**
 * 按行切，并去掉**首尾**空行（中间的空行保留——它也是正文的一部分）。
 * 换行符兼容 `\n` / `\r\n` / `\r`。
 */
function splitLines(text) {
  const raw = String(text ?? '').split(/\r\n|\r|\n/)
  let start = 0
  let end = raw.length
  while (start < end && isBlank(raw[start])) start += 1
  while (end > start && isBlank(raw[end - 1])) end -= 1
  return raw.slice(start, end)
}

/**
 * 相邻的 diff 行归成一段，段内统一「先删除、后新增」。
 *
 * 回溯出来的顺序可能是 del/add 交错（取决于走哪条等长路径），但给人看的 diff
 * 一律把一段里的删除放在新增前面——否则同一处改动会一会儿红一行、一会儿绿一行。
 */
function groupRuns(rows) {
  const out = []
  let index = 0
  while (index < rows.length) {
    if (rows[index].type === 'same') {
      out.push(rows[index])
      index += 1
      continue
    }
    const removed = []
    const added = []
    while (index < rows.length && rows[index].type !== 'same') {
      if (rows[index].type === 'del') removed.push(rows[index])
      else added.push(rows[index])
      index += 1
    }
    out.push(...removed, ...added)
  }
  return out
}

/** 朴素 LCS：两行滚动求长度 + 一个字节/格记录回溯方向（比整张长度矩阵省内存）。 */
function diffByLcs(beforeLines, afterLines) {
  const n = beforeLines.length
  const m = afterLines.length
  const cols = m + 1
  let prev = new Uint32Array(cols)
  let cur = new Uint32Array(cols)
  // 0 = 对角（相同）、1 = 上（before 多一行）、2 = 左（after 多一行）
  const dir = new Uint8Array((n + 1) * cols)

  for (let i = 1; i <= n; i += 1) {
    const line = beforeLines[i - 1]
    for (let j = 1; j <= m; j += 1) {
      if (line === afterLines[j - 1]) {
        cur[j] = prev[j - 1] + 1
        dir[i * cols + j] = 0
      } else if (prev[j] >= cur[j - 1]) {
        cur[j] = prev[j]
        dir[i * cols + j] = 1
      } else {
        cur[j] = cur[j - 1]
        dir[i * cols + j] = 2
      }
    }
    const swap = prev
    prev = cur
    cur = swap
    cur.fill(0)
  }

  const rows = []
  let i = n
  let j = m
  while (i > 0 && j > 0) {
    const direction = dir[i * cols + j]
    if (direction === 0) {
      rows.push(makeRow('same', beforeLines[i - 1]))
      i -= 1
      j -= 1
    } else if (direction === 1) {
      rows.push(makeRow('del', beforeLines[i - 1]))
      i -= 1
    } else {
      rows.push(makeRow('add', afterLines[j - 1]))
      j -= 1
    }
  }
  while (i > 0) {
    rows.push(makeRow('del', beforeLines[i - 1]))
    i -= 1
  }
  while (j > 0) {
    rows.push(makeRow('add', afterLines[j - 1]))
    j -= 1
  }
  rows.reverse()
  return groupRuns(rows)
}

/**
 * `fallback` 挂在返回的数组上，但**不可枚举**：这样 `rows` 本身仍是干净的
 * `[{type, text}]`（`toEqual([...])` 不会因为多一个键而失败），
 * 调用方用 `rows.fallback === true` 判断是否走了退化路径。
 */
function withFallback(rows, fallback) {
  Object.defineProperty(rows, 'fallback', {
    value: fallback,
    enumerable: false,
    configurable: false,
    writable: false,
  })
  return rows
}

/**
 * 行级 diff。
 *
 * @param {string} before 旧正文（可为空）
 * @param {string} after 新正文（可为空）
 * @returns {Array<{ type: 'same' | 'add' | 'del', text: string }> & { fallback: boolean }}
 *   - `same`：两边都有这一行（按 LCS 配对）
 *   - `del`：只有 before 有
 *   - `add`：只有 after 有
 *
 * 两条口径：
 * ① 首尾的空行不参与比对（中间空行照常参与）；
 * ② 任一侧行数 > `MAX_DIFF_LINES` 时**不跑 LCS**：有差异就把 before 全部标 `del`、after 全部标 `add`；
 *    两边完全相同时仍标 `same`（不能把"没改"说成"全改了"）。两种情况的 `fallback` 都是 `true`，
 *    由组件改成"前后两栏"显示。
 */
export function diffLines(before, after) {
  const beforeLines = splitLines(before)
  const afterLines = splitLines(after)
  // 两边一模一样时直接给 same，别让 LCS 白算一遍（超长文本尤其明显）。
  const identical = sameLines(beforeLines, afterLines)

  if (Math.max(beforeLines.length, afterLines.length) > MAX_DIFF_LINES) {
    // 超长但两边一模一样时不能假装"全都改了"：先做一次 O(n) 的逐行相等检查。
    const rows = []
    if (identical) {
      for (const line of beforeLines) rows.push(makeRow('same', line))
    } else {
      for (const line of beforeLines) rows.push(makeRow('del', line))
      for (const line of afterLines) rows.push(makeRow('add', line))
    }
    return withFallback(rows, true)
  }

  if (identical) {
    return withFallback(
      beforeLines.map((line) => makeRow('same', line)),
      false,
    )
  }

  return withFallback(diffByLcs(beforeLines, afterLines), false)
}
</script>

<script setup>
/**
 * 版本对比 —— 纯展示组件：`before` 与 `after` 两段正文进来，逐行标出增删。
 *
 * 口径：
 * ① **只在行首标 `+ ` / `- `**（前缀是文本的一部分，复制出去也读得懂）；
 * ② `same` 灰字、`add` 绿底、`del` 红底——颜色只是辅助，语义由前缀与 `data-type` 承担；
 * ③ 行号**可选**（`showLineNumbers`），按去掉首尾空行后的正文从 1 开始各自计数；
 * ④ 超长正文退化时**不假装逐行比对**：直接说"超过上限"并两栏显示全文。
 */
import { computed } from 'vue'

const props = defineProps({
  /** 旧正文（版本稿）。 */
  before: { type: String, default: '' },
  /** 新正文（当前稿）。 */
  after: { type: String, default: '' },
  /** 是否显示 before / after 各自的 1 基行号（默认不显示，给窄栏省宽度）。 */
  showLineNumbers: { type: Boolean, default: false },
})

/** setup 内用一个别名，模板/计算属性都不依赖"普通 script 的绑定能否直接上模板"这种细节。 */
const maxDiffLines = MAX_DIFF_LINES

const rows = computed(() => diffLines(props.before, props.after))
const fallback = computed(() => rows.value.fallback === true)

const addCount = computed(() => rows.value.filter((row) => row.type === 'add').length)
const delCount = computed(() => rows.value.filter((row) => row.type === 'del').length)
const hasChanges = computed(() => addCount.value > 0 || delCount.value > 0)

const summary = computed(() => {
  if (!hasChanges.value) return '这一版和当前稿一样'
  return `新增 ${addCount.value} 行，删除 ${delCount.value} 行`
})

/** 退化提示里的"有 N 行"：有改动时取触发退化的一侧；内容相同时取公共行数。 */
const fallbackLineCount = computed(() => {
  if (!fallback.value) return 0
  if (hasChanges.value) return Math.max(addCount.value, delCount.value)
  return rows.value.length
})

/** 退化时两栏各自的标题行数（内容一样时两栏都是同一份行数）。 */
const fallbackBeforeCount = computed(() =>
  hasChanges.value ? delCount.value : rows.value.length,
)
const fallbackAfterCount = computed(() =>
  hasChanges.value ? addCount.value : rows.value.length,
)

/**
 * 退化提示只在退化时出现；文案把"为什么"和"代价"都说清楚：
 * 为什么（超过上限）、代价（不逐行比对，有改动时摘要按整段计）。
 */
const fallbackNote = computed(() => {
  if (!fallback.value) return ''
  const cost = hasChanges.value ? '（摘要按整段计）' : ''
  return (
    `正文有 ${fallbackLineCount.value} 行，超过 ${maxDiffLines} 行的逐行比对上限：` +
    `为了不卡住页面，这里直接并排显示前后全文，不做逐行比对${cost}。`
  )
})

/**
 * 行号是**显示顺序**上的编号（去掉首尾空行之后从 1 开始）。
 * 不给纯函数塞行号，是为了让 `diffLines` 的返回值严格保持 `{type, text}` 两字段。
 */
const numberedRows = computed(() => {
  if (!props.showLineNumbers || fallback.value) return rows.value
  let beforeNo = 0
  let afterNo = 0
  return rows.value.map((row) => {
    const item = { ...row, beforeNo: null, afterNo: null }
    if (row.type !== 'add') {
      beforeNo += 1
      item.beforeNo = beforeNo
    }
    if (row.type !== 'del') {
      afterNo += 1
      item.afterNo = afterNo
    }
    return item
  })
})

/** 退化时两栏的全文，直接由 diff 行拼回来（与计数同源，不另读 props）。 */
const fallbackColumns = computed(() => {
  if (!fallback.value) return { before: '', after: '' }
  // 超长但内容相同：没有 del/add 行，两侧都取同一份 same 行。
  if (!hasChanges.value) {
    const text = rows.value.map((row) => row.text).join('\n')
    return { before: text, after: text }
  }
  const before = []
  const after = []
  for (const row of rows.value) {
    if (row.type === 'del') before.push(row.text)
    else if (row.type === 'add') after.push(row.text)
  }
  return { before: before.join('\n'), after: after.join('\n') }
})

/** 前缀只在这里定义一次；`same` 留空，但版面用等宽符号位对齐。 */
function signOf(type) {
  if (type === 'add') return '+ '
  if (type === 'del') return '- '
  return ''
}
</script>

<style scoped>
.vd {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  min-width: 0;
  font-size: var(--fs-meta);
  color: var(--ink);
}

.vd-head {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.vd-summary {
  font-weight: 600;
}

/* 没有差异时不装"成功"色：这件事本身只是"没变化"，不是好消息也不是坏消息。 */
.vd-summary.is-same {
  color: var(--muted);
  font-weight: 500;
}

.vd-hint {
  margin-left: auto;
  font-size: var(--fs-micro);
  color: var(--muted);
}

.vd-note,
.vd-empty {
  margin: 0;
  font-size: var(--fs-micro);
  color: var(--muted);
  line-height: 1.6;
}

.vd-body {
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface);
  overflow-x: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace;
  font-size: 12.5px;
  line-height: 1.6;
}

.vd-line {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-1);
  min-height: 1.6em;
  padding: 0 var(--sp-2);
}

/* 空行也要占一行高，否则 diff 的"行"会塌成一条线。 */
.vd-line-same {
  color: var(--muted);
}

.vd-line-add {
  background: #e8f5ee;
  color: var(--ok-ink);
}

.vd-line-del {
  background: #fdeaea;
  color: var(--danger-ink);
}

.vd-no {
  flex: 0 0 auto;
  min-width: 2.5em;
  text-align: right;
  color: var(--muted);
  user-select: none;
  font-variant-numeric: tabular-nums;
}

.vd-sign {
  flex: 0 0 2ch;
  user-select: none;
}

.vd-text {
  flex: 1 1 auto;
  min-width: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.vd-columns {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--sp-2);
}

.vd-col {
  min-width: 0;
}

.vd-colhead {
  margin-bottom: var(--sp-1);
  font-size: var(--fs-micro);
  color: var(--muted);
}

.vd-pre {
  margin: 0;
  padding: var(--sp-2);
  max-height: 480px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface);
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

/* 窄屏（手机 / 手机抽屉）两栏并排会把每栏压到十几列，改成上下两段。 */
@media (max-width: 720px) {
  .vd-columns {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
