<template>
  <!-- 「读懂」开工页（2026-10-17 知识库重构）。
       ⭐ 以前这一屏只在"库里一篇都没有"时出现（`libraryEmpty`），所以你有 6 篇论文时
       **永远看不到上传入口**——那正是"点读懂却是清单"的根因。
       现在它是一张**常驻的页**：上传 / 示例 / 继续读 / 最近三篇，跟"有几篇论文"无关。 -->
  <section class="rh">
    <header class="rh-hero">
      <h1 class="rh-h1">把文献读懂</h1>
      <p class="rh-tagline">翻译只是起点，理解才是价值</p>
      <p class="rh-lede">
        上传文献 PDF，得到双语对照稿、结构化导读与统一术语表；
        还能就文献提问，每条答案都标明来自哪一段原文。
      </p>
      <div class="rh-pills">
        <button type="button" class="pill" @click="openExample('guide')">
          看示例论文的结构化导读
        </button>
        <button type="button" class="pill" @click="openExample('terms')">
          看示例论文的术语表
        </button>
        <button type="button" class="pill" @click="openExample('ask')">
          看示例论文的带出处问答
        </button>
      </div>
    </header>

    <!-- 继续读：有"上次读到第几页"的那一篇，直接给一条明显的入口 -->
    <div v-if="continueTask" class="rh-continue">
      <div class="rh-continue-main">
        <span class="rh-continue-k">继续读</span>
        <span class="rh-continue-name">{{ continueTask.filename }}</span>
        <span class="rh-continue-page">上次读到第 {{ continueTask.last_read_page }} 页</span>
      </div>
      <button type="button" class="btn primary sm" @click="openTask(continueTask)">接着读</button>
    </div>

    <!-- 上传卡（空库/已有文献都摆着——这是"开始做事"的地方） -->
    <div class="card upload-card rh-upload">
      <div
        class="drop"
        :class="{ 'drop-over': uploading || dropHinting }"
        @click="pickFile()"
        @dragover.prevent
        @drop.prevent="onDrop"
      >
        <div class="big">点击或拖拽 PDF 到此处</div>
        <div class="tiny">
          {{
            selectedLang === 'zh'
              ? '上传后自动抽取文字并生成导读；完成后可读原文、导读与术语表'
              : '上传后自动开始翻译；完成后可读双语稿、导读与术语表'
          }}
        </div>
        <div class="drop-hint">
          支持电子版 PDF 与扫描件（扫描件走本地 OCR，文字可能有错字）；耗时取决于页数与档位
        </div>
        <div v-if="uploading" class="drop-hint">正在上传…</div>
        <div v-if="uploadError" class="drop-hint rh-err">{{ uploadError }}</div>
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
          <div class="tier-label rh-tier-gap">翻译档位</div>
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

    <!-- 最近三篇：**只放进阅读区的门**，不做筛选、不做删除（管理在「历史记录」） -->
    <div v-if="recent.length" class="rh-recent">
      <div class="rh-recent-head">
        <h2 class="rh-h2">最近读过</h2>
        <button type="button" class="btn ghost sm" @click="goHistory">全部 {{ total }} 篇 →</button>
      </div>
      <div class="rh-recent-grid">
        <button
          v-for="task in recent"
          :key="task.id"
          type="button"
          class="card rh-card"
          @click="openTask(task)"
        >
          <span class="rh-card-name">{{ task.filename }}</span>
          <span class="rh-card-meta">
            <span class="chip" :class="statusChipMap[task.status] || ''">
              {{ statusTextMap[task.status] || task.status }}
            </span>
            <span v-if="task.native" class="chip">中文文献</span>
          </span>
        </button>
      </div>
    </div>

    <div v-else-if="!historyLoading" class="rh-empty">
      还没有文献。上面拖一份 PDF 进来，或者
      <button type="button" class="rh-link" @click="goHistory">去历史记录看看</button>。
    </div>
  </section>
</template>

<script setup>
/**
 * 「读懂」开工页 = **开始做事的地方**（2026-10-17）。
 *
 * 与「历史记录」的分工（这是本次重构的核心，别混回去）：
 * - **读懂（这一页）**：上传 / 示例 / 继续读 / 最近三篇 —— 只放**入口**，不放筛选、不放删除；
 * - **历史记录（`#/library`）**：全部文献 + 筛选 + 排序 + 删除 —— 只做**管理**。
 *
 * 数据全部来自既有 store（`useLibrary` 的上传态、`useTasks` 的列表），
 * 这一页**不自己取数**，所以不会出现"两处各拉一份、口径不一致"。
 */
import { computed } from 'vue'

import {
  dropHinting,
  langOptions,
  onDrop,
  openExample,
  pickFile,
  selectedLang,
  selectedTier,
  tierOptions,
  uploading,
  uploadError,
} from '../stores/useLibrary'
import { openTask } from '../stores/useReader'
import { historyLoading, statusChipMap, statusTextMap, tasks } from '../stores/useTasks'
import { navigate } from '../router'

const total = computed(() => tasks.value.length)

/** 继续读：优先"有上次阅读位置"的那一篇（列表已按新→旧）。 */
const continueTask = computed(() => tasks.value.find((task) => task.last_read_page) || null)

/** 最近三篇：列表前三条（同样是新的在前）。 */
const recent = computed(() => tasks.value.slice(0, 3))

function goHistory() {
  navigate('library')
}
</script>
