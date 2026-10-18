<template>
  <!-- 「历史记录」= 全部文献 + 筛选 + 管理（2026-10-17 知识库重构后的定位）。
       ⚠️ **开工的事（上传 / 示例 / 继续读）搬去了「读懂」工作台**：
       以前这一页既是入口又是清单，于是"点读懂看到的是清单"——那正是用户报的问题。
       这一页只做一件事：**我读过什么、怎么找回来**。 -->
  <div class="lib-wrap">
    <div class="title-row">
      <h2>{{ countsText }}</h2>
      <span class="spacer" />
      <button class="btn primary" @click="showUpload = !showUpload">
        {{ showUpload ? '收起上传' : '＋ 上传 PDF' }}
      </button>
    </div>

    <!-- ==================== 筛选区（卡③ + 契约 N8） ====================
         ⭐ 2026-10-17：**集合 / 标签 / 智能集合三条列表接上了**（N1 / N6 / N9）。
         在此之前这里传的是三个空数组（那三条接口早就活着，只是没人接），
         于是筛选条上永远只有「状态」一行——看着像"没做"，其实是"没接"。 -->
    <LibFilters
      :filters="filters"
      :total="libraryTotal"
      :shown="tasks.length"
      :collections="collections"
      :tags="tags"
      :smart-collections="smartCollections"
      @change="applyFilters"
      @clear="clearFilters"
    />

    <!-- 归集/未归类这类**筛选条没画出来的条件**，在这里如实说一句（否则"筛空了"没头没尾） -->
    <p v-if="extraFilterText" class="lib-extra-filter">
      {{ extraFilterText }}
      <button type="button" class="btn ghost sm" @click="clearFilters">清除筛选</button>
    </p>

    <!-- 上传卡：**空库时直接摆出来**（库里一篇都没有，这一页唯一有用的事就是上传）；
         有历史时由标题行的「＋ 上传 PDF」按需展开（那一页的主角是清单）。 -->
    <div v-if="libraryEmpty || showUpload" class="card upload-card">
      <div class="drop" :class="{ 'drop-over': uploading || dropHinting }" @click="pickFile()" @dragover.prevent @drop.prevent="onDrop">
        <div class="big">点击或拖拽 PDF 到此处</div>
        <div class="tiny">
          {{
            selectedLang === 'zh'
              ? '上传后自动抽取文字并生成导读；完成后可读原文、导读与术语表'
              : '上传后自动开始翻译；完成后可读双语稿、导读与术语表'
          }}
        </div>
        <div class="drop-hint">支持电子版 PDF 与扫描件（扫描件走本地 OCR，文字可能有错别字）；耗时取决于页数与档位</div>
        <div v-if="uploading" class="drop-hint">正在上传…</div>
        <div v-if="uploadError" class="drop-hint" style="color: var(--danger)">{{ uploadError }}</div>
      </div>

      <div>
        <div class="tier-label">文献语言</div>
        <div class="seg">
          <span
            v-for="lang in langOptions"
            :key="lang.value"
            :class="{ on: selectedLang === lang.value }"
            @click="selectedLang = lang.value"
          >
            {{ lang.label }}
          </span>
        </div>

        <template v-if="selectedLang !== 'zh'">
          <div class="tier-label" style="margin-top: 16px">翻译档位</div>
          <div class="seg">
            <span
              v-for="tier in tierOptions"
              :key="tier.value"
              :class="{ on: selectedTier === tier.value }"
              @click="selectedTier = tier.value"
            >
              {{ tier.label }}
            </span>
          </div>
          <div class="tier-note">
            档位影响速度与质量，请在上传前选择<br />
            快：最快，先看个大概<br />
            中：版式更稳，适合正式阅读<br />
            精档（多一道审校的那一档）还没做，做出来再放出来<br />
            耗时取决于页数与档位（不承诺秒数）
          </div>
        </template>
        <div v-else class="tier-note">
          中文文献不翻译：直接抽文字层进理解层（导读 / 术语 / 带出处的问答）。<br />
          耗时取决于页数（不承诺秒数）
        </div>
      </div>
    </div>

    <!-- 进行中任务条：只留 3 段信息 + 队列数 -->
    <div v-for="bar in activeBars" :key="bar.task.id" class="card running">
      <!-- 文件名本身是进阅读工作区的入口（原型这里只有取消 / 详情，但"看翻译中的进度"
           总得有个门；做成文件名可点，不新增控件、不动信息密度） -->
      <span class="name name-link" title="打开阅读工作区" @click="openTask(bar.task)">
        {{ bar.task.filename }}
      </span>
      <div class="bar" :class="{ striped: bar.striped }"><i :style="{ width: bar.percent + '%' }" /></div>
      <span class="tiny muted">{{ bar.line }}</span>
      <span v-if="bar.queue" class="queue">{{ bar.queue }}</span>
      <button class="btn sm" :disabled="taskActionBusy" @click="cancelTask(bar.task)">取消</button>
      <button class="btn ghost sm" @click="openPanel('blocks', bar.task)">详情</button>
    </div>

    <!-- 翻译完成后任务条不静默消失：变绿给下一步动作，可手动关掉 -->
    <div v-if="completedBannerTask" class="card taskbar-ok">
      <span class="ok-text">翻译完成</span>
      <span class="tiny muted">{{ bannerMeta }}</span>
      <span class="spacer" />
      <button class="btn primary sm" @click="openTask(completedBannerTask)">开始阅读</button>
      <button class="btn ghost sm" @click="dismissBanner(completedBannerTask)">关闭</button>
    </div>

    <div v-if="historyError" class="card" style="margin-bottom: 14px; color: var(--danger)">
      历史任务加载失败：{{ historyError }}
      <button class="btn sm" style="margin-left: 10px" @click="loadTasksAndSync">重试</button>
    </div>

    <!-- 真空态：一份文献都没有。**说清"下面就能传" + 给去"读懂"的出口** -->
    <div v-else-if="libraryEmpty" class="card muted">
      还没有文献 —— 下面拖一份 PDF 进来就行；想看示例导读，去「读懂」页。
      <button class="btn ghost sm lib-go-read" @click="goReadHome">去读懂 →</button>
    </div>

    <div v-else-if="!taskCards.length" class="card muted">
      这个筛选下没有可读的文献——上面点「清除筛选」回到全部。
    </div>

    <div v-else class="grid3">
      <div v-for="card in taskCards" :key="card.task.id" class="card paper-card">
        <div class="row">
          <span class="fname">{{ card.task.filename }}</span>
          <span class="chip" :class="card.chip">{{ statusTextMap[card.task.status] || card.task.status }}</span>
          <span v-if="card.task.native" class="chip">中文文献</span>
        </div>
        <div class="meta">{{ card.meta }}</div>
        <div v-if="card.task.last_read_page" class="lastpos">
          上次读到第 {{ card.task.last_read_page }} 页
        </div>

        <!-- ⭐ 归集（N5）：**只有"不在集合里 / 只在一个集合里"的才给下拉**。
             在多个集合里的直接禁用并说明——N5 是**全量替换**，给下拉就等于
             "改一个、悄悄抹掉另一个"，宁可少给一个操作。 -->
        <label v-if="collections.length" class="lib-assign">
          <span>归到</span>
          <select
            class="lib-assign-select"
            :value="primaryCollectionId(card.task)"
            :disabled="taskActionBusy || (card.task.collection_ids || []).length > 1"
            :title="
              (card.task.collection_ids || []).length > 1
                ? '这篇同时在多个集合里，改归属请去「集合」页'
                : '把这篇归到一个集合（也可以放回未归类）'
            "
            @change="assignCollection(card.task, $event.target.value)"
          >
            <option value="">未归类</option>
            <option v-for="item in collections" :key="item.id" :value="String(item.id)">
              {{ item.name }}
            </option>
          </select>
        </label>

        <!-- ⭐ 标签（N7）：在卡片上直接贴，不跳页。N7 是全量替换，
             所以每次发的是"当前这组 + 新加的一个"。 -->
        <div class="lib-tags">
          <button
            v-for="name in card.task.tags || []"
            :key="name"
            type="button"
            class="lib-tag-chip"
            :title="`点掉标签「${name}」`"
            :disabled="taskActionBusy"
            @click="removeTag(card.task, name)"
          >
            {{ name }}<span class="lib-tag-x">×</span>
          </button>

          <template v-if="tagEditingId === card.task.id">
            <input
              ref="tagInputEl"
              v-model="tagDraft"
              class="lib-tag-input"
              type="text"
              maxlength="24"
              list="lib-tag-suggest"
              placeholder="标签名，回车加上"
              @keydown.enter.prevent="commitTag(card.task)"
              @keydown.esc.prevent="cancelTag"
              @blur="commitTag(card.task)"
            />
          </template>
          <button
            v-else
            type="button"
            class="lib-tag-add"
            :disabled="taskActionBusy"
            @click="startTag(card.task)"
          >
            ＋ 标签
          </button>
        </div>

        <div class="actions">
          <button
            v-if="card.retryable"
            class="btn primary sm"
            :disabled="taskActionBusy"
            @click="retryTask(card.task)"
          >
            {{ card.primary }}
          </button>
          <button v-else class="btn primary sm" @click="openTask(card.task)">
            {{ card.primary }}
          </button>
          <button class="btn ghost sm" @click="openPanel('blocks', card.task)">详情</button>
          <template v-if="deleteConfirmId === card.task.id">
            <button class="btn danger sm" :disabled="taskActionBusy" @click="deleteTask(card.task)">
              确认删除
            </button>
            <button class="btn ghost sm" @click="deleteConfirmId = null">再想想</button>
          </template>
          <button v-else class="btn ghost sm" @click="deleteConfirmId = card.task.id">删除</button>
        </div>
      </div>
    </div>

    <!-- 概况底行（卡③）：四段数**现在真的有数了**（N42 `GET /api/me/overview`）。
         ⚠️ 拿不到整块就仍走诚实档（不摆一排 0 冒充"统计好了"）。 -->
    <LibOverview :stats="overviewStats" :tags="tags" @pick-tag="pickTag" />

    <!-- 已有标签做输入建议：贴过的名字不该让人再手打一遍（打错就是新标签） -->
    <datalist id="lib-tag-suggest">
      <option v-for="item in tags" :key="item.id" :value="item.name" />
    </datalist>

    <div class="footline">
      <span v-if="taskActionError" style="color: var(--danger)">{{ taskActionError }}</span>
      <span v-if="tagError" style="color: var(--danger)">{{ tagError }}</span>
      <span class="spacer" />
      <span>docwise · 学术文献理解智能体</span>
    </div>
  </div>
</template>

<script setup>
/**
 * 「历史记录」整页（原「L1 我的论文」库页）：全部文献 + 筛选 + 归集 + 删除。
 *
 * ⭐ 2026-10-17 知识库重构：
 * - **开工入口搬去「读懂」工作台**（上传 / 示例 / 继续读），这一页只做"回顾与管理"；
 * - **筛选条接上真选项**（集合 N1 / 标签 N6 / 智能集合 N9）——此前传的是空数组；
 * - **卡片上加「归集」**（N5）。⚠️ N5 是**全量替换**，所以只在"0 或 1 个集合"时给下拉：
 *   在多个集合里的禁用，宁少一个操作也不悄悄抹掉归属。
 *
 * ⚠️ 筛选状态的主人是这一页：`LibFilters` 走"`filters` 进、`change`/`clear` 出"，
 * 这里把条件交给 `loadTasksAndSync()`（**服务端筛**，契约 N8）。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import {
  activeBars,
  activeTaskQuery,
  bannerMeta,
  cancelTask,
  completedBannerTask,
  deleteConfirmId,
  deleteTask,
  dismissBanner,
  dropHinting,
  langOptions,
  libraryEmpty,
  libraryTotal,
  loadTasksAndSync,
  onDrop,
  openPanel,
  pickFile,
  retryTask,
  selectedLang,
  selectedTier,
  showUpload,
  taskActionBusy,
  taskActionError,
  taskCards,
  tierOptions,
  uploading,
  uploadError,
} from '../stores/useLibrary'
import LibFilters from '../components/LibFilters.vue'
import LibOverview from '../components/LibOverview.vue'
import { navigate } from '../router'
import { openTask } from '../stores/useReader'
import { historyError, statusTextMap, tasks } from '../stores/useTasks'
import { collectionNameOf, collections, loadKnowledge, overview, smartCollections, tags } from '../stores/useKnowledge'
import { apiJson } from '../auth'

const filters = ref({ ...(activeTaskQuery.value || {}) })

watch(activeTaskQuery, (query) => {
  filters.value = { ...(query || {}) }
})

onMounted(() => {
  // 筛选条的可选项（集合 / 标签 / 智能集合）：一个挂了只影响一行，各自容错
  loadKnowledge()
})

/** 标题：没筛 = 共 N 篇；筛了 = 本筛选 N 篇（与"共"分开，避免两个数字打架）。 */
const countsText = computed(() => {
  const n = tasks.value.length
  const hasFilters = Object.keys(activeTaskQuery.value || {}).length > 0
  if (!n && !hasFilters) return '我的文献'
  return hasFilters ? `本筛选 ${n} 篇` : `我的文献 · ${n} 篇`
})

/** 筛选条没画出来的条件（`unfiled`），在这里补一句人话。 */
const extraFilterText = computed(() => {
  if (activeTaskQuery.value?.unfiled) return '当前只看「未归类」——还没放进任何集合的文献。'
  return ''
})

/** 概况四段数（N42）：`LibOverview` 要的就是这四个键；整块没拿到就传 null（走诚实档）。 */
const overviewStats = computed(() => {
  const data = overview.value
  if (!data) return null
  return {
    tasks: data.tasks,
    blocks: data.blocks,
    materials: data.materials,
    citations: data.citations,
  }
})

/** 点标签云 = 按这个标签筛（与筛选条上的标签芯片同一条路）。 */
function pickTag(name) {
  applyFilters({ tag: [name] })
}

// ---------------------------------------------------------------- 标签（N7）
//
// ⚠️ N7 是**全量替换**：`PUT /api/tasks/{id}/tags` 传什么就只剩什么。
// 所以"加一个"= 当前这组 + 新的那一个；"删一个"= 当前这组减掉它。
// 前端绝不能只发新加的那个——那会把别的标签全抹了。

const tagEditingId = ref(null)
const tagDraft = ref('')
const tagInputEl = ref(null)
const tagError = ref('')

/** 已有标签的 kind（新标签沿用同名标签的 kind，没有就 topic）。 */
function tagKindOf(name) {
  const hit = tags.value.find((item) => item.name === name)
  return hit?.kind || 'topic'
}

function startTag(task) {
  tagEditingId.value = task.id
  tagDraft.value = ''
  tagError.value = ''
  nextTick(() => {
    const el = Array.isArray(tagInputEl.value) ? tagInputEl.value[0] : tagInputEl.value
    el?.focus?.()
  })
}

function cancelTag() {
  tagEditingId.value = null
  tagDraft.value = ''
}

/** 发一整组标签（N7），成功后刷新列表与标签计数。 */
async function saveTags(task, names) {
  const unique = [...new Set(names.map((name) => name.trim()).filter(Boolean))]
  try {
    await apiJson(`/api/tasks/${task.id}/tags`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tags: unique.map((name) => ({ name, kind: tagKindOf(name) })),
      }),
    })
    tagError.value = ''
    await loadTasksAndSync(filters.value)
    await loadKnowledge()
    return true
  } catch (err) {
    tagError.value = `标签没存上（${err.message || '网络或服务异常'}）`
    return false
  }
}

async function commitTag(task) {
  const name = tagDraft.value.trim()
  if (!name) {
    cancelTag()
    return
  }
  const current = task.tags || []
  if (current.includes(name)) {
    cancelTag()
    return
  }
  const ok = await saveTags(task, [...current, name])
  if (ok) cancelTag()
}

async function removeTag(task, name) {
  const current = task.tags || []
  await saveTags(
    task,
    current.filter((item) => item !== name),
  )
}

function applyFilters(next) {
  filters.value = { ...next }
  loadTasksAndSync(filters.value)
}

function clearFilters() {
  applyFilters({})
}

function goReadHome() {
  navigate('readHome')
}

/** 卡片上「归到」下拉显示的当前值（0 个集合 = 未归类 = 空串）。 */
function primaryCollectionId(task) {
  const ids = Array.isArray(task?.collection_ids) ? task.collection_ids : []
  return ids.length === 1 ? String(ids[0]) : ''
}

/**
 * 归集（N5）。传 `[]` = 放回未归类。
 *
 * ⚠️ 成功后**重新拉列表**（不本地改）——归属的真相在服务端，本地改容易与
 * `collection_ids` 失配，而失配的下一步就是"改一个抹掉另一个"。
 */
async function assignCollection(task, value) {
  const ids = value === '' ? [] : [Number(value)]
  try {
    await apiJson(`/api/tasks/${task.id}/collections`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ collection_ids: ids }),
    })
    await Promise.all([loadTasksAndSync(filters.value), loadKnowledge()])
  } catch (err) {
    taskActionError.value = `没归集成功（${err && err.message ? err.message : '网络或服务异常'}）`
  }
}
</script>
