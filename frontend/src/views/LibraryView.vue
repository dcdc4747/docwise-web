<template>
  <div class="lib-wrap">
    <!-- 空库态才出大 hero；三枚标签是**可点的描边按钮**（点了进对应副页签） -->
    <div v-if="libraryEmpty" class="hero">
      <h1>把文献读懂</h1>
      <p class="tagline">翻译只是起点，理解才是价值</p>
      <p>
        上传文献 PDF，得到双语对照稿、结构化导读与统一术语表；
        还能就文献提问，每条答案都标明来自哪一段原文。
      </p>
      <div class="pills">
        <button class="pill" @click="openExample('guide')">看示例论文的结构化导读</button>
        <button class="pill" @click="openExample('terms')">看示例论文的术语表</button>
        <button class="pill" @click="openExample('ask')">看示例论文的带出处问答</button>
      </div>
    </div>

    <div v-else class="title-row">
      <h2>我的论文（{{ tasks.length }} 篇）</h2>
      <span class="spacer" />
      <button class="btn primary" @click="showUpload = !showUpload">
        {{ showUpload ? '收起上传' : '＋ 上传 PDF' }}
      </button>
    </div>

    <!-- 上传卡：空库时就在 hero 下面；有历史时由「＋ 上传 PDF」按需展开 -->
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
        <div class="drop-hint">支持电子版 PDF 与扫描件（扫描件走本地 OCR，文字可能有错字）；耗时取决于页数与档位</div>
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

    <template v-if="!libraryEmpty">
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

      <div v-else-if="!taskCards.length" class="card muted">
        还没有可读的论文——上面点「＋ 上传 PDF」传一篇，译文出来后会出现在这里。
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

      <div class="footline">
        <span v-if="taskActionError" style="color: var(--danger)">{{ taskActionError }}</span>
        <span class="spacer" />
        <span>docwise · 学术文献理解智能体</span>
      </div>
    </template>
  </div>
</template>

<script setup>
/**
 * L1「我的论文」库页：空库 hero、上传卡、进行中任务条、完成横幅、论文卡片网格。
 *
 * **纯搬迁**：模板整段来自 `App.vue` 的「L1 库页」段，一个类名、一句文案都没改。
 * 状态不在这里，在 `stores/useLibrary`——阅读区也要用其中几样（当前在读哪一篇、
 * 打开任务），放视图里就共享不了了。这个组件只管"把 store 的东西摆出来"。
 *
 * ⚠️ 顶栏 `.topbar`（品牌 / 账号菜单 / 退出）**留在 `App.vue`**：它是外壳的登录分发，
 * 与"当前显示哪个视图"同属一件事；拆进视图反而要穿 4 个 props + 2 个事件，
 * 为的是把 18 行挪个地方，并不划算。
 */
import {
  activeBars,
  bannerMeta,
  cancelTask,
  completedBannerTask,
  deleteConfirmId,
  deleteTask,
  dismissBanner,
  dropHinting,
  langOptions,
  libraryEmpty,
  loadTasksAndSync,
  onDrop,
  openExample,
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
import { openTask } from '../stores/useReader'
import { historyError, statusTextMap, tasks } from '../stores/useTasks'
</script>
