<script setup>
/**
 * docwise 前端外壳：**登录分发 + 路由分发 + 各视图挂载点 + 弹层**。
 *
 * 形态与样式**全部照** `frontend/prototype/product-form.html`（设计权威）搬过来——
 * 那部分内容现在拆在 `views/`（库页 / 阅读工作区的模板）与 `stores/`（状态与操作）里，
 * 这个文件只剩"该显示谁"这一层。
 *
 * - 结构：模板里的层级与类名与原型一一对应（topbar / lib-wrap / hero / upload-card /
 *   grid3 / reader-top / thin-bar / note-line / doc-pane / assist / tabs / chips /
 *   thread / guide-card / termlist / composer / sheet / toast …）；
 * - 交互：原型末尾那段命令式 JS 已经**重写成响应式状态**（openMenu / assistTab /
 *   flashId / sheetState / selChip / toast …），不再用 querySelector 查改 DOM；
 *   只有"把某一段滚进视野"本来就必须命令式，用模板 ref 做，不用 getElementById。
 *
 * 三条不能违反的硬约束（都写在 docs/产品形态说明.md 第四节）：
 * ① 出处永远说人话（2026-09-17 口径修订后是「第 X 页 ·「这一句的开头…」」——**不再说第几段**，
 *   段号靠 PDF 版面切分算、在没见过的期刊上只有五六成准，不准的段号比没有更糟；块编号只进 title / 详情）；
 * ② 死链不许做成活链样式（无出处的要点置灰不可点，并说明为什么没有）；
 * ③ 坐标只在有出处时才显示（术语表没有出处字段 → 命中后才回填）。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import { apiUrl } from './api'
import {
  clearToken,
  fetchMe,
  getToken,
  logout as apiLogout,
  setToken,
  setUnauthorizedHandler,
} from './auth'
import AdminView from './components/AdminView.vue'
import AppRail from './components/AppRail.vue'
import RailAccount from './components/RailAccount.vue'
import AppStatusBar from './components/AppStatusBar.vue'
import AppTabbar from './components/AppTabbar.vue'
import LoginView from './components/LoginView.vue'
import TaskPanels from './components/TaskPanels.vue'
import { buildHash, currentRoute, navigate, onRouteChange } from './router'
import { initAsk, lastQuestion } from './stores/useAsk'
import {
  fileInput,
  initLibrary,
  libraryEmpty,
  loadTasksAndSync,
  onFilePicked,
  selectedTier,
  syncActiveDetail,
  disposeLibrary,
} from './stores/useLibrary'
import {
  blocks,
  currentTask,
  disposeReader,
  initReader,
  loadBlocks,
  openTask,
  pickedBlockId,
  selChip,
  stopProgress,
} from './stores/useReader'
import { clearTasks, tasks } from './stores/useTasks'
import { checkOpen, openCheck, resetWrite } from './stores/useWrite'
import {
  activeNav,
  closeMenus,
  disposeUi,
  loadRailMin,
  openMenu,
  railClass,
  railMin,
  runToastUndo,
  setNote,
  showToast,
  syncNarrow,
  toast,
  toggleMenu,
  toggleRail,
} from './stores/useUi'
import LibraryView from './views/LibraryView.vue'
import MeView from './views/MeView.vue'
import ProcessView from './views/ProcessView.vue'
import MemoryView from './views/MemoryView.vue'
import ReadView from './views/ReadView.vue'
import WriteView from './views/WriteView.vue'
import { NConfigProvider, NSpin, zhCN, dateZhCN } from 'naive-ui'

// ============================================================ 屏与账号

/** L1 库页 / L2 阅读工作区。回 L1 **不清 currentTask**——后台翻译的进度还要继续推。 */
const view = ref('library')
const authUser = ref(null)
const authChecking = ref(true)
const authNotice = ref('')
const demoAutologin = ref(false)
const showAdmin = ref(false)
const backendStatus = ref('checking')
const healthInfo = ref(null)

// ============================================================ 偏好（M5 个人中心那一页存的）
//
// ⚠️ 偏好**只存在本机** `localStorage.docwise_prefs`：契约的 N 清单里没有偏好接口
// （后端没这项，也不该为它破 6 依赖红线），所以"换设备不跟着走"是如实口径。
// 这里做的是把 M5 那一页存下来的东西**真的消费掉**——在那之前它只写不读，
// 界面上改了字号/档位/动效**一点反应都没有**（"看起来能用其实没用"）。
const PREFS_KEY = 'docwise_prefs'
/** 阅读字号 → `--fs-scale`（只乘阅读类字号：正文 / 正文英文 / 译文，见 style.css 的 token 注释）。 */
const FS_SCALE = { small: 0.92, normal: 1, large: 1.12 }

function readShellPrefs() {
  try {
    const raw = JSON.parse(localStorage.getItem(PREFS_KEY) || '{}')
    return {
      tier: raw.tier === 'fast' || raw.tier === 'medium' ? raw.tier : 'medium',
      readingSize: FS_SCALE[raw.readingSize] ? raw.readingSize : 'normal',
      // 这一项的意思是"**跟随系统**"：勾上之后系统开了「减少动态效果」就压掉动效
      reducedMotion: Boolean(raw.reducedMotion),
    }
  } catch {
    return { tier: 'medium', readingSize: 'normal', reducedMotion: false }
  }
}

const shellPrefs = ref(readShellPrefs())
/** 字号偏好 → 根上的 `--fs-scale`（`.dw` 是 token 定义处，就地覆盖）。 */
const shellStyle = computed(() => ({ '--fs-scale': FS_SCALE[shellPrefs.value.readingSize] ?? 1 }))
/** 勾了"动效跟随系统"才挂这个属性：CSS 里只有它挂上、且系统真的要求减少动效时才压制（见 style.css）。 */
const motionMode = computed(() => (shellPrefs.value.reducedMotion ? 'system' : 'full'))

/** 偏好在个人中心改完 → 外壳当场跟上（同一页里改完不用刷新）。 */
function reloadShellPrefs() {
  shellPrefs.value = readShellPrefs()
  selectedTier.value = shellPrefs.value.tier
}

const isAdmin = computed(() => authUser.value?.role === 'admin')
const accountLabel = computed(() => {
  const user = authUser.value
  if (!user) return ''
  return `${user.username}（${user.role === 'admin' ? '管理员' : '普通用户'}）`
})

/**
 * 把外壳才有的能力交给 store。
 *
 * `stores/useReader` / `stores/useLibrary` 都**不 import 这个文件**（那就绕成环了），
 * 所以由这里注入——与 `useAsk` 的 `initAsk()` 同一个路子，也与它在一行里调用。
 * 下面的 `navigateToHash` / `loadTasksAndSync` 是函数声明，会提升，所以引用它们是安全的。
 */
initAsk({ blocks, currentTask, loadBlocks })
initReader({ view, navigateToHash, loadTasksAndSync })
initLibrary({ view, navigateToHash })

/** 手机抽屉收起时那一行摘要（要显示"当前问题"，所以依赖 useAsk 的 lastQuestion，
 *  这也正是它不放进 useUi 的原因——放进去两个 store 就绕成环了）。 */
const peekSummary = computed(() =>
  lastQuestion.value
    ? `当前问题：${lastQuestion.value}`
    : '读到有问题的地方，点段落浮出「就这段提问」',
)

// ============================================================ 数据加载（后端健康检查）

async function checkBackend() {
  try {
    const res = await fetch(apiUrl('/api/health'))
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const health = await res.json()
    healthInfo.value = health
    backendStatus.value = health.status === 'ok' ? 'ok' : 'degraded'
    demoAutologin.value = Boolean(health.auth && health.auth.demo_autologin)
  } catch {
    backendStatus.value = 'down'
  }
}

// ============================================================ 哈希路由
//
// 分工：**状态是唯一真源，地址跟着状态走**。
// - 主动切页（点卡片 / 点返回）→ 先改状态，再把地址写上（`openTask` / `backToLibrary`）；
// - 被动切页（用户按后退、改地址栏、刷新）→ 地址变了，`syncFromRoute` 把状态对上。
//
// ⚠️ **防来回触发**：写地址时把目标 hash 记进 `expectedHash`，
// 紧接着到达的那一次 `hashchange` 一看目标一致就知道"是我们自己写的"，直接返回、不重复加载。
// 这个不能省：`openTask` 会真的去拉数据，重复触发就是白白拉两遍。

/** 我们自己刚写下的 hash（= 正在等待的那个 hashchange）。 */
let expectedHash = ''
/** 路由订阅的取消函数（组件卸载时要调，否则监听会越积越多）。 */
let stopRouteWatch = null
/** 启动时的"回原页"只做一次——不能让后续任何一次登录都重新跳一次。 */
let bootRouteApplied = false

/** 改地址，并记下这是"我们自己写的"（广播与去重都在 router.js 里，这里只管接线）。 */
function navigateToHash(target, { replace = false } = {}) {
  const hash = buildHash(target.name, target.params || {})
  if (window.location.hash === hash) return
  expectedHash = hash
  navigate(target.name, target.params || {}, { replace })
}

/** 地址 → 状态的唯一入口。**它只做"该显示什么"，不自己拼地址**（那会绕开 `expectedHash` 防抖）。 */
async function syncFromRoute() {
  const route = currentRoute()
  // 左栏选中态跟着地址走。**在这里同步而不是散在各处 go**：`syncFromRoute` 是
  // "地址变了"的唯一入口（主动切页 / 后退 / 刷新都汇到这里），一处就够了。
  // ⚠️ 库页算「读懂」这个模块（形态 §1.2 的布局图：读懂 → 书单 → 选一篇进阅读区），
  // 所以 `library` 与 `read` 都亮「读懂」；下段的「全部文献」要等 R5 把首页换成"我的库"再分。
  activeNav.value = route.name === 'library' ? 'read' : route.name

  if (route.name === 'library') {
    if (view.value !== 'library') view.value = 'library'
    return
  }

  if (route.name === 'read') {
    const id = route.params.taskId
    // `router.js` 已经把不合法的任务号挡在外面（落库页），所以走到这里必有 id；
    // 这一段是防御性的：真出现了也别硬编一个号去请求，如实说 + 回库页（replace，免得后退打转）
    if (!id) {
      showToast('这条地址里没有有效的论文编号，已回到「我的论文」')
      navigateToHash({ name: 'library' }, { replace: true })
      return
    }
    if (view.value === 'reader' && currentTask.value?.id === id) return
    const task = tasks.value.find((item) => item.id === id)
    if (!task) {
      // 还没有任务列表（或这一篇不属于当前账号）时，交给后端如实回答：
      // `refreshWorkbench` 对不存在的任务会走既有的报错路径，不在这里硬编一套
      if (!tasks.value.length && getToken()) await loadTasksAndSync()
    }
    const found = tasks.value.find((item) => item.id === id)
    if (!found) {
      showToast('找不到这篇文献——可能已被删除，或不属于当前账号')
      navigateToHash({ name: 'library' }, { replace: true })
      return
    }
    // 状态已经是它了就不重复加载（这是防抖的最后一道，也是刷新时唯一的入口）
    if (view.value === 'reader' && currentTask.value?.id === id) return
    await openTask(found, { skipHash: true })
    return
  }

  // M3 起草页（`#/write`）：**不依赖读懂**，可直达（契约 §2.6 / 形态 §3.2）。
  // 起草页自己管取数（草稿 / 素材 / 引文），所以这里只切屏，不预加载任何东西。
  if (route.name === 'write') {
    if (view.value !== 'write') view.value = 'write'
    return
  }

  // M5 处理过程（`#/process`）：整页，自己取台账（契约 N17）。
  // 与起草页同理：**这里只切屏**，取数归页面自己（它还要管筛选与下钻）。
  if (route.name === 'process') {
    if (view.value !== 'process') view.value = 'process'
    return
  }

  // M7 记忆（`#/memory`）：整页，自己取数（N35–N39）。与上两页同理，**这里只切屏**。
  if (route.name === 'memory') {
    if (view.value !== 'memory') view.value = 'memory'
    return
  }

  // 离开个人中心时**把偏好重新读一遍**：那一页改完字号/档位/动效，
  // 外壳当场跟上（不刷新页面也能看到效果；下次进来也还在）。
  if (view.value === 'me' && route.name !== 'me') reloadShellPrefs()

  // M5 个人中心（`#/me`）：整页，自己管取数（四个 `me/*` 请求各自容错）。
  if (route.name === 'me') {
    if (view.value !== 'me') view.value = 'me'
    return
  }

  // 管理后台（`#/admin`）：**不是新做一页**，就是把账号菜单里那个现成的面板打开
  // （`showAdmin`），所以地址与屏是同一件事——以前这里是"还没做"的提示，那是假的：
  // 后台一直在，只是没有地址。同时把 URL 留着，刷新/后退都还在后台。
  if (route.name === 'admin') {
    showAdmin.value = true
    return
  }
  // 从后台回别的页（浏览器后退 / 点我们自己那条「回我的论文」）→ 面板跟着关
  if (showAdmin.value && route.name !== 'admin') showAdmin.value = false

  // ⭐ **现在已经没有"还没做的页面"了**：`#/process`（E15）与 `#/memory`（M7）都做出来了。
  // 这里原来有一张 `NOT_BUILT_YET` 表，作用是"如实说它还没做、然后回库页，绝不白屏"。
  // ⚠️ **以后再加页面时**：要么真做出来（并在上面加一条切屏分支），要么把那张表加回来——
  // **只加路由不加分支，结果就是"地址变了、屏没变"**（比白屏还难查；这次真踩到了：
  // 在 JS 里直接改 `#/memory` 时地址对了、页面还是库页）。
}

/** 订阅地址变化。 */
function startRouteWatch() {
  if (stopRouteWatch) return
  stopRouteWatch = onRouteChange((route) => {
    const hash = buildHash(route.name, route.params || {})
    if (hash === expectedHash) {
      expectedHash = '' // 是我们自己写的那一次，状态早就改好了
      return
    }
    syncFromRoute()
  })
}

/** 启动时按地址回到该在的页（刷新不丢页 / PWA 从主屏进来回到原处）。只做一次。 */
async function applyBootRoute() {
  if (bootRouteApplied) return
  bootRouteApplied = true
  const route = currentRoute()
  if (route.name === 'library') return
  await syncFromRoute()
}

// ============================================================ 左栏导航
//
// ⚠️ 左栏是**哑组件**（`components/AppRail.vue` 不 import 任何 store、不读 location.hash），
// 所以"点了去哪个地址"这一层映射留在外壳 —— 契约 §0.5：**`location.hash` 只在 `router.js` 里读写**。

/**
 * 左栏每一项落到哪。`go` 给 `navigateToHash` 的目标；`note` 是**还没做的页**的诚实说法
 * （形态 v2 的分期任务：M1 知识库 / M3 起草 / M4 收口 / M5 处理过程 / M7 记忆）。
 * ⚠️ 两者**必须给一个**：既没有 `go` 也没有 `note` 的项点了会像没反应（判据①是"都能点"）。
 */
const RAIL_TARGETS = {
  read: { go: { name: 'library' } },
  write: { go: { name: 'write' } },
  check: { go: { name: 'write' }, opens: 'check' },
  // 「全部文献」= 回库页**并清掉筛选**（不传 filter 会沿用上一次的条件，那就不是"全部"了）
  'lib-all': { go: { name: 'library' }, filter: {} },
  'lib-collections': { note: '集合列表接口（契约 N1）还没做——筛选条上的「集合」那一行等它', },
  'lib-tags': { note: '标签列表接口（契约 N6）还没做——筛选条上的「标签」那一行等它' },
  // ⭐「待读」是一条**真的智能集合**（规则：状态 = 待读）：N8 已经能按 `reading_status` 筛了，
  // 所以这里不再是"还没做"的提示，而是带着条件进库页（以后智能集合列表接口上来，
  // 这条要改成读 N9 返回的规则、按 `smart_id` 筛）。
  'lib-todo': { go: { name: 'library' }, filter: { reading_status: 'todo' } },
  'lib-materials': { note: '素材列表接口（契约 N13）还没做——素材已经能在起草页左栏里用', },
  'lib-drafts': { note: '草稿列表页还没做——你的草稿在「起草」页里（点左上「起草」）' },
  'lib-refs': { note: '引用列表页还没做——引文在「起草」页的「引用」页签里看' },
  // ⭐ 记忆页（M7）已经做出来：真跳 `#/memory`（N35–N39，自己的表、不是台账）
  memory: { go: { name: 'memory' } },
  // ⭐ 处理过程一屏（E15）已经做出来：真跳 `#/process`（吃 N17 那张台账，与「我的」页同源）
  process: { go: { name: 'process' } },
}

/** 点左栏一项：**先动状态，地址跟着状态走**（与 `backToLibrary` 同一个规矩）。 */
function onRailSelect(key) {
  const target = RAIL_TARGETS[key]
  if (!target) return
  closeMenus()
  if (target.note) showToast(target.note)

  // ⚠️ **顺序不能反**（`backToLibrary` 那条注释讲的就是这个坑）：
  // `navigateToHash` 会把目标 hash 记进 `expectedHash`，紧接着到达的 `hashchange`
  // 一看目标一致，就断定"这是我们自己写的那次、状态早就改好了" → **直接 return，不调 `syncFromRoute`**。
  // 所以"只写地址、不设状态"会让界面**停在原地**（地址变了、屏没变）—— 第一次实现就踩了，
  // 靠"点起草之后 `#/` 变了但 `.lib-wrap` 还不存在"这条用例抓出来。
  //
  // 现在左栏能真正打开的有两处（库页与起草页），所以两样状态都在这一处显式设对：
  // `view` 决定渲染哪一屏，`activeNav` 决定左栏哪一项亮着（那次 hashchange 被吞了，
  // `syncFromRoute` 不会替我们做这件事）。
  const go = target.go || { name: 'library' }
  // ⭐「收口」= 进起草页**并当场拉开检查抽屉**（形态 §3.3：收口是起草页里的抽屉，不是新页面）
  if (target.opens === 'check') openCheck()
  // ⭐ 整页只有这四张（起草 / 个人中心 / 处理过程 / 记忆）；其余一律回库页
  const PAGES = { write: 'write', me: 'me', process: 'process', memory: 'memory' }
  view.value = PAGES[go.name] || 'library'
  activeNav.value = PAGES[go.name] ? go.name : 'read'
  // ⭐ 带筛选条件的入口（「待读」= 智能集合"状态 = 待读"；「全部文献」= 清掉筛选）：
  // **不止跳过去，还要真的筛**——N8 的四个参数已经在后端了（契约 §2.2）。
  if (target.filter) loadTasksAndSync(target.filter)
  navigateToHash(go)
}

// ============================================================ 手机底部标签栏（R6）
//
// 形态 v2 §2.3：**手机端（<720px）左栏换成底部标签栏 5 个** ——
// **库 / 起草 / 检查 / 记忆 / 我的**。命名口径（§2.3 原文）：桌面叫「收口」、
// 手机标签因字数显示「检查」；第一个叫「**库**」不叫「读懂」（窄屏用户看到"读懂"会以为进的是阅读页）。
// ⚠️ 形态 §2.3 的产品判断：**不在手机上做精读**；⚠️ 不许在手机上照搬"左下角头像"。

/**
 * ⚠️ **为什么单独算一个 `isPhone`，而不是用 `isNarrow`**：
 * `stores/useUi.js` 的 `isNarrow` 是 **<1024**（它是"左栏收起 / 助手换抽屉"那几档用的），
 * 而形态文档给标签栏的档位是 **<720**（§2.3）。两处阈值不一致是**已知问题**、
 * 由外壳负责人拍板怎么统一 —— 本卡按文档那一档实现，**不动 `isNarrow`**。
 */
const isPhone = ref(false)

function syncPhone() {
  isPhone.value = window.innerWidth < 720
}

/** 5 个标签。图标名都取自 `index.html` 的 sprite（5 个都已存在，不是新画的）。 */
const MOBILE_TABS = [
  { key: 'library', label: '库', icon: 'layers' },
  { key: 'write', label: '起草', icon: 'pen' },
  { key: 'check', label: '检查', icon: 'check-search' },
  { key: 'memory', label: '记忆', icon: 'gear' },
  { key: 'me', label: '我的', icon: 'user' },
]

/**
 * 标签落到哪：**复用左栏那张表**（`RAIL_TARGETS` 是导航的唯一真源，
 * 在这里再写第二套地址映射＝迟早两套地址不一致）。
 * 「我的」不在 `RAIL_TARGETS` 里（桌面那条路只有顶栏账号菜单），所以单独在 `onTabSelect` 里处理。
 */
const TAB_TARGETS = {
  library: 'lib-all', // 「库」= 回库页**并清筛选**（与左栏「全部文献」同一条路）
  write: 'write',
  check: 'check', // 「检查」= 进起草页并当场拉开检查抽屉（形态 §3.3：收口是抽屉不是新页面）
  memory: 'memory',
  me: 'me',
}

/**
 * 当前该亮哪一个：按**屏**算，不读 `location.hash`（契约 §0.5：地址只在 `router.js` 里读写）。
 * `view === 'reader'`（正在读一篇）也归「库」—— 手机上读文献是从库里点进去的，
 * 而形态 §2.3 明确**不做精读标签**。
 */
const tabbarActive = computed(() => {
  if (view.value === 'me') return 'me'
  if (view.value === 'write') return checkOpen.value ? 'check' : 'write'
  // 「处理过程」**不是手机标签栏上的一项**（形态 §2.3 定死 5 个）→ 一个都不亮，
  // 别回落到 'library' 把「库」点亮（那会让人以为自己在库里）
  if (view.value === 'process') return ''
  return 'library'
})

/**
 * 进个人中心。左栏底部账号区（R7）与手机标签栏「我的」（R6）**走同一条路**：
 * 「先动状态、地址跟着状态走」——理由与 `onRailSelect` 上那段注释同源
 * （`navigateToHash` 会把目标 hash 记进 `expectedHash`，紧接着的 `hashchange` 便不再替我们设状态）。
 * ⚠️ `RAIL_TARGETS` 里**没有** `me` 这一条（桌面那条路到 R7 才有入口），所以它单独成函数，
 * 两个入口都调它，避免两处各写一遍顺序。
 */
function goMe() {
  closeMenus()
  view.value = 'me'
  activeNav.value = 'me'
  navigateToHash({ name: 'me' })
}

/** 点一条标签：走与左栏**同一条路**（"先动状态、地址跟着状态走"的完整理由在 `onRailSelect` 上）。 */
function onTabSelect(key) {
  const railKey = TAB_TARGETS[key]
  if (!railKey) return
  // 「我的」：左栏表里没有这一条，所以这一处单独设状态 + 写地址（与 `onRailSelect` 同一顺序）
  if (railKey === 'me') {
    goMe()
    return
  }
  onRailSelect(railKey)
}

/** 关掉管理后台并回库页：**地址与屏一起改**（只改一个会让刷新回到后台、像关不掉）。 */
function closeAdmin() {
  showAdmin.value = false
  navigateToHash({ name: 'library' })
}

// ============================================================ 账号与会话

onMounted(async () => {
  // 收起态先读回来（刷新后仍是收起的样子 —— R4 判据④）
  loadRailMin()
  syncNarrow()
  syncPhone()
  // 偏好里的「翻译档位」= 上传卡的默认档位（M5 存下来的东西在这里被消费掉）
  selectedTier.value = shellPrefs.value.tier
  window.addEventListener('resize', syncNarrow)
  window.addEventListener('resize', syncPhone)
  window.addEventListener('keydown', onGlobalKeydown)
  setUnauthorizedHandler(handleUnauthorized)
  startRouteWatch()
  await checkBackend()
  await restoreSession()
})

/**
 * 全局快捷键：`Esc` 取消段落精读里的选中；`Ctrl+B`（macOS `Cmd+B`）收起 / 展开左栏。
 *
 * ⚠️ `Ctrl+B` 要与主流编辑器一致（形态 §1.2b）。`preventDefault()` 必须调：
 * 浏览器把 `Ctrl+B` 占给了书签侧栏，不拦的话地址栏会跳出去、焦点丢失。
 */
function onGlobalKeydown(event) {
  if ((event.ctrlKey || event.metaKey) && (event.key === 'b' || event.key === 'B')) {
    event.preventDefault()
    toggleRail()
    return
  }
  if (event.key !== 'Escape') return
  selChip.value = null
  pickedBlockId.value = ''
}

onUnmounted(() => {
  window.removeEventListener('resize', syncNarrow)
  window.removeEventListener('resize', syncPhone)
  window.removeEventListener('keydown', onGlobalKeydown)
  if (stopRouteWatch) stopRouteWatch()
  stopProgress()
  // 定时器都跟着状态搬进了各自的 store，由它们自己收尾
  // （原来在本地声明，搬走之后这里再 clear 就会报 `xxxTimer is not defined`——上一轮真踩过）
  disposeUi()
  disposeReader()
  disposeLibrary()
})

watch(view, () => {
  if (view.value === 'library') syncActiveDetail()
})

async function restoreSession() {
  authChecking.value = true
  try {
    if (getToken()) {
      authUser.value = await fetchMe()
      await loadTasksAndSync()
      // 任务列表就位之后再按地址回原页（顺序不能反：`#/read/12` 要先能在库里找到 12）
      await applyBootRoute()
    }
  } catch {
    authUser.value = null
  } finally {
    authChecking.value = false
  }
}

async function onLoginSuccess({ token, user, remember }) {
  setToken(token, remember)
  authUser.value = user
  authNotice.value = ''
  showAdmin.value = false
  await loadTasksAndSync()
  // 登录后同样按地址回到该在的页（例：分享出去的 `#/read/12`，登录完直接落在那篇上）
  await applyBootRoute()
}

async function onLogout() {
  closeMenus()
  try {
    await apiLogout()
  } catch {
    clearToken()
  }
  authUser.value = null
  currentTask.value = null
  clearTasks()
  // 起草页的状态也要清：不清的话，换个人登录会先看到上一个人的草稿（哪怕一秒）
  resetWrite()
  showAdmin.value = false
  stopProgress()
  // 退出后回库页并清掉地址里的那一篇（否则换个账号登录还会去开上一个账号的任务号）；
  // 同时把"启动只做一次"的闸放开，让下一个账号登录时还能按地址落位。
  navigateToHash({ name: 'library' }, { replace: true })
  bootRouteApplied = false
}

function handleUnauthorized() {
  authUser.value = null
  showAdmin.value = false
  stopProgress()
  resetWrite()
  authNotice.value = '登录已过期，请重新登录'
}
</script>

<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN">
    <!-- 正在用已存令牌恢复登录态 -->
    <div v-if="authChecking" class="boot-screen">
      <n-spin size="large" />
    </div>

    <!-- 未登录：整页登录 / 注册 -->
    <LoginView v-else-if="!authUser" :demo-autologin="demoAutologin" @success="onLoginSuccess" />

    <!-- ⭐ 根上挂 `has-tabbar`：手机档才有底部标签栏，内容列据此让出等高下边距
         （**由 JS 决定"有没有"，CSS 只管几何**——两处各判一次阈值必然漂移）。 -->
    <div
      v-else
      class="dw"
      :class="{ 'has-tabbar': isPhone }"
      :style="shellStyle"
      :data-motion="motionMode"
      @click="closeMenus"
    >
      <!-- 管理后台（M5）：面板本身没有返回口（v1 从账号菜单进来，只能刷出去）。
           既然 `#/admin` 现在是真地址，就得有个正常的出口——否则从地址进来的人被困住。 -->
      <template v-if="showAdmin">
        <div class="admin-backbar">
          <button class="btn ghost sm" @click="closeAdmin">← 回我的论文</button>
          <span class="admin-backbar-tip">管理后台 · 也可以直接用浏览器后退</span>
        </div>
        <AdminView class="admin-page" />
      </template>

      <div v-else class="dw-layout" :class="railClass">
        <!-- ==================== 左栏（常驻，260 ⇄ 58） ==================== -->
        <aside class="rail">
          <AppRail :rail-min="railMin" :active-nav="activeNav" @toggle="toggleRail" @select="onRailSelect">
            <!-- ⭐ 账号区挂载点（第 6 步留的座位，**R7 已填上**：`components/RailAccount.vue`）。
                 数据一律由外壳交下去（`accountLabel` / `activeNav === 'me'`），
                 组件本身不认识 store、不读地址 —— `AppRail.vue` 的"哑组件"约定不破。
                 点它走 `goMe()`，与手机标签栏「我的」同一条路。 -->
            <template #account>
              <RailAccount
                :label="accountLabel"
                :active="activeNav === 'me'"
                @select="goMe"
              />
            </template>
          </AppRail>
        </aside>

        <!-- ==================== 右侧内容列 ==================== -->
        <div class="dw-main">
          <!-- ==================== L1 库页 ==================== -->
          <section v-if="view === 'library'">
            <div class="topbar">
              <span class="brand">docwise</span>
              <span class="brand-sub">学术文献理解智能体</span>
              <span class="spacer" />
              <span v-if="authNotice" class="tiny" style="color: var(--danger)">{{ authNotice }}</span>
              <button v-if="libraryEmpty" class="btn ghost sm" @click="loadTasksAndSync">我的论文</button>
              <!-- 管理后台收进账号菜单（仅管理员可见），不占顶栏主位 -->
              <div class="menu-wrap">
                <button class="btn ghost sm" @click.stop="toggleMenu('acct')">
                  {{ authUser.username }} ▾
                </button>
                <div class="menu" :class="{ open: openMenu === 'acct' }">
                  <button @click="setNote('当前账号：' + accountLabel)">{{ accountLabel }}</button>
                  <button v-if="isAdmin" @click="showAdmin = true">管理后台</button>
                  <button @click="onLogout">退出</button>
                </div>
              </div>
            </div>
            <LibraryView />
          </section>

          <!-- ==================== M3 起草页（#/write 三栏） ====================
               ⚠️ 必须排在阅读区**前面**判断：`view` 是唯一真源，
               而从起草页点 [1] 跳回原文之后 `currentTask` 还在，
               若先判 `currentTask` 就会"地址是 #/write、屏停在阅读区"。 -->
          <section v-else-if="view === 'write'" class="screen-write">
            <WriteView />
          </section>

          <!-- ==================== M5 个人中心（#/me 整页） ====================
               与起草页同理：**必须排在阅读区前面判断**（`view` 是唯一真源），
               否则"在读一篇 + 点 #/me"会被 `currentTask` 那条分支吃掉、屏停不动。 -->
          <section v-else-if="view === 'me'" class="screen-me">
            <MeView />
          </section>

          <!-- ==================== M5 处理过程（#/process 整页） ====================
               同样**必须排在阅读区前面判断**（理由同上面两张整页）：
               否则"正在读一篇 + 点左栏「处理过程」"会被 `currentTask` 那条分支吃掉。 -->
          <section v-else-if="view === 'process'" class="screen-process">
            <ProcessView />
          </section>

          <!-- ==================== M7 记忆（#/memory 整页） ====================
               与上两张同理：**必须排在阅读区前面判断**，
               否则"正在读一篇 + 点左栏「记忆」"会被 `currentTask` 那条分支吃掉。 -->
          <section v-else-if="view === 'memory'" class="screen-memory">
            <MemoryView />
          </section>

          <!-- ==================== L2 阅读工作区 ==================== -->
          <section v-else-if="currentTask" class="screen-reader">
            <ReadView :peek-summary="peekSummary" />
          </section>

          <!-- ⭐ 底部状态条挂载点（R8 的 `AppStatusBar.vue`）。
               这里**不传 slots**，所以组件自门控、整条不渲染 —— 不占屏幕、不写假数据。
               R8 接上 N17（后端 B2 交付）之后，把三个信息位传进来它就出来了 ——
               **外壳这一行不用再改**（第 7 步"预留挂载点"要的就是这个）。
               放在 `.dw-main` 里（内容列底部）：它与内容列同宽、在左栏右侧，跟原型一致。 -->
          <AppStatusBar />
        </div>
      </div>

      <!-- ⭐ 手机底部标签栏（R6 已接线：形态 v2 §2.3 的 **库 / 起草 / 检查 / 记忆 / 我的**）。
           ⚠️ 放在 `.dw-layout` **之外**是**必须的两件事之一**：
           ① 留在布局之外 → 不被 `height:100dvh; overflow:hidden` 裁掉；
           ② 样式里 `position:fixed` → 真的贴视口底（留在外面但在正常流里，它会排到
              100dvh 之后 = **屏幕外**，这正是窄屏走查指出的隐患）。
           内容不被盖住不靠这里，靠根上的 `has-tabbar` 类（`.dw-main` 让出等高下边距，含安全区）。
           ⚠️ 只在**手机档（<720）**出现，见脚本里 `isPhone` 的说明（不动 `isNarrow` 的 1024）。 -->
      <AppTabbar
        v-if="isPhone"
        :tabs="MOBILE_TABS"
        :active="tabbarActive"
        @select="onTabSelect"
      />

      <!-- 隐藏的文件选择器（上传 / 换档位重译都用它） -->
      <input ref="fileInput" type="file" accept="application/pdf" class="hidden-file" @change="onFilePicked" />

      <!-- 任务弹层：文档信息 / 详情 / 问题反馈 / 删除确认 / 换档位重译 -->
      <TaskPanels />

      <!-- toast：阅读位置提示 / 可撤销的动作 -->
      <div class="toast" :class="{ show: toast.show }">
        <span>{{ toast.text }}</span>
        <button v-if="toast.undoLabel" @click="runToastUndo">{{ toast.undoLabel }}</button>
      </div>
    </div>
  </n-config-provider>
</template>
