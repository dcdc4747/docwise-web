<template>
  <div class="mx">
    <div class="mx-scroll">
      <table class="mx-table">
        <caption v-if="topic" class="mx-caption">
          {{ topic }}
        </caption>
        <thead>
          <tr>
            <th scope="col" class="mx-file-col">文献</th>
            <th v-for="column in columns" :key="column" scope="col" class="mx-col">
              {{ column }}
            </th>
            <!-- 操作列表头留空：按钮的语义由按钮自己承担，不给表格加一句没用的"操作" -->
            <th scope="col" class="mx-copy-col" aria-label="操作"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!rows.length" class="mx-empty-row">
            <td :colspan="columns.length + 2" class="mx-empty">没有可对比的文献</td>
          </tr>
          <tr v-for="(row, rowIndex) in rows" :key="rowIndex" class="mx-row">
            <th scope="row" class="mx-file">
              <span v-if="fileName(row)">{{ fileName(row) }}</span>
              <span v-else class="mx-dash" aria-label="空">—</span>
            </th>
            <td v-for="column in columns" :key="column" class="mx-cell">
              <button
                v-if="isLong(cellText(row, column))"
                type="button"
                class="mx-cell-toggle"
                :aria-expanded="isExpanded(rowIndex, column) ? 'true' : 'false'"
                :aria-label="(isExpanded(rowIndex, column) ? '收起' : '展开') + '「' + column + '」全文'"
                @click="toggleCell(rowIndex, column)"
              >
                {{ displayText(cellText(row, column), isExpanded(rowIndex, column)) }}
              </button>
              <span v-else-if="cellText(row, column)" class="mx-cell-text">
                {{ cellText(row, column) }}
              </span>
              <span v-else class="mx-dash" aria-label="空">—</span>
            </td>
            <td class="mx-copy-cell">
              <button type="button" class="mx-copy" @click="copyRow(row)">复制这一行</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 没进表格的文献不混进对比行：单独一行说清"有几篇、为什么不参与" -->
    <p v-if="missing.length" class="mx-missing">
      另有 {{ missing.length }} 篇没有导读（不参与对比）
    </p>

    <!-- 复制结果常驻：成功也给回执；失败把整段文本放进 live 区，不静默失败 -->
    <p class="mx-live" :class="{ 'is-fail': copyFeedback.kind === 'fail' }" role="status" aria-live="polite">
      <template v-if="copyFeedback.kind === 'ok'">{{ copyFeedback.message }}</template>
      <template v-else-if="copyFeedback.kind === 'fail'">
        复制失败（浏览器没给剪贴板权限）。下面是这一行的文本，可手动复制：
        <span class="mx-live-text">{{ copyFeedback.text }}</span>
      </template>
    </p>
  </div>
</template>

<script>
/**
 * 纯函数放在普通 `<script>` 里导出，供单测直接 import（`<script setup>` 不许有 ES 导出）。
 * 组件本身不请求接口、不碰 store —— 数据从 `data` prop 进来。
 */

/** 后端没给 `columns` 时用的默认列（与 `build_matrix` 的默认口径一致）。 */
export const DEFAULT_COLUMNS = Object.freeze(['研究问题', '方法', '结论', '术语', '可引用句'])

/** 空值的唯一呈现：灰色破折号。**不留白，也不编内容**。 */
const EMPTY = '—'

/** 单元格里的空白压平成单行（PDF 文本块常带换行，表格里按一行摆）。 */
function flatten(value) {
  return String(value).replace(/\s+/g, ' ').trim()
}

/** 一格的值 → 单行文本；空值返回 `''`，由渲染层统一补「—」。 */
export function cellText(row, column) {
  const raw = row?.cells?.[column]
  if (raw == null) return ''
  // 术语这类列有时是数组：用顿号连起来，不丢条目
  if (Array.isArray(raw)) {
    return flatten(
      raw
        .filter((item) => item != null && String(item).trim() !== '')
        .join('、'),
    )
  }
  if (typeof raw === 'string' || typeof raw === 'number' || typeof raw === 'boolean') {
    return flatten(raw)
  }
  return ''
}

/** 文件名；缺失时返回 `''`（渲染层补「—」，不替它编"未命名文献"）。 */
export function fileName(row) {
  return flatten(row?.filename ?? '')
}

/**
 * 一行 → 可复制的纯文本。**这是复制按钮唯一的文本来源**，格式固定：
 *
 * ```text
 * a.pdf
 * 研究问题：…
 * 方法：…
 * 结论：—
 * ```
 *
 * 第一行是文件名，之后每列一行（`列名：值`）；空值写「—」，列顺序与表头一致。
 */
export function rowToText(row, columns) {
  const cols = Array.isArray(columns) && columns.length ? columns : DEFAULT_COLUMNS
  const lines = [fileName(row) || EMPTY]
  for (const column of cols) {
    lines.push(`${column}：${cellText(row, column) || EMPTY}`)
  }
  return lines.join('\n')
}
</script>

<script setup>
/**
 * 文献对比矩阵 —— 把 `build_matrix` 的结果摆成一张能"一眼横向对比"的表。
 *
 * 几条口径：
 * ① 表头 = `columns`（缺省/空数组都退回 `DEFAULT_COLUMNS`），**第一列固定「文献」**；
 *    最后一列只放「复制这一行」按钮。
 * ② 单元格超过 60 字折叠成"前 60 字 + …"，点格子展开/收起，按钮上带 `aria-expanded`；
 *    顿号/换行都算字符，展开后显示**完整原文**（不二次加工）。
 * ③ 空格子一律灰色 `—`：空白会被读成"没这一列"，破折号才说得清"这一格没有内容"。
 * ④ `missing` 里的文献不占表格行，表格下方单独一行报数量。
 * ⑤ 复制失败**不静默**：把整段文本放进 `aria-live` 区，用户能看见、读屏能念出来。
 */
import { computed, ref } from 'vue'

const props = defineProps({
  /**
   * `build_matrix` 的结果：`{ topic, columns, rows, missing }`。
   * 允许缺字段、允许为空 —— 组件对每一种缺失都有确定的表现，不抛异常。
   */
  data: { type: Object, default: () => ({}) },
})

/** 折叠阈值（字）。写死 60：需求口径，不是可调参数。 */
const COLLAPSE_AT = 60

const topic = computed(() => (typeof props.data?.topic === 'string' ? props.data.topic.trim() : ''))

const columns = computed(() => {
  const declared = props.data?.columns
  if (!Array.isArray(declared)) return DEFAULT_COLUMNS
  const valid = declared.filter((column) => typeof column === 'string' && column.trim() !== '')
  return valid.length ? valid : DEFAULT_COLUMNS
})

const rows = computed(() => (Array.isArray(props.data?.rows) ? props.data.rows : []))
const missing = computed(() => (Array.isArray(props.data?.missing) ? props.data.missing : []))

/** 展开状态按"第几行 + 哪一列"记；换一份 data 时由模板重新挂载，不残留。 */
const expanded = ref(new Set())

function isExpanded(rowIndex, column) {
  return expanded.value.has(`${rowIndex}:${column}`)
}

function toggleCell(rowIndex, column) {
  const next = new Set(expanded.value)
  const key = `${rowIndex}:${column}`
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expanded.value = next
}

/** 按"字"算长度（不是 UTF-16 码元），中文/emoji 都不会数错。 */
function charLength(text) {
  return Array.from(text).length
}

function isLong(text) {
  return charLength(text) > COLLAPSE_AT
}

function displayText(text, open) {
  if (open || !isLong(text)) return text
  return `${Array.from(text).slice(0, COLLAPSE_AT).join('')}…`
}

const copyFeedback = ref({ kind: '', text: '', message: '' })

/** 复制这一行：文本只来自 `rowToText`（同一份纯函数，单测钉的就是它）。 */
async function copyRow(row) {
  const text = rowToText(row, columns.value)
  try {
    if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
      throw new Error('clipboard unavailable')
    }
    await navigator.clipboard.writeText(text)
    copyFeedback.value = {
      kind: 'ok',
      text: '',
      message: `已复制「${fileName(row) || '当前文献'}」这一行`,
    }
  } catch {
    copyFeedback.value = { kind: 'fail', text, message: '' }
  }
}

defineExpose({ rowToText })
</script>

<style scoped>
/* 观感照仓库既有 token：表头浅灰、行间细线、灰字用 --muted。
   每个变量都带兜底值 —— 组件偶尔被单独截屏/挂载时，不靠外层 `.dw` 也能看。 */
.mx {
  border: 1px solid var(--line, #e5e7eb);
  border-radius: var(--r-md, 10px);
  background: var(--surface, #fff);
  overflow: hidden;
}

.mx-scroll {
  overflow-x: auto;
}

.mx-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-ui, 13.5px);
}

.mx-caption {
  caption-side: top;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line, #e5e7eb);
  color: var(--muted, #6b7280);
  font-size: var(--fs-meta, 12.5px);
  text-align: left;
}

.mx-table th,
.mx-table td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--line, #e5e7eb);
  text-align: left;
  vertical-align: top;
}

.mx-table tbody tr:last-child th,
.mx-table tbody tr:last-child td {
  border-bottom: 0;
}

.mx-table thead th {
  background: var(--surface-3, #f4f6fa);
  color: var(--muted, #6b7280);
  font-size: var(--fs-meta, 12.5px);
  font-weight: 600;
  white-space: nowrap;
}

/* 第一列钉住：横向滚动看后面的列时，"这是哪篇"一直可见 */
.mx-file-col,
.mx-file {
  position: sticky;
  left: 0;
  z-index: 1;
  background: var(--surface, #fff);
}

.mx-table thead .mx-file-col {
  z-index: 2;
  background: var(--surface-3, #f4f6fa);
}

.mx-file {
  max-width: 180px;
  color: var(--ink, #1f2329);
  font-weight: 600;
  overflow-wrap: anywhere;
}

/* 单元格自身不留内边距，内边距交给里面的块级元素 —— 这样整格都是点击热区 */
.mx-cell {
  min-width: 140px;
  max-width: 320px;
  padding: 0;
  color: var(--ink, #1f2329);
  line-height: 1.65;
}

.mx-cell > * {
  display: block;
  box-sizing: border-box;
  width: 100%;
  padding: 9px 12px;
}

.mx-cell-toggle {
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  overflow-wrap: anywhere;
}

.mx-cell-toggle:hover,
.mx-cell-toggle:focus-visible {
  background: var(--hover, rgba(31, 35, 41, 0.04));
}

.mx-cell-toggle:focus-visible {
  outline: 2px solid var(--accent-line, rgba(61, 82, 150, 0.36));
  outline-offset: -2px;
}

.mx-cell-text {
  overflow-wrap: anywhere;
}

.mx-dash {
  color: var(--muted, #6b7280);
}

.mx-copy-col {
  width: 1%;
}

.mx-copy-cell {
  white-space: nowrap;
  text-align: right;
}

.mx-copy {
  padding: 4px 10px;
  border: 1px solid var(--line, #e5e7eb);
  border-radius: var(--r-sm, 6px);
  background: var(--surface, #fff);
  color: var(--muted, #6b7280);
  font-size: var(--fs-micro, 11.5px);
  cursor: pointer;
}

.mx-copy:hover,
.mx-copy:focus-visible {
  border-color: var(--accent-line, rgba(61, 82, 150, 0.36));
  color: var(--ink, #1f2329);
}

.mx-missing {
  margin: 10px 2px 0;
  color: var(--muted, #6b7280);
  font-size: var(--fs-meta, 12.5px);
}

.mx-live {
  min-height: 1.2em;
  margin: 6px 2px 0;
  color: var(--muted, #6b7280);
  font-size: var(--fs-micro, 11.5px);
  line-height: 1.6;
}

.mx-live.is-fail {
  color: var(--warn-ink, #8a5202);
}

.mx-live-text {
  display: block;
  margin-top: 6px;
  padding: 8px 10px;
  border: 1px solid var(--line, #e5e7eb);
  border-radius: var(--r-sm, 6px);
  background: var(--surface-2, #fbfcfe);
  color: var(--ink, #1f2329);
  font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace;
  white-space: pre-wrap;
}

.mx-empty {
  padding: 18px 12px;
  color: var(--muted, #6b7280);
  text-align: center;
}
</style>
