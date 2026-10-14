/**
 * 界面零碎事：菜单 / 提示条 / toast / 窄屏判断 / 手机抽屉 / 段落字号与「就这段提问」的浮出 / 左栏收起态。
 *
 * **为什么单独一个模块**：这些状态全站都要用（库页、阅读区、左栏、手机端），
 * 以前它们和"论文数据""问答线程"一起挤在 `App.vue` 的 1819 行脚本里 ——
 * 5 个人同时改那一个文件，谁动一下都碰着别人。分开之后各改各的。
 *
 * ⚠️ **状态定义在模块顶层（单例），不在 `useUi()` 里面**。
 * 若定义在函数里，每次调用都会新建一份：A 页面展开菜单，B 页面看不到 —— 这种错很隐蔽。
 * 所以这里一律「模块顶层建状态、导出函数只负责交出去」。
 *
 * 这个模块**不 import 任何其它 store**（保持是"叶子"）：别处依赖它、它不依赖别处，
 * 这样谁都不会绕成环。需要读数的地方（比如顶部抽屉摘要要显示"当前问题"）由 App.vue 拼。
 */

import { computed, ref } from 'vue'

// ============================================================ 菜单

/** 当前展开的下拉菜单（单层级、互斥展开、点外关闭）——对应原型里的 .menu.open。 */
export const openMenu = ref('')

/** 菜单项 / 动作的一句话说明（原型用同一机制把 data-note 显示在 .note-line 上）。 */
export const menuNote = ref('')
let noteTimer = null

export function toggleMenu(name) {
  openMenu.value = openMenu.value === name ? '' : name
}

export function closeMenus() {
  openMenu.value = ''
}

export function setNote(text, holdMs = 6000) {
  menuNote.value = text || ''
  if (noteTimer) clearTimeout(noteTimer)
  if (!text) return
  noteTimer = setTimeout(() => {
    menuNote.value = ''
  }, holdMs)
}

// ============================================================ toast（含"可撤销"）

export const toast = ref({ show: false, text: '', undoLabel: '' })
let toastTimer = null
let toastUndo = null

export function showToast(text, undo = null, holdMs = 3000) {
  toast.value = { show: true, text, undoLabel: undo ? undo.label : '' }
  toastUndo = undo || null
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toast.value = { show: false, text: '', undoLabel: '' }
    toastUndo = null
  }, holdMs)
}

export function runToastUndo() {
  const action = toastUndo
  toast.value = { show: false, text: '', undoLabel: '' }
  toastUndo = null
  if (toastTimer) clearTimeout(toastTimer)
  if (action && action.run) action.run()
}

/**
 * 收尾：清掉提示条与 note 的定时器。
 * **组件卸载时必须调**（App.vue 的 onUnmounted 里），否则定时器会在组件没了之后
 * 还去改一份已经不显示的状态——测试里表现为"卸载时报错、后续用例全废"。
 */
export function disposeUi() {
  if (noteTimer) clearTimeout(noteTimer)
  if (toastTimer) clearTimeout(toastTimer)
  noteTimer = null
  toastTimer = null
  toastUndo = null
}

// ============================================================ 窄屏 / 手机抽屉三档

export const isNarrow = ref(false)
export const sheetState = ref('peek')
/** 手机端"已定位到第 X 页"这类一次性提示行（点出处后挂在抽屉上）。 */
export const locatedHint = ref('')
/** 段落精读在手机上的字号缩放（0.85–1.4）。 */
export const pdocScale = ref(1)
/** 手机上点段号浮出的「就这段提问」挂在哪一段（热区只有段号本身）。 */
export const pgChipFor = ref('')

/** 助手区容器的模板 ref：点出处 / 提问后要把内容滚到底，只有它需要命令式滚动。 */
export const assistBodyEl = ref(null)

export function setAssistBody(el) {
  assistBodyEl.value = el
}

/** 把内容滚到最底（点出处、提交提问之后用）。 */
export function scrollThreadToEnd() {
  const body = assistBodyEl.value
  if (body) body.scrollTop = body.scrollHeight
}

export const sheetGripText = computed(() => {
  if (sheetState.value === 'peek') return '上拖展开（半屏 → 近全屏）'
  if (sheetState.value === 'full') return '下拖回到半屏'
  return '上拖到近全屏'
})

export const assistClass = computed(() => {
  if (!isNarrow.value) return ['assist']
  return [
    'sheet',
    sheetState.value === 'peek' ? 'peek' : '',
    sheetState.value === 'full' ? 'full' : '',
  ]
})

export const assistBodyClass = computed(() => (isNarrow.value ? 'sbody' : 'tabbody'))

export const pdocStyle = computed(() => ({ '--pdoc-scale': String(pdocScale.value) }))

export function cycleSheet() {
  const order = ['peek', 'half', 'full']
  sheetState.value = order[(order.indexOf(sheetState.value) + 1) % order.length]
}

/** 手机端点段号：浮出 / 收起「就这段提问」。段落本身就是锚点，不用划词、不用文本匹配。 */
export function togglePgChip(row) {
  if (row.index === null) return
  const id = row.block.block_id
  pgChipFor.value = pgChipFor.value === id ? '' : id
}

export function stepFont(delta) {
  const next = Math.round((pdocScale.value + delta * 0.1) * 10) / 10
  pdocScale.value = Math.min(1.4, Math.max(0.85, next))
}

export function syncNarrow() {
  isNarrow.value = window.innerWidth < 1024
}

// ============================================================ 左栏（常驻导航）
//
// 形态 v2 §1.2b：左栏 **260 ⇄ 58**，顶部一颗按钮切换、`Ctrl+B` 等效、**收起态记住**。
// ⚠️ **收起态不是"模块指示器"**（那条论证形态 §1.2b 已撤回）——它唯一的理由是**阅读时让出横向空间**。
//
// 状态放这里而不是 AppRail.vue：`Ctrl+B` 的监听在外壳（与 Esc 那一条挨着），
// 而左栏的外层容器（`.dw-layout`）与左栏自己都要读同一份状态 —— 两处读一份，才不会各变各的。
//
// ⚠️ 开关类挂在 **`.dw-layout`**（`.dw` 的子元素）上，不是 `.dw` 自己：
// `.dw` 里还套着管理后台（`AdminView`），开关不该跟着它跑。因此 `style.css` 里收起态的
// 选择器必须是**后代**形式（`.dw ` + `.rail-min …`），不能把两者复合成一个选择器 ——
// 详见 `[M0]` 段那段注释，那是踩出来的（写错了浏览器里一点效果都没有，而用例全绿）。

/** localStorage 键。**测试里有断言依赖这个字面值**，改它要一起改用例。 */
export const RAIL_MIN_KEY = 'dw_rail_min'

/** 收起态（true = 58px 图标态）。 */
export const railMin = ref(false)

/** 当前选中的导航项 key（由外壳按地址算出来塞进来，rail 自己不读地址）。 */
export const activeNav = ref('read')

/** 收起态下 `.dw` 要挂的类（与 `.rail` 的宽度过渡同一处开关）。 */
export const railClass = computed(() => (railMin.value ? 'rail-min' : ''))

/**
 * 读回上次的收起态。
 *
 * ⚠️ **必须容错**：隐私模式 / 禁 cookie 的浏览器里 `localStorage` 一读就抛，
 * 那时按"展开"渲染即可——**不能因为读不到偏好就白屏**。
 */
export function loadRailMin() {
  try {
    railMin.value = localStorage.getItem(RAIL_MIN_KEY) === '1'
  } catch {
    railMin.value = false
  }
}

/** 写下收起态（同样容错：写不进去就只影响"下次记住"，不影响本次交互）。 */
export function persistRailMin() {
  try {
    localStorage.setItem(RAIL_MIN_KEY, railMin.value ? '1' : '0')
  } catch {
    /* 存不了就算了，本次会话内的收起仍然生效 */
  }
}

/** 切换收起 / 展开（顶部按钮与 `Ctrl+B` 走同一个函数，保证两条路行为一致）。 */
export function toggleRail() {
  railMin.value = !railMin.value
  persistRailMin()
}

// ============================================================ 阅读区副页签

/** 右助手当前副页签：问答 / 导读 / 术语（页签数不再增加）。 */
export const assistTab = ref('ask')
