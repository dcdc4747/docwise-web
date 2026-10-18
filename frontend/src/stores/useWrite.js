/**
 * 写作（M3 / `#/write`）—— 草稿、素材、引文，以及**点 `[1]` 回原文**这条主线。
 *
 * 三条口径（都来自契约，别自己发明）：
 *
 * ① ⚠️ **正文一个字都不替用户生成**：这个模块里**没有任何**生成/补全/改写的调用，
 *    它只做四件事——拉草稿、存草稿、插引文、跳回原文。界面上的文案也照这条写。
 * ② ⭐ **"点 `[1]` 回原文"靠 `citation.material_id` → 素材的 `task_id`/`block_id`**
 *    （契约 §2.7 明写这条路径）。素材的 `task_id` 为 null = 源文献已删 →
 *    **如实说"仅存快照"，绝不做死链装活链**。
 * ③ **草稿只存当前稿**（契约 §5：不建版本历史表），所以"过程"页签只记**本次会话**
 *    做了什么，不假装有跨会话的历史。
 *
 * ⚠️ **状态定义在模块顶层（单例）**，理由与 `useReader` / `useUi` 一样：
 * 定义在函数里的话，跳回原文再回来就是另一份草稿了（"我明明写了一半"就是这么丢的）。
 *
 * ⚠️ **它 import `useReader`，但 `useReader` 不 import 它** —— 单向依赖，不绕环。
 * 跳转本身复用阅读区那套 `openTask` + `traceTo`，**不另写一套定位**（D7 判据原话）。
 */

import { computed, ref, watch } from 'vue'

import { apiJson } from '../auth'
import { insertMarker } from '../writeText'
import { findTask } from './useTasks'
// 素材卡的状态与写入路径在 `useMaterials`（M2 的 N12–N14）。这里 import 进来，
// 既让下面的素材引用照常工作，也不破坏既有的 `from './useWrite'` 导入。
import {
  loadMaterials,
  materials,
  materialsError,
  materialsLoading,
  resetMaterials,
} from './useMaterials'
import { fetchTaskDetail, openTask, traceTo } from './useReader'
import { showToast } from './useUi'
import { htmlToMd, mdToHtml } from '../writeRich'

/** 停了多久没有输入就自动存一次（毫秒）。手动「保存」与跳转前都会立刻存，不靠它。 */
const SAVE_DEBOUNCE_MS = 1200
/** "过程"页签最多留多少条（本会话的动作记录，不是历史）。 */
const LOG_MAX = 12

// ============================================================ 状态

export const drafts = ref([])
export const draftsLoading = ref(false)
export const draftsError = ref('')

// ⚠️ 素材卡的三份状态（`materials` / `materialsLoading` / `materialsError`）与
// `loadMaterials` 自 2026-10-16 起归 `useMaterials` 管（写入路径与读取同处一个 store，
// 免得"创建"与"列表"各拿一份状态）。这里 re-export，保持既有导入不变。
export { loadMaterials, materials, materialsError, materialsLoading } from './useMaterials'

export const currentDraftId = ref(null)
export const title = ref('')
export const body = ref('')
/**
 * 富文本源（2026-10-19）：编辑器是 TipTap，**逐段字号/行距只能存在 HTML 里**。
 * `body` 仍是 Markdown —— 由它转出来（引文 `[n]`、提纲、导出、AI 锚点校验都读 md）。
 */
export const bodyHtml = ref('')

/** `idle`（没改动）/ `dirty`（改了没存）/ `saving` / `saved` / `error`。 */
export const saveState = ref('idle')
export const saveError = ref('')
export const savedAt = ref('')

/** 本次会话做过的动作（保存正文 / 插引文 / 清空引文）——"过程"页签的内容。 */
export const sessionLog = ref([])

export const currentDraft = computed(
  () => drafts.value.find((item) => item.id === currentDraftId.value) || null,
)

/** 这篇稿的引文（按 `order` 排；服务端已按序返回，这里再兜一次底）。 */
export const citations = computed(() => {
  const list = currentDraft.value?.citations
  if (!Array.isArray(list)) return []
  return [...list].sort((a, b) => (a.order || 0) - (b.order || 0))
})

export const materialById = computed(() => {
  const map = {}
  for (const item of materials.value) map[item.id] = item
  return map
})

// ============================================================ 参考文献（契约 N31）
//
// ⭐ 为什么放在 store 里：样式选择、条目、跳过原因要跟着**当前草稿**走，
// 视图切页签不该丢；而且导出/复制要用同一份文本（两边不一致比没有更糟）。
// ⚠️ 后端支持 4 种样式；**样式列表以接口回的 `styles` 为准**（这里只是兜底默认）。

/** 兜底样式表（接口会回 `styles`，以它为准）。 */
export const BIB_STYLES = [
  { key: 'gb-t-7714-2015-numeric', label: 'GB/T 7714 顺序编码' },
  { key: 'gb-t-7714-2015-author-date', label: 'GB/T 7714 著者-出版年' },
  { key: 'apa', label: 'APA' },
  { key: 'ieee', label: 'IEEE' },
]

export const bibStyle = ref('gb-t-7714-2015-numeric')
/** 接口承认的样式（拿不到就用兜底表） */
export const bibStyleKeys = ref(BIB_STYLES.map((s) => s.key))
export const bibEntries = ref([])
/** 没生成的条目 + 原因（**如实展示**，不许悄悄少几条） */
export const bibSkipped = ref([])
export const bibError = ref('')
export const bibLoading = ref(false)

/** 下拉要显示的样式（按接口承认的 key 过滤兜底表，未知 key 也显示出来）。 */
export const bibStyleOptions = computed(() => {
  const known = BIB_STYLES.filter((s) => bibStyleKeys.value.includes(s.key))
  const extra = bibStyleKeys.value
    .filter((key) => !BIB_STYLES.some((s) => s.key === key))
    .map((key) => ({ key, label: key }))
  return [...known, ...extra]
})

/** 跳过项的说明（后端可能给字符串或对象，两种都收）。 */
function skippedText(item) {
  if (item === null || item === undefined) return ''
  if (typeof item === 'string') return item
  if (typeof item === 'object') {
    return String(item.reason || item.title || item.id || JSON.stringify(item))
  }
  return String(item)
}

/**
 * 拉一次参考文献（N31）。**没有引文就不请求**（省一次网络、也不显示空表）。
 *
 * ⚠️ 引擎环境没配好时接口回 503——那句话要**原样给用户看**，不要换成"出错了"。
 */
export async function loadBibliography() {
  const draft = currentDraft.value
  bibEntries.value = []
  bibSkipped.value = []
  bibError.value = ''
  if (!draft || !citations.value.length) return

  bibLoading.value = true
  try {
    const data = await apiJson(
      `/api/drafts/${draft.id}/bibliography?style=${encodeURIComponent(bibStyle.value)}`,
    )
    bibEntries.value = Array.isArray(data?.entries) ? data.entries : []
    bibSkipped.value = Array.isArray(data?.skipped) ? data.skipped.map(skippedText).filter(Boolean) : []
    if (Array.isArray(data?.styles) && data.styles.length) bibStyleKeys.value = data.styles
  } catch (err) {
    bibError.value = err.message || '参考文献没生成出来'
  } finally {
    bibLoading.value = false
  }
}

/** 复制用的一整段文本（与界面所见一致）。 */
export const bibText = computed(() => bibEntries.value.join('\n'))

/** 素材的来源清单（素材栏顶部的"来源筛选"用它，**客户端筛，不新造端点**）。 */
export const materialSources = computed(() => {
  const seen = []
  for (const item of materials.value) {
    const name = item.source_name
    if (name && !seen.includes(name)) seen.push(name)
  }
  return seen
})

// ============================================================ 脏标记与自动保存

let dirty = false
let saveTimer = null
let inFlight = null

/**
 * 出处能不能点：**只看一件事——素材有没有指向一篇还在的文献**。
 *
 * ⚠️ 返回的 `reason` 是给人看的一句话：说不清"为什么点不了"的灰按钮，
 * 用户只会以为界面坏了（形态硬约束②：死链不许做成活链样式）。
 */
export function sourceStateOf(material) {
  if (!material) return { alive: false, reason: '素材卡已删除——引文记录还在，但回不了原文' }
  if (!material.task_id) return { alive: false, reason: '源文献已删，仅存快照——回不了原文' }
  return { alive: true, reason: '' }
}

/** 一条引文的出处状态（引文只有 `material_id`，所以要查素材表）。 */
export function citationStateOf(citation) {
  return sourceStateOf(materialById.value[citation?.material_id])
}

function clockNow() {
  try {
    return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

/** 记一条"本次会话做过什么"（过程页签）。**只记真发生过的事**，不编。 */
export function logEvent(text) {
  if (!text) return
  sessionLog.value = [{ at: clockNow(), text }, ...sessionLog.value].slice(0, LOG_MAX)
}

function markDirty(delay = SAVE_DEBOUNCE_MS) {
  if (!currentDraftId.value) return
  dirty = true
  if (saveState.value !== 'saving') saveState.value = 'dirty'
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    saveTimer = null
    void saveNow()
  }, delay)
}

/**
 * 标题/正文一变就标脏（自动保存）。
 *
 * ⚠️ **判据是"跟服务端那份一不一样"，不是"有没有赋值"**：
 * `selectDraft` 是**程序化**回填（选草稿、刷新列表），那时标题/正文恰好等于草稿里存的，
 * 所以不会被判成"用户改了字"。用一个 `applying` 布尔标记反而会漏——
 * Vue 的 watcher 是异步派发的，赋值当下把它设成 false，回调跑的时候已经太晚了。
 */
watch([title, body, bodyHtml], ([nextTitle, nextBody]) => {
  const draft = currentDraft.value
  if (!draft) return
  if (nextTitle === (draft.title || '') && nextBody === (draft.body_md || '')) return
  markDirty()
})

// ============================================================ 草稿：拉 / 建 / 选 / 存

/** 把服务端返回的元信息合并回列表项（**不覆盖 `citations`**：那是 insertCitation 的地盘）。 */
function mergeDraftMeta(saved) {
  drafts.value = drafts.value.map((item) =>
    item.id === saved.id
      ? {
          ...item,
          title: saved.title,
          body_md: saved.body_md,
          body_html: saved.body_html,
          template_id: saved.template_id,
          updated_at: saved.updated_at,
        }
      : item,
  )
}

/** 选一篇草稿到编辑器（服务端是权威：标题与正文照它回填）。 */
export function selectDraft(id) {
  const draft = drafts.value.find((item) => item.id === id)
  if (!draft) return false
  currentDraftId.value = draft.id
  title.value = draft.title || ''
  body.value = draft.body_md || ''
  // 富文本优先：老稿没有 html 就从 md 转一份（保证编辑器能显示已有内容）
  bodyHtml.value = draft.body_html || mdToHtml(draft.body_md || '')
  if (saveTimer) {
    clearTimeout(saveTimer)
    saveTimer = null
  }
  dirty = false
  saveState.value = 'idle'
  saveError.value = ''
  savedAt.value = ''
  return true
}

/** `GET /api/drafts`（N18）。失败就把原因摆出来，**不静默变成"你没有草稿"**。 */
export async function loadDrafts() {
  draftsLoading.value = true
  draftsError.value = ''
  try {
    const data = await apiJson('/api/drafts')
    const items = Array.isArray(data?.items) ? data.items : []
    drafts.value = items
    if (currentDraftId.value) {
      // 服务端那份是权威；**但正在编辑（脏）时不回填**，否则会把没存上的字吞掉
      if (items.some((item) => item.id === currentDraftId.value)) {
        if (!dirty) selectDraft(currentDraftId.value)
      } else {
        // 这篇在服务端没了（换了账号 / 别处删了）——如实清掉选中，别继续编辑一份不存在的稿
        currentDraftId.value = null
        title.value = ''
        body.value = ''
        saveState.value = 'idle'
      }
    }
    return items
  } catch (err) {
    draftsError.value = err?.message || '草稿列表加载失败'
    return []
  } finally {
    draftsLoading.value = false
  }
}

/** `GET /api/materials`（N13）已移到 `useMaterials`（素材的读与写同处一个 store）。 */

/**
 * 起一份新稿（N18 `POST /api/drafts`）。
 *
 * ⭐ **起稿四入口（模板 / 大纲 / 空白 / 上传自己的模板）落到接口只差 `template_id`**：
 * `templateId` 为空 = 空白；有值就照原样存进草稿（本期只存标识、不做版式渲染）。
 * `seed` 是"起点正文"——**只有"上传自己的模板"会给**（内容来自用户的文件，不经模型）。
 */
export async function newDraft({ title: draftTitle, templateId = null, seed = '' } = {}) {
  const payload = { title: String(draftTitle ?? '').trim() || '未命名草稿' }
  if (templateId) payload.template_id = templateId
  const created = await apiJson('/api/drafts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  let draft = created
  if (seed) {
    draft = await apiJson(`/api/drafts/${created.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body_md: seed }),
    })
  }
  drafts.value = [draft, ...drafts.value.filter((item) => item.id !== draft.id)]
  selectDraft(draft.id)
  logEvent(`新建草稿「${draft.title}」`)
  return draft
}

/**
 * 存当前稿（N19 `PATCH /api/drafts/{id}`）。
 *
 * ⚠️ **跳回原文之前一定要先 await 它**：跳转会把写作页卸载，
 * 没存上的字只活在内存里（本会话内还在，刷新就没了）。
 */
export async function saveNow() {
  if (saveTimer) {
    clearTimeout(saveTimer)
    saveTimer = null
  }
  if (inFlight) await inFlight.catch(() => {})
  if (!dirty || !currentDraftId.value) return true

  const id = currentDraftId.value
  const shotTitle = title.value.trim() || '未命名草稿'
  const shotBody = body.value
  const shotHtml = bodyHtml.value
  saveState.value = 'saving'
  saveError.value = ''
  inFlight = (async () => {
    try {
      const saved = await apiJson(`/api/drafts/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: shotTitle, body_md: shotBody, body_html: shotHtml }),
      })
      mergeDraftMeta(saved)
      if (title.value.trim() === shotTitle && body.value === shotBody) {
        dirty = false
        saveState.value = 'saved'
        savedAt.value = clockNow()
        logEvent(`保存正文（${shotBody.length} 字）`)
      } else {
        saveState.value = 'dirty' // 存的过程中又改了，保持"没存完"的诚实状态
      }
      return true
    } catch (err) {
      dirty = true
      saveState.value = 'error'
      saveError.value = err?.message || '保存失败'
      return false
    } finally {
      inFlight = null
      if (saveState.value === 'dirty') markDirty(400)
    }
  })()
  return inFlight
}

/** 保存按钮/快捷键走这里：失败时说一句人话（自动保存失败则只在状态行显示）。 */
export async function saveWithFeedback() {
  const ok = await saveNow()
  if (ok && saveState.value === 'saved') showToast('已保存')
  else if (!ok) showToast(`没存上：${saveError.value || '原因不明'}——可以再点一次「保存」`)
  return ok
}

// ============================================================ 引文

/**
 * 插一条引文（N20 `POST /api/drafts/{id}/citations`），并在正文里落下 `[n]`。
 *
 * `order`（文内编号）**由服务端算**（当前最大 +1）——前端自己数，在并发/删除之后必然错位，
 * 而 M4 的格式检查第一条查的就是编号连续性。所以这里只用服务端回来的那个号。
 *
 * @returns {Promise<{citation: object, caret: number}|null>}
 */
export async function insertCitation(material, offset) {
  if (!currentDraftId.value) {
    showToast('先起一份稿：点右上角「＋ 新建」，引文才有地方落')
    return null
  }
  if (!material?.id) return null
  const draftId = currentDraftId.value
  const raw = Number(offset)
  const anchorOffset = Number.isFinite(raw) ? Math.max(0, Math.trunc(raw)) : body.value.length

  const citation = await apiJson(`/api/drafts/${draftId}/citations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      material_id: material.id,
      anchor: { block_id: material.block_id ?? null, offset: anchorOffset },
    }),
  })

  const { text, caret } = insertMarker(body.value, anchorOffset, citation.order)
  body.value = text // → watch → markDirty（正文变了就要落库）
  // 编辑器看的是 html：md 变了要跟着转一份，否则界面不会出现刚插进去的 [n]
  bodyHtml.value = mdToHtml(text)
  drafts.value = drafts.value.map((item) =>
    item.id === draftId ? { ...item, citations: [...(item.citations || []), citation] } : item,
  )
  logEvent(`插入引文 [${citation.order}] · ${material.source_name || '素材'} · 第 ${material.page} 页`)
  return { citation, caret }
}

/** 清空这篇稿的引文（N21 只给了"整篇清空"这一条路径，所以只能整篇清）。 */
export async function clearCitations() {
  if (!currentDraftId.value) return false
  const draftId = currentDraftId.value
  await apiJson(`/api/drafts/${draftId}/citations`, { method: 'DELETE' })
  drafts.value = drafts.value.map((item) =>
    item.id === draftId ? { ...item, citations: [] } : item,
  )
  logEvent('清空引文（正文里的 [n] 标记没有自动删）')
  return true
}

// ============================================================ ⭐ 点 [1] 回原文

/**
 * ⭐ 点 `[1]` → 跳回原文献并高亮那一句（**素材卡直跳也走这里**）。
 *
 * 链路（契约 §2.7 写死的那条）：素材的 `task_id` / `block_id` → 打开那篇文献
 * → **复用阅读区的 `traceTo`** 滚过去 + 高亮（D7 判据：别另写一套定位）。
 *
 * 四件"如实说"的事（都不许糊过去）：
 * ① 素材卡查不到 → 说清"引文记录还在、回不了原文"；
 * ② 素材 `task_id` 为 null → "源文献已删，仅存快照"；
 * ③ 素材没记下 `block_id` → 只打开文献、**不假装定位到了句子**；
 * ④ 块在文献里找不到 → 由 `traceTo` 自己如实说（这里不另编一句）。
 */
export async function jumpToMaterial(material) {
  const state = sourceStateOf(material)
  if (!state.alive) {
    showToast(`${state.reason}（没有做成能点的假链接）`)
    return false
  }

  // 跳走之前先把稿存了：写作页会被卸载，不存就等于丢字
  await saveNow().catch(() => {})

  let task = findTask(material.task_id)
  if (!task) {
    // 列表里没有（已归档 / 不在这一页的返回里）：**真去取一次**，取不到才算"已删除"
    const detail = await fetchTaskDetail(material.task_id)
    if (!detail) {
      showToast('这篇源文献取不到（可能已被删除）——只保留了快照出处')
      return false
    }
    task = detail
  }

  await openTask(task)
  if (!material.block_id) {
    showToast(
      `${material.source_name} · 第 ${material.page} 页——这条素材没记下段落坐标，只打开了文献，没定位到句子`,
    )
    return false
  }

  // 打开之后要等阅读区把段落渲染出来，`traceTo` 才找得到那一块。
  // 前几次静默重试（避免"还没渲染好"被当成"对不上"），最后一次不静默，让它如实说。
  let ok = false
  for (let i = 0; i < 3 && !ok; i += 1) {
    ok = await traceTo(material.block_id, { silent: i < 2, text: material.text_quote })
    if (!ok) await new Promise((resolve) => setTimeout(resolve, 0))
  }
  if (ok) {
    showToast(`已回到原文并高亮——${material.source_name} · 第 ${material.page} 页`)
  }
  return ok
}

/**
 * 点一条引文（`[n]`）→ 按 `material_id` 找到素材，再走上面那条链路。
 *
 * ⚠️ 引文只存 `material_id`（快照在素材卡上）——所以素材卡没了就真的回不去，
 * 这时候**如实说**，而不是拿 `csl_json` 里的书名当坐标硬跳。
 */
export async function jumpToSource(citation) {
  const material = materialById.value[citation?.material_id]
  if (!material) {
    showToast('这条引文的素材卡取不到了（可能已删除）——引文记录还在，但回不了原文')
    return false
  }
  return jumpToMaterial(material)
}

/** 预览里点 `[n]`：先按编号找引文，找不到就**如实说这条编号没有对应引文**（别装没点到）。 */
export async function jumpByOrder(order) {
  const hit = citations.value.find((item) => item.order === Number(order))
  if (!hit) {
    showToast(`正文里的 [${order}] 没有对应的引文记录——可能是手写的编号，或引文被清空过`)
    return false
  }
  return jumpToSource(hit)
}

// ============================================================ 校对检查（M4）

/**
 * 校对检查（形态 §3.3 / 契约 §2.7 的 N22–N23）。
 *
 * ⚠️ **它是"看"，不是"改"**：这里只把报告取回来摆出来，
 * **一个"一键修好/自动改写"都没有**（形态 §3.3 ②：并列摆出两处，不自动改）。
 * ⚠️ **判不出就说判不出**：`unknown` 是一等公民，界面上**单独一栏**，
 * 绝不混进"该报的"里充数。
 * ⚠️ **不报百分比**（卡④⑧）：只给「报出 N 处、另有 M 处判不出」。
 */
export const checkOpen = ref(false)
export const checkReport = ref(null)
export const checkRunning = ref(false)
export const checkError = ref('')

/** 分组的顺序**写死**（与后端 `rules.py` 的 `KIND_ORDER` 一致）：不靠对象键序去猜。 */
const CHECK_KINDS = [
  { kind: 'missing_citation', label: '该引未引' },
  { kind: 'term_inconsistent', label: '术语一致性' },
  { kind: 'format', label: '格式自检' },
  { kind: 'unknown', label: '无法判断' },
]

/** 报告按 `kind` 分组（空组不出现）；每组带自己的计数，**不出百分比**。 */
export const checkGroups = computed(() => {
  const findings = checkReport.value?.findings || []
  return CHECK_KINDS.map(({ kind, label }) => {
    const items = findings.filter((item) => item.kind === kind)
    return {
      kind,
      label,
      items,
      reported: items.filter((item) => item.severity === 'report').length,
      unknown: items.filter((item) => item.severity === 'unknown').length,
    }
  }).filter((group) => group.items.length)
})

export const checkSummary = computed(
  () => checkReport.value?.summary || { reported: 0, unknown: 0 },
)

/** 引擎判出来的语言与引用制式（说人话；**判不出就写"未能识别"**）。 */
export const checkStep = computed(() => {
  const step = checkReport.value?.step
  if (!step) return null
  return {
    lang: step.lang === 'zh' ? '中文' : step.lang === 'en' ? '英文' : '未能识别',
    style:
      step.citation_style === 'numeric'
        ? '顺序编码制（[n]）'
        : step.citation_style === 'author-year'
          ? '著者-出版年制（作者，年份）'
          : '未能识别',
    unknownLang: step.lang === 'unknown',
    unknownStyle: step.citation_style === 'unknown',
    // ⭐ 筛子账：每族"为什么只报这么少"都要能看见（语言/制式上面两个 chip 已经有了）
    // 「术语一致性」那本是 R6 启用后加的：少了它，"术语没报"就又成了黑箱
    ledger: (Array.isArray(step.notes) ? step.notes : []).filter(
      (note) =>
        note.startsWith('该引未引：') ||
        note.startsWith('术语一致性：') ||
        note.includes('不是失灵'),
    ),
  }
})

export function toggleCheck() {
  checkOpen.value = !checkOpen.value
}

export function openCheck() {
  checkOpen.value = true
}

export function closeCheck() {
  checkOpen.value = false
}

/** 跑一次检查（契约 N22）。**报告只读**：不写回草稿、不动引文。 */
export async function runCheck() {
  const draft = currentDraft.value
  if (!draft) {
    checkError.value = '先建一份草稿，再跑检查'
    return false
  }
  checkRunning.value = true
  checkError.value = ''
  try {
    const report = await apiJson('/api/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ draft_id: draft.id, doc_text: body.value || '' }),
    })
    checkReport.value = report
    const { reported, unknown } = checkSummary.value
    logEvent(`校对检查：报出 ${reported} 处，另有 ${unknown} 处判不出`)
    return true
  } catch (err) {
    checkReport.value = null
    checkError.value = err.message || '检查没跑成'
    return false
  } finally {
    checkRunning.value = false
  }
}

/**
 * 点「回素材那一句」：按 `suggest.material_id` 找素材。
 * **找不到就如实说**（换了草稿 / 素材被删），**绝不装作能跳**。
 */
export function jumpToSuggested(finding) {
  const id = finding?.suggest?.material_id
  if (id === null || id === undefined) return
  const material = materials.value.find((item) => item.id === id)
  if (!material) {
    showToast('这条候选素材不在当前素材列表里（可能换了草稿，或素材被删了）')
    return
  }
  jumpToMaterial(material)
}

// ============================================================ 检查历史（契约 N43 / N23）
//
// ⭐ 以前抽屉里只有"当场这一次"：关掉就没了，想对比两次检查办不到。
// 现在列表走 N43（只带摘要），点一条再走 N23 取完整报告
// —— 契约保证它与 POST 当场返回的**逐字节一致**。

export const checkHistory = ref([])
export const checkHistoryError = ref('')
export const checkHistoryLoading = ref(false)

/** 拉一次历史（当前草稿的；没草稿就整块空）。 */
export async function loadCheckHistory() {
  const draft = currentDraft.value
  if (!draft) {
    checkHistory.value = []
    return
  }
  checkHistoryLoading.value = true
  checkHistoryError.value = ''
  try {
    const data = await apiJson(`/api/check?draft_id=${draft.id}&limit=10`)
    checkHistory.value = Array.isArray(data?.items) ? data.items : []
  } catch (err) {
    checkHistoryError.value = err.message || '历史报告没取到'
    checkHistory.value = []
  } finally {
    checkHistoryLoading.value = false
  }
}

/** 点一条历史 → 用 N23 取回那份报告，替换抽屉里的当前报告。 */
export async function openCheckRun(runId) {
  checkRunning.value = true
  checkError.value = ''
  try {
    const report = await apiJson(`/api/check/${runId}`)
    checkReport.value = report
    logEvent(`回看检查报告 #${runId}`)
    return true
  } catch (err) {
    checkError.value = err.message || '这份报告没取到'
    return false
  } finally {
    checkRunning.value = false
  }
}

// ============================================================ 收尾

/** 退出登录 / 换账号时清空（否则下一个人会看到上一个人的草稿）。 */
export function resetWrite() {
  drafts.value = []
  draftsError.value = ''
  // 素材连"待删的撤销窗口定时器"一起清（只清列表会漏下一个定时器）
  resetMaterials()
  currentDraftId.value = null
  title.value = ''
  body.value = ''
  saveState.value = 'idle'
  saveError.value = ''
  savedAt.value = ''
  sessionLog.value = []
  checkOpen.value = false
  checkReport.value = null
  checkError.value = ''
  dirty = false
  if (saveTimer) {
    clearTimeout(saveTimer)
    saveTimer = null
  }
  inFlight = null
}

/** 组件卸载时收尾（定时器不清，会在组件没了之后还去改一份不显示的状态）。 */
export function disposeWrite() {
  if (saveTimer) {
    clearTimeout(saveTimer)
    saveTimer = null
  }
}
