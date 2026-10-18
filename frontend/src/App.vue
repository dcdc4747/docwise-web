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
import AgentSettings from './components/AgentSettings.vue'
import { buildHash, currentRoute, navigate, onRouteChange } from './router'
import { initAsk, lastQuestion } from './stores/useAsk'
import { loadPrefs } from './stores/usePrefs'
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
import MaterialsView from './views/MaterialsView.vue'
import ReadHomeView from './views/ReadHomeView.vue'
import CollectionsView from './views/CollectionsView.vue'
import TagsView from './views/TagsView.vue'
import TrashView from './views/TrashView.vue'
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
  // ⚠️ **离开管理后台时必须先把面板关掉，且必须放在所有 early return 之前**。
  // 以前这行在函数末尾：点左栏 / 改地址时上面那些分支先 `return` 了，
  // 这行永远走不到 → 面板一直盖着、目标页压根不渲染（用户报的"管理后台做的有问题"）。
  if (showAdmin.value && route.name !== 'admin') showAdmin.value = false
  // 左栏选中态跟着地址走。**在这里同步而不是散在各处 go**：`syncFromRoute` 是
  // "地址变了"的唯一入口（主动切页 / 后退 / 刷新都汇到这里），一处就够了。
  // ⭐ 2026-10-17 起「读懂」和「全部文献」是**两个不同的页面**：
  //    读懂工作台 / 阅读页 → 亮「读懂」；历史记录 → 亮下段的「全部文献」。
  activeNav.value = NAV_OF_ROUTE[route.name] || route.name

  // ⭐ 读懂工作台（`#/read`）：上传 / 示例 / 继续读 / 最近三篇。
  // 它要"最近三篇"，所以顺手把列表拉一次（已有列表就不重复拉）。
  if (route.name === 'readHome') {
    if (view.value !== 'readHome') view.value = 'readHome'
    if (!tasks.value.length && getToken()) await loadTasksAndSync()
    return
  }

  // ⭐ 集合整页（`#/collections`）/ 标签整页（`#/tags`）：自己取数（N1–N6），**这里只切屏**。
  if (route.name === 'collections') {
    if (view.value !== 'collections') view.value = 'collections'
    return
  }
  if (route.name === 'tags') {
    if (view.value !== 'tags') view.value = 'tags'
    return
  }

  // 回收站（`#/trash`）：自己取数（`?trashed=1`），这里只切屏。
  // ⚠️ 教训写在下面那段注释里：**只加路由不加分支 → 地址变了、屏没变**。
  if (route.name === 'trash') {
    if (view.value !== 'trash') view.value = 'trash'
    return
  }

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

  // M3 写作页（`#/write`）：**不依赖读懂**，可直达（契约 §2.6 / 形态 §3.2）。
  // 写作页自己管取数（草稿 / 素材 / 引文），所以这里只切屏，不预加载任何东西。
  if (route.name === 'write') {
    if (view.value !== 'write') view.value = 'write'
    return
  }

  // M5 处理过程（`#/process`）：整页，自己取台账（契约 N17）。
  // 与写作页同理：**这里只切屏**，取数归页面自己（它还要管筛选与下钻）。
  if (route.name === 'process') {
    if (view.value !== 'process') view.value = 'process'
    return
  }

  // M7 记忆（`#/memory`）：整页，自己取数（N35–N39）。与上两页同理，**这里只切屏**。
  if (route.name === 'memory') {
    if (view.value !== 'memory') view.value = 'memory'
    return
  }

  // E2 素材库（`#/materials`）：整页，自己取数（N13 + 集合/标签列表）。**这里只切屏**。
  if (route.name === 'materials') {
    if (view.value !== 'materials') view.value = 'materials'
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
  // （已在函数开头统一处理；这里保留一句说明，免得以后有人又加回末尾）

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
 * （形态 v2 的分期任务：M1 知识库 / M3 写作 / M4 校对 / M5 处理过程 / M7 记忆）。
 * ⚠️ 两者**必须给一个**：既没有 `go` 也没有 `note` 的项点了会像没反应（判据①是"都能点"）。
 */
const RAIL_TARGETS = {
  // ⭐ 2026-10-17 知识库重构：**「读懂」与「历史记录」是两个地方**
  //    读懂 = 开工页（上传 / 示例 / 继续读）；历史记录 = 全部文献 + 筛选。
  read: { go: { name: 'readHome' } },
  write: { go: { name: 'write' } },
  check: { go: { name: 'write' }, opens: 'check' },
  // 「全部文献」= 回**历史记录**并清掉筛选（不传 filter 会沿用上一次的条件，那就不是"全部"了）
  'lib-all': { go: { name: 'library' }, filter: {} },
  // ⭐ 集合 / 标签 两个整页（后端 N1–N6 早就有，此前左栏点了只弹"还没做"）
  'lib-collections': { go: { name: 'collections' } },
  'lib-tags': { go: { name: 'tags' } },
  // ⭐「待读」是一条**真的智能集合**（规则：状态 = 待读）：进历史记录并带上条件
  'lib-todo': { go: { name: 'library' }, filter: { reading_status: 'todo' } },
  // ⭐「未归类」= 没进任何集合的文献（N8 新增的 `unfiled` 参数，Zotero 的 Unfiled 同一件事）
  'lib-unfiled': { go: { name: 'library' }, filter: { unfiled: 1 } },
  // ⭐ 素材库（E2）：真跳 `#/materials`（吃 N13 的 `?collection_id?` / `&tag?`）
  'lib-materials': { go: { name: 'materials' } },
  'lib-trash': { go: { name: 'trash' } },
  // ⚠️「草稿」「引用」**不再放在历史记录这一组**：它们是写作资产，入口在「写作」页里
  //    （草稿在左上角下拉、引文在「引用」页签）——放这儿点了只能弹一句"还没做"，最伤。
  // ⭐ 记忆页（M7）：真跳 `#/memory`（N35–N39，自己的表、不是台账）
  memory: { go: { name: 'memory' } },
  // ⭐ 处理过程一屏（E15）：真跳 `#/process`（吃 N17 那张台账，与「我的」页同源）
  process: { go: { name: 'process' } },
}

/**
 * 地址名 → 左栏高亮项。**两处不是同名**：读懂工作台与阅读页都算「读懂」，
 * 历史记录算下段的「全部文献」。
 */
const NAV_OF_ROUTE = {
  readHome: 'read',
  read: 'read',
  library: 'lib-all',
  collections: 'lib-collections',
  tags: 'lib-tags',
  trash: 'lib-trash',
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
  // 靠"点写作之后 `#/` 变了但 `.lib-wrap` 还不存在"这条用例抓出来。
  //
  // 现在左栏能真正打开的有两处（库页与写作页），所以两样状态都在这一处显式设对：
  // `view` 决定渲染哪一屏，`activeNav` 决定左栏哪一项亮着（那次 hashchange 被吞了，
  // `syncFromRoute` 不会替我们做这件事）。
  const go = target.go || { name: 'readHome' }
  // ⭐「校对」= 进写作页**并当场拉开检查抽屉**（形态 §3.3：校对是写作页里的抽屉，不是新页面）
  if (target.opens === 'check') openCheck()
  // ⭐ 整页只有这几张（读懂工作台 / 历史记录 / 写作 / 素材库 / 集合 / 标签 / 个人中心 / 处理过程 / 记忆）
  const PAGES = {
    readHome: 'readHome',
    library: 'library',
    write: 'write',
    materials: 'materials',
    collections: 'collections',
    tags: 'tags',
  trash: 'trash',
    me: 'me',
    process: 'process',
    memory: 'memory',
  }
  view.value = PAGES[go.name] || 'readHome'
  activeNav.value = NAV_OF_ROUTE[go.name] || go.name
  // ⭐ 带筛选条件的入口（「待读」= 智能集合"状态 = 待读"；「全部文献」= 清掉筛选）：
  // **不止跳过去，还要真的筛**——N8 的四个参数已经在后端了（契约 §2.2）。
  if (target.filter) loadTasksAndSync(target.filter)
  navigateToHash(go)
}

// ============================================================ 手机底部标签栏（R6）
//
// 形态 v2 §2.3：**手机端（<720px）左栏换成底部标签栏 5 个** ——
// **库 / 写作 / 检查 / 记忆 / 我的**。命名口径（§2.3 原文）：桌面叫「校对」、
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
  { key: 'write', label: '写作', icon: 'pen' },
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
  check: 'check', // 「检查」= 进写作页并当场拉开检查抽屉（形态 §3.3：校对是抽屉不是新页面）
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
  // ⭐ 偏好（N40）：恢复会话后跟服务端对一次 → 反写本机缓存 → 外壳（字号/档位/动效）当场跟上。
  //    放 `await` 是因为上传卡的默认档位、阅读区字号都吃这份，晚了会先按旧缓存闪一下。
  await loadPrefs()
  reloadShellPrefs()
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
  // 写作页的状态也要清：不清的话，换个人登录会先看到上一个人的草稿（哪怕一秒）
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
          <button class="btn ghost sm" @click="closeAdmin">← 回历史记录</button>
          <span class="admin-backbar-tip">管理后台 · 点左栏或浏览器后退也能离开</span>
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
          <!-- ==================== 「读懂」开工页（#/read） ====================
               ⭐ 2026-10-17 知识库重构后它是**首屏**：上传 / 示例 / 继续读 / 最近三篇。
               历史上这张"英雄页"被绑在"库里一篇都没有"上（`libraryEmpty`），
               于是有论文的人永远看不到上传入口——这才是"点读懂却是清单"的根因。 -->
          <section v-if="view === 'readHome'">
            <div class="topbar">
              <span class="brand">docwise</span>
              <span class="brand-sub">学术文献理解智能体</span>
              <span class="spacer" />
              <span v-if="authNotice" class="tiny" style="color: var(--danger)">{{ authNotice }}</span>
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
            <ReadHomeView />
          </section>

          <!-- ==================== 「历史记录」（#/library） ==================== -->
          <section v-else-if="view === 'library'">
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

          <!-- ==================== M3 写作页（#/write 三栏） ====================
               ⚠️ 必须排在阅读区**前面**判断：`view` 是唯一真源，
               而从写作页点 [1] 跳回原文之后 `currentTask` 还在，
               若先判 `currentTask` 就会"地址是 #/write、屏停在阅读区"。 -->
          <section v-else-if="view === 'write'" class="screen-write">
            <WriteView />
          </section>

          <!-- ==================== M5 个人中心（#/me 整页） ====================
               与写作页同理：**必须排在阅读区前面判断**（`view` 是唯一真源），
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

          <!-- ==================== E2 素材库（#/materials 整页） ====================
               同理：**必须排在阅读区前面判断**，否则"正在读一篇 + 点左栏「素材」"会被吃掉。 -->
          <section v-else-if="view === 'materials'" class="screen-materials">
            <MaterialsView />
          </section>

          <!-- ==================== 集合（#/collections 整页 · N1–N4） ====================
               2026-10-17 新开：左栏「集合」以前点了只弹"还没做"，而接口与数据一直都在。 -->
          <section v-else-if="view === 'collections'" class="screen-kn">
            <CollectionsView />
          </section>

          <!-- ==================== 标签（#/tags 整页 · N6） ==================== -->
          <section v-else-if="view === 'tags'" class="screen-kn">
            <TagsView />
          </section>

          <!-- ==================== 回收站（#/trash · N44/N45 的入口） ====================
               删除先落这里，不是直接没了。 -->
          <section v-else-if="view === 'trash'" class="screen-kn">
            <TrashView />
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

      <!-- ⭐ 手机底部标签栏（R6 已接线：形态 v2 §2.3 的 **库 / 写作 / 检查 / 记忆 / 我的**）。
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

    <!-- 设置弹窗：自定义配置都在这（输入框旁边只负责选模型） -->
    <AgentSettings />
  </n-config-provider>
</template>
