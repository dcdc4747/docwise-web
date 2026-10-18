/**
 * 知识库的"名词"数据：集合 / 标签 / 智能集合（契约 N1 / N6 / N9）。
 *
 * ## 为什么单独一个 store
 *
 * 这三样**只用来"给人挑"**（筛选条上的芯片、集合页的列表、标签页的列表），
 * 和"文献列表"（`useTasks`）不是一件事：列表会被筛，而**可选项不跟着筛**——
 * 筛到 0 条时你还得能看见"我有哪些集合可以换一个"。
 *
 * ## 三条口径
 *
 * 1. ⭐ **三个请求各自容错**：一个挂了只影响一行（`errors` 里如实说），
 *    不许因为标签接口出错就让整个筛选条消失；
 * 2. ⭐ **字段名照接口**：集合 `doc_count`（直接成员）/ 标签 `doc_count` / 智能集合 `count`，
 *    统一映射成组件要的 `count`（映射只在这一处，别在模板里再算）；
 * 3. ⭐ **没数据就是空数组**，不编默认集合（"给你三个示例集合"会变成假数据）。
 */

import { ref } from 'vue'

import { apiJson } from '../auth'

/** 集合：`[{id, name, parentId, count}]` */
export const collections = ref([])
/** 标签：`[{id, name, kind, count}]` */
export const tags = ref([])
/** 智能集合：`[{id, name, query, count, builtin}]` */
export const smartCollections = ref([])
/** 概览条数（N42）：`{tasks, archived_tasks, blocks, materials, drafts, citations, check_runs}` */
export const overview = ref(null)
/** 各块自己的错（空串 = 正常） */
export const errors = ref({ collections: '', tags: '', smart: '', overview: '' })
export const loading = ref(false)
export const loaded = ref(false)

function toCount(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

/** 集合一行 → 组件要的形状（`parentId` 用来画树；`deepCount` 是含子集合的总数）。 */
export function mapCollection(row) {
  return {
    id: row?.id,
    name: String(row?.name ?? '').trim(),
    parentId: row?.parent_id ?? null,
    count: toCount(row?.doc_count),
    // 排序号：后端按 `sort, id` 排；界面靠它做"上移 / 下移"
    sort: Number(row?.sort ?? 0),
    // ⚠️ 两个计数别混：`count` 只数**直接成员**，`deepCount` 才是含子集合（后端两个都给了）
    deepCount: toCount(row?.doc_count_deep),
  }
}

export function mapTag(row) {
  return {
    id: row?.id,
    name: String(row?.name ?? '').trim(),
    kind: row?.kind || '',
    count: toCount(row?.doc_count),
  }
}

export function mapSmart(row) {
  return {
    id: row?.id,
    name: String(row?.name ?? '').trim(),
    query: row?.query || {},
    count: toCount(row?.count),
    builtin: Boolean(row?.builtin),
  }
}

function messageOf(error, fallback) {
  return error && error.message ? String(error.message) : fallback
}

/**
 * 拉一次三样。
 *
 * ⚠️ **各自 allSettled**：用 `Promise.all` 的话，标签接口一挂集合也跟着没——
 * 而集合恰恰是更常用的那个。
 */
export async function loadKnowledge() {
  loading.value = true
  const [c, t, s, o] = await Promise.allSettled([
    apiJson('/api/collections'),
    apiJson('/api/tags'),
    apiJson('/api/smart-collections'),
    apiJson('/api/me/overview'),
  ])

  const pick = (result, map, key, label) => {
    if (result.status === 'fulfilled') {
      const items = Array.isArray(result.value?.items) ? result.value.items : []
      errors.value[key] = ''
      return items.map(map)
    }
    errors.value[key] = `${label}列表暂时取不到（${messageOf(result.reason, '网络或服务异常')}）`
    return []
  }

  collections.value = pick(c, mapCollection, 'collections', '集合')
  tags.value = pick(t, mapTag, 'tags', '标签')
  smartCollections.value = pick(s, mapSmart, 'smart', '智能集合')

  // 概览（N42）：整块拿到才用；拿不到就保持 null → 底行走诚实档（不摆一排 0）
  if (o.status === 'fulfilled' && o.value && typeof o.value === 'object') {
    overview.value = {
      tasks: toCount(o.value.tasks) ?? 0,
      archivedTasks: toCount(o.value.archived_tasks) ?? 0,
      blocks: toCount(o.value.blocks) ?? 0,
      materials: toCount(o.value.materials) ?? 0,
      drafts: toCount(o.value.drafts) ?? 0,
      citations: toCount(o.value.citations) ?? 0,
      checkRuns: toCount(o.value.check_runs) ?? 0,
    }
    errors.value.overview = ''
  } else {
    overview.value = null
    errors.value.overview = `概况暂时取不到（${messageOf(
      o.status === 'rejected' ? o.reason : null,
      '网络或服务异常',
    )}）`
  }

  loading.value = false
  loaded.value = true
}

/** 退出登录 / 换账号时清掉（否则下一个人看到上一个人的集合名）。 */
export function resetKnowledge() {
  collections.value = []
  tags.value = []
  smartCollections.value = []
  overview.value = null
  errors.value = { collections: '', tags: '', smart: '', overview: '' }
  loaded.value = false
}

/** 按 id 找集合名（"当前筛选：集合 X" 这类人话要用）。 */
export function collectionNameOf(id) {
  if (id === '' || id === null || id === undefined) return ''
  const hit = collections.value.find((item) => String(item.id) === String(id))
  return hit ? hit.name : String(id)
}
