<template>
  <!-- 桌面工具条：< 1024px 整条不渲染（手机端的顶栏是 .ptop，原型就是这么分开的）；
       手机要用的下载 / ⋯ 跟着搬到 .ptop 上，功能一个不少 -->
  <div v-if="!isNarrow" class="reader-top">
    <button class="btn ghost sm" @click="backToLibrary">← 我的论文</button>
    <span class="fname">{{ currentTask.filename }}</span>
    <!-- 档位只读；想换档请在 ⋯ 里以其他档位重新翻译（会新建任务） -->
    <span class="chip" title="上传时选定；想换档请在 ⋯ 里以其他档位重新翻译（会新建任务）">
      {{ currentTask.native ? '中文文献 · 不翻译' : tierTextMap[currentTask.tier] || currentTask.tier }}
    </span>
    <div class="menu-wrap">
      <span class="chip" role="button" tabindex="0" @click.stop="toggleMenu('mode')">
        {{ docModeLabel }} ▾
      </span>
      <div class="menu" :class="{ open: openMenu === 'mode' }">
        <button v-for="item in docModeOptions" :key="item.value" @click="setDocMode(item.value)">
          {{ item.label }}
        </button>
      </div>
    </div>
    <span class="spacer" />
    <button class="btn ghost sm" @click="toggleSearch">🔍 搜索</button>
    <span v-if="pageChipText" class="chip">{{ pageChipText }}</span>
    <!-- 下载入口只有一个，命名统一为「下载译稿」，两项在里面选 -->
    <div class="menu-wrap">
      <button class="btn ghost sm" @click.stop="toggleMenu('dl')">⤓ 下载译稿 ▾</button>
      <div class="menu" :class="{ open: openMenu === 'dl' }">
        <button v-for="item in downloadOptions" :key="item.key" @click="runDownload(item)">
          {{ item.label }}
        </button>
      </div>
    </div>
    <!-- 单层级、6 项、任意两项不共享动词 -->
    <div class="menu-wrap">
      <button class="btn ghost sm" @click.stop="toggleMenu('more')">⋯</button>
      <div class="menu" :class="{ open: openMenu === 'more' }">
        <button @click="openPanel('info', currentTask)">文档信息</button>
        <button :disabled="!canRetryCurrent" @click="retryCurrent">重试翻译（本档）</button>
        <button @click="openPanel('retier', currentTask)">换档位重译…</button>
        <button @click="openPanel('blocks', currentTask)">详情</button>
        <button @click="openPanel('feedback', currentTask)">问题反馈…</button>
        <div class="sep" />
        <button class="danger" @click="openDeletePanel">删除…</button>
      </div>
    </div>
  </div>

  <!-- 极细进度条：永远在；不确定时画流动条纹（桌面；手机端用它自己的 .progress-line） -->
  <div v-if="!isNarrow" class="thin-bar" :class="{ striped: thinBar.striped }">
    <i :style="{ width: thinBar.width }" />
  </div>

  <!-- 空的时候必须真的是空的：原型靠 .note-line:not(:empty) 决定要不要那条分隔线 -->
  <div v-if="!isNarrow" class="note-line">
    <div v-if="searchOpen" class="search-row">
      <input
        v-model="searchTerm"
        class="search-input"
        placeholder="在这篇文献的正文里找…"
        @keydown.enter="runSearch"
      />
      <button class="btn sm" @click="runSearch">查找</button>
      <button class="btn ghost sm" @click="toggleSearch">关闭</button>
    </div>
    <template v-else-if="noteLineText">{{ noteLineText }}</template>
  </div>

  <div class="reader-body">
    <!-- 左栏 · 段落精读（自己的 DOM，出处锚点才成立） -->
    <div
      v-if="!isNarrow && docMode === 'paragraph'"
      ref="docPaneEl"
      class="doc-pane"
      @scroll="onPaneScroll"
    >
      <div v-if="scannedNotice" class="card doc-note">
        这份文献是扫描件：文字由本地 OCR 识别，可能有个别错字；出处与引用都按识别结果给出。
      </div>
      <div v-if="noBlockTranslationNotice" class="card doc-note">
        这篇文献暂无「块级」译文（译文在 PDF 产物里，段落视图拿不到），下面显示的是原文；
        问答与检索同样基于原文。
      </div>
      <div v-if="showOutline" class="toc">
        <button class="toc-head" @click="outlineOpen = !outlineOpen">
          <span>目录 · {{ outlineItems.length }} 节</span>
          <i>{{ outlineOpen ? '收起' : '展开' }}</i>
        </button>
        <ol v-if="outlineOpen" class="toc-list">
          <li v-for="item in outlineItems" :key="item.blockId">
            <button
              class="toc-item"
              :class="'toc-' + item.type"
              @click="goOutline(item)"
            >
              <span class="toc-text">{{ item.text }}</span>
              <span class="toc-page">{{
                item.page === null ? '' : `第 ${item.page + 1} 页`
              }}</span>
            </button>
          </li>
        </ol>
      </div>
      <div v-if="!docPages.length" class="card doc-note">{{ docEmptyText }}</div>
      <template v-else>
        <div
          v-for="(page, pageIndex) in docPages"
          :key="page.key"
          :ref="(el) => setPageEl(page.page, el)"
          class="page"
          :data-page-key="page.key"
          @mouseup="onDocMouseUp($event, $event.currentTarget)"
        >
          <h3>{{ pageIndex === 0 ? docTitle : page.label }}</h3>
          <div v-if="pageIndex === 0" class="authors">{{ docMetaLine }}</div>
          <div class="cols">
            <p
              v-for="row in page.rows"
              :key="row.block.block_id"
              :id="row.block.block_id"
              :ref="(el) => setBlockEl(row.block.block_id, el)"
              :data-block-id="row.block.block_id"
              :title="'原文块 ' + row.block.block_id"
              :class="{
                anchor: flashId === row.block.block_id,
                flash: flashId === row.block.block_id,
                sel: pickedBlockId === row.block.block_id,
                ['pg-' + (row.block.type || 'body')]: true,
              }"
              @click="onBlockClick(row, $event)"
            >
              <span v-if="hasBlockTranslations" class="en">{{ row.source }}</span>
              {{ row.main }}
            </p>
          </div>
          <button
            v-if="selChip && selChip.pageKey === page.key"
            class="selchip"
            :style="{ left: selChip.left + 'px', top: selChip.top + 'px' }"
            @mousedown.prevent
            @mouseup.stop
            @click="askSelectedSentence"
          >
            就这句提问
          </button>
        </div>
      </template>
    </div>

    <!-- 左栏 · 原版 / 纯中文 / 双语 PDF：pdf.js 渲染（有文字层，所以能定位、能点段落提问） -->
    <div v-else-if="!isNarrow" class="doc-pane pdf-mode">
      <PdfPane
        :task-id="currentTask.id"
        :variant="docMode"
        :doc-page-count="docPageCount"
        :start-page="pdfStartPage"
        :locate-text="locateText"
        :locate-key="locateKey"
        :fallback-page="pdfFallbackPage"
        :has-dual="fileAvailability.dual"
        @locate="onPdfLocate"
        @ask="onPdfAsk"
        @page-change="(n) => (currentPage = n)"
      />
    </div>

    <!-- 手机 · 顶栏是 .ptop（原型手机屏就是这么一根），不是桌面那条 reader-top -->
    <div v-else class="mobile-reader">
      <div class="ptop">
        <button class="btn ghost sm ptop-icon" @click="backToLibrary">←</button>
        <span class="spacer" />
        <span class="fname">{{ currentTask.filename }}</span>
        <span class="spacer" />
        <button class="btn ghost sm ptop-icon" :title="mobileOriginalTitle" @click="toggleMobileOriginal">
          {{ docMode === 'paragraph' ? pdfQuickLabel : '段落' }}
        </button>
        <!-- 下载入口只有一个名字（「下载译稿 ▾」），手机上不例外 -->
        <div class="menu-wrap">
          <button class="btn ghost sm ptop-icon" title="下载译稿" @click.stop="toggleMenu('dl')">⤓</button>
          <div class="menu" :class="{ open: openMenu === 'dl' }">
            <button v-for="item in downloadOptions" :key="item.key" @click="runDownload(item)">
              {{ item.label }}
            </button>
          </div>
        </div>
        <div class="menu-wrap">
          <button class="btn ghost sm ptop-icon" title="更多" @click.stop="toggleMenu('more')">⋯</button>
          <div class="menu" :class="{ open: openMenu === 'more' }">
            <button @click="openPanel('info', currentTask)">文档信息</button>
            <button :disabled="!canRetryCurrent" @click="retryCurrent">重试翻译（本档）</button>
            <button @click="openPanel('retier', currentTask)">换档位重译…</button>
            <button @click="openPanel('blocks', currentTask)">详情</button>
            <button @click="openPanel('feedback', currentTask)">问题反馈…</button>
            <div class="sep" />
            <button class="danger" @click="openDeletePanel">删除…</button>
          </div>
        </div>
      </div>
      <div class="progress-line">
        <span>{{ pageChipText || stageText }}</span>
        <div class="pl-bar" :class="{ striped: thinBar.striped }"><i :style="{ width: thinBar.width }" /></div>
        <span>{{ statusTextMap[currentTask.status] }}</span>
      </div>
      <!-- 菜单说明这类一次性提示，手机上没有 note-line 可挂，就挂在进度行下面（有内容才占位） -->
      <div v-if="noteLineText" class="note-line">{{ noteLineText }}</div>
      <div class="reader-ctrls">
        <span>
          字号
          <button class="rc-btn" @click="stepFont(-1)">A-</button>
          <button class="rc-btn" @click="stepFont(1)">A+</button>
        </span>
        <span class="spacer" />
        <span v-if="isNativeTask" class="on">原文中文</span>
        <div v-else class="menu-wrap">
          <button class="rc-btn on" @click.stop="toggleMenu('dual')">{{ mobileLangLabel }} ▾</button>
          <div class="menu" :class="{ open: openMenu === 'dual' }">
            <button
              v-for="item in docModeOptions"
              :key="item.value"
              :disabled="item.value === docMode"
              @click="setDocMode(item.value)"
            >
              {{ item.label }}
            </button>
          </div>
        </div>
      </div>
      <div v-if="docMode === 'paragraph'" class="pdoc" :style="pdocStyle">
        <div v-if="scannedNotice" class="honest pdoc-note">
          这份文献是扫描件：文字由本地 OCR 识别，可能有个别错字。
        </div>
        <div v-if="noBlockTranslationNotice" class="honest pdoc-note">
          这篇文献暂无「块级」译文（译文在 PDF 产物里）——下面显示的是原文。
        </div>
        <div v-if="showOutline" class="toc">
          <button class="toc-head" @click="outlineOpen = !outlineOpen">
            <span>目录 · {{ outlineItems.length }} 节</span>
            <i>{{ outlineOpen ? '收起' : '展开' }}</i>
          </button>
          <ol v-if="outlineOpen" class="toc-list">
            <li v-for="item in outlineItems" :key="item.blockId">
              <button
                class="toc-item"
                :class="'toc-' + item.type"
                @click="goOutline(item)"
              >
                <span class="toc-text">{{ item.text }}</span>
                <span class="toc-page">{{
                  item.page === null ? '' : `第 ${item.page + 1} 页`
                }}</span>
              </button>
            </li>
          </ol>
        </div>
        <div v-if="!paragraphRows.length" class="card doc-note">{{ docEmptyText }}</div>
        <template
          v-for="row in pdocRows"
          :key="row.kind === 'page' ? 'sep-' + row.page : row.block.block_id"
        >
          <div v-if="row.kind === 'page'" class="pg-sep">{{ row.label }}</div>
          <template v-else>
            <div
              :id="'m_' + row.block.block_id"
              :ref="(el) => setBlockEl(row.block.block_id, el)"
              :data-block-id="row.block.block_id"
              class="pg"
              :class="[
                'pg-' + (row.block.type || 'body'),
                { flash: flashId === row.block.block_id },
              ]"
            >
              <!-- 触发热区收窄到「段 N」标签本身（不与系统选词 / 滚动抢手势） -->
              <span
                class="seg-no"
                :class="{ 'seg-btn': row.index !== null }"
                :title="row.index !== null ? '点段号提问' : ''"
                @click="togglePgChip(row)"
              >
                {{ row.index !== null ? row.label : '—' }}
              </span>
              <div>
                <div v-if="hasBlockTranslations" class="en">{{ row.source }}</div>
                <div class="zh">{{ row.main }}</div>
              </div>
            </div>
            <button v-if="pgChipFor === row.block.block_id" class="pg-chip" @click="askParagraph(row)">
              就这段提问
            </button>
          </template>
        </template>
      </div>
      <!-- 手机上的「原版」：同一套 pdf.js 视图，换的是容器 -->
      <div v-else class="pdoc-pdf">
        <PdfPane
          :task-id="currentTask.id"
          :variant="docMode"
          :doc-page-count="docPageCount"
          :start-page="pdfStartPage"
          :locate-text="locateText"
          :locate-key="locateKey"
          :fallback-page="pdfFallbackPage"
        :has-dual="fileAvailability.dual"
          @locate="onPdfLocate"
          @ask="onPdfAsk"
          @page-change="(n) => (currentPage = n)"
        />
      </div>
    </div>

    <!-- 助手区：桌面 = 右栏；手机 = 底部抽屉三档。**同一份 DOM**，只有容器类名不同 -->
    <div :class="assistClass">
      <template v-if="isNarrow">
        <div class="grip" @click="cycleSheet">
          <i /><span>{{ sheetGripText }}</span>
        </div>
        <div class="peek-summary">{{ peekSummary }}</div>
        <div v-if="locatedHint" class="peek-line">
          {{ locatedHint }} · 正文已滚到该段 ·
          <button class="sample-link" @click="sheetState = 'half'">点我回来</button>
        </div>
      </template>

      <div class="tabs">
        <button
          v-for="tab in assistTabs"
          :key="tab.key"
          :class="{ on: assistTab === tab.key }"
          @click="switchTab(tab.key)"
        >
          {{ tab.label }}
        </button>
      </div>

      <div :class="assistBodyClass" :ref="setAssistBody">
        <div v-if="honestNote" class="honest">{{ honestNote }}</div>

        <!-- ============ 问答 ============ -->
        <div class="tabpane" :class="{ on: assistTab === 'ask' }">
          <div class="chips">
            <button
              v-for="chip in quickChips"
              :key="chip.label"
              :disabled="askLoading"
              @click="askPreset(chip.q)"
            >
              {{ chip.label }}
            </button>
          </div>
          <div class="chips-hint">{{ askChipsHint }}</div>

          <div v-for="turn in askTurns" :key="turn.id" class="turn">
            <div class="bubble-q">{{ turn.question }}</div>
            <div v-if="turn.loading" class="bubble-a muted">正在读原文并作答…</div>
            <div v-else-if="turn.error" class="fail-card">
              {{ turn.error }}
              <div v-if="turn.errorDetail" class="q-kept">{{ turn.errorDetail }}</div>
              <div class="q-kept">你的问题已保留：「{{ turn.question }}」</div>
              <button class="btn primary sm" style="margin-top: 8px" @click="retryTurn(turn)">重试</button>
            </div>
            <template v-else>
              <div class="bubble-a">
                {{ turn.answer }}
                <div class="srcs">
                  <span class="lbl">出处：</span>
                  <template v-if="turn.sources.length">
                    <button
                      v-for="src in turn.sources"
                      :key="src.id"
                      class="src-tag"
                      :class="{ unknown: !src.found }"
                      :title="'原文块 ' + src.ids.join(' + ')"
                      @click="traceTo(src.id, { text: src.text })"
                    >
                      {{ src.label || '出处未能定位' }} ▸
                    </button>
                  </template>
                  <span v-else class="lbl">（回答未给出处）</span>
                </div>
              </div>
              <div class="a-tools">
                <span v-if="turn.mode === 'fts'" class="muted">长文 · 检索模式</span>
                <button @click="copyAnswer(turn)">{{ turn.copied ? '已复制' : '复制答案' }}</button>
                <button v-if="turn.sources.length" @click="traceTo(turn.sources[0].id, { text: turn.sources[0].text })">展开原文</button>
              </div>
            </template>
          </div>

          <div v-if="!askTurns.length" class="chips-hint">
            问点什么吧——答案会标出处，点出处能跳回原文那一段并高亮一次。
          </div>
        </div>

        <!-- ============ 导读 ============ -->
        <div class="tabpane" :class="{ on: assistTab === 'guide' }">
          <div v-if="understandingLoading" class="chips-hint">{{ guideEmptyText }}</div>
          <div v-else-if="understandingStatus === 'failed'" class="fail-card">
            {{ understandingError || '导读生成失败' }}
            <button class="btn primary sm" style="margin-top: 8px" @click="retryUnderstanding">重试</button>
          </div>
          <div v-else-if="!guidePoints.length" class="chips-hint">{{ guideEmptyText }}</div>
          <template v-else>
            <div v-for="point in guidePoints" :key="point.key" class="guide-card">
              <div class="k">{{ point.label }}</div>
              <div class="v">{{ point.text }}</div>
              <div class="ops">
                <template v-if="point.sources.length">
                  <button
                    v-for="src in point.sources"
                    :key="src.id"
                    :title="'原文块 ' + src.ids.join(' + ')"
                    @click="traceTo(src.id, { text: src.text })"
                  >
                    看原文（{{ src.label || '位置待定' }}）▸
                  </button>
                </template>
                <!-- 没有单一段落出处 → 降级态置灰、不可点、不给箭头 -->
                <button v-else class="dead" disabled>无单一段落出处</button>
                <button @click="probePoint(point)">就这条追问</button>
              </div>
              <div v-if="!point.sources.length" class="dead-note">
                该要点由全文综合而成，没有哪一段能单独代表它——所以这里不给「看原文」。
              </div>
            </div>
          </template>
        </div>

        <!-- ============ 术语 ============ -->
        <div class="tabpane" :class="{ on: assistTab === 'terms' }">
          <div v-if="understandingLoading" class="chips-hint">{{ termsEmptyText }}</div>
          <div v-else-if="understandingStatus === 'failed'" class="fail-card">
            {{ understandingError || '术语表生成失败' }}
            <button class="btn primary sm" style="margin-top: 8px" @click="retryUnderstanding">重试</button>
          </div>
          <div v-else-if="!termItems.length" class="chips-hint">{{ termsEmptyText }}</div>
          <template v-else>
            <div class="termlist">
              <div v-for="item in termItems" :key="item.key" class="term">
                <b>{{ item.term }}</b><span class="cn">{{ item.cn }}</span>
                <div class="def">{{ item.definition }}</div>
                <div class="ops">
                  <button @click="locateTerm(item)">{{ item.locate }}</button>
                </div>
              </div>
            </div>
            <div class="chips-hint">
              术语表当前没有出处字段：按钮只在「命中之后」才回填坐标，未命中会直说「没找到」——不预填假坐标。
            </div>
          </template>
        </div>
      </div>

      <!-- 问答输入框吸底 -->
      <div class="composer">
        <textarea
          v-model="askQuestion"
          rows="1"
          :placeholder="composerPlaceholder"
          :disabled="askLoading"
          @keydown.enter.exact.prevent="submitAsk"
        />
        <button class="btn primary" :disabled="askLoading || !askQuestion.trim()" @click="submitAsk">
          ↑
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * L2 阅读工作区：桌面工具条 / 细进度条 / 提示行 / 左栏（段落精读 · pdf.js）/ 右助手三副页签。
 *
 * **纯搬迁**：模板整段来自 `App.vue` 的「L2 阅读工作区」段，一个类名、一句文案都没改。
 * 状态在 `stores/useReader`（+ `stores/useUi` 的界面零碎事、`stores/useAsk` 的问答线程、
 * `stores/useLibrary` 的任务动作与弹层）。跨视图共享的东西都不在这个组件里。
 *
 * ⚠️ 唯一一个 prop 是 `peekSummary`（手机抽屉收起时那行摘要）：它要读 `useAsk` 的
 * `lastQuestion`，而"摘要留在外壳"是上一轮定下的（放进 `useUi` 会绕成环），
 * 所以由 `App.vue` 算好、当 prop 传进来。
 */
import PdfPane from '../components/PdfPane.vue'
import {
  askChipsHint,
  askLoading,
  askParagraph,
  askPreset,
  askQuestion,
  askTurns,
  composerPlaceholder,
  copyAnswer,
  probePoint,
  quickChips,
  retryTurn,
  submitAsk,
} from '../stores/useAsk'
import { canRetryCurrent, openDeletePanel, openPanel, retryCurrent } from '../stores/useLibrary'
import {
  askSelectedSentence,
  assistTabs,
  backToLibrary,
  currentPage,
  currentTask,
  docEmptyText,
  docMetaLine,
  docMode,
  docModeLabel,
  docModeOptions,
  docPageCount,
  docPages,
  docPaneEl,
  docTitle,
  downloadOptions,
  fileAvailability,
  flashId,
  goOutline,
  guideEmptyText,
  guidePoints,
  hasBlockTranslations,
  honestNote,
  isNativeTask,
  locateKey,
  locateTerm,
  locateText,
  mobileLangLabel,
  mobileOriginalTitle,
  noBlockTranslationNotice,
  noteLineText,
  onBlockClick,
  onDocMouseUp,
  onPaneScroll,
  onPdfAsk,
  onPdfLocate,
  outlineItems,
  outlineOpen,
  pageChipText,
  paragraphRows,
  pdfFallbackPage,
  pdfQuickLabel,
  pdfStartPage,
  pickedBlockId,
  pdocRows,
  retryUnderstanding,
  runDownload,
  runSearch,
  scannedNotice,
  searchOpen,
  searchTerm,
  selChip,
  setBlockEl,
  setDocMode,
  setPageEl,
  showOutline,
  stageText,
  switchTab,
  termItems,
  termsEmptyText,
  thinBar,
  toggleMobileOriginal,
  toggleSearch,
  traceTo,
  understandingError,
  understandingLoading,
  understandingStatus,
} from '../stores/useReader'
import { statusTextMap, tierTextMap } from '../stores/useTasks'
import {
  assistBodyClass,
  assistClass,
  assistTab,
  cycleSheet,
  isNarrow,
  locatedHint,
  openMenu,
  pgChipFor,
  pdocStyle,
  setAssistBody,
  sheetGripText,
  sheetState,
  stepFont,
  toggleMenu,
  togglePgChip,
} from '../stores/useUi'

defineProps({ peekSummary: { type: String, default: '' } })
</script>
