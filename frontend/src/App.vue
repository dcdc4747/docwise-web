<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import {
  zhCN,
  dateZhCN,
  NConfigProvider,
  NLayout,
  NLayoutHeader,
  NLayoutContent,
  NLayoutFooter,
  NGrid,
  NGi,
  NCard,
  NTag,
  NUpload,
  NUploadDragger,
  NText,
  NProgress,
  NAlert,
  NButton,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NRadioButton,
  NRadioGroup,
  NSpace,
  NSpin,
} from 'naive-ui'

const backendStatus = ref('checking')
const taskCount = ref(null)
const uploading = ref(false)
const uploadError = ref('')
const currentTask = ref(null)
const uploadRef = ref(null)
const previewMode = ref('mono')
const fileAvailability = ref({ mono: false, dual: false })
const previewCheckDone = ref(false)
const previewLoading = ref(true)
const selectedTier = ref('fast')

const tierOptions = [
  { value: 'fast', label: '快', desc: '速度优先' },
  { value: 'medium', label: '中', desc: '质量与速度平衡' },
  { value: 'precise', label: '慢', desc: '质量优先' },
]

const tierTextMap = {
  fast: '快',
  medium: '中',
  precise: '慢',
}

const tasks = ref([])
const historyLoading = ref(false)
const historyError = ref('')

const drawerVisible = ref(false)
const detailTaskId = ref(null)
const detailTitle = ref('')
const detailLoading = ref(false)
const detailError = ref('')
const detailTask = ref(null)

const statusMeta = {
  checking: { type: 'default', text: '检测中…' },
  ok: { type: 'success', text: '已连接' },
  down: { type: 'error', text: '未连接（请先启动后端）' },
}

const statusTextMap = {
  pending: '等待中',
  in_progress: '翻译中',
  completed: '已完成',
  failed: '失败',
}

const statusTypeMap = {
  pending: 'default',
  in_progress: 'info',
  completed: 'success',
  failed: 'error',
}

const tierTextMap = {
  fast: '快档',
  medium: '中档',
  precise: '精档',
}

const blockStatusMeta = {
  success: { type: 'success', text: '成功' },
  overflow: { type: 'warning', text: '溢出' },
  failed: { type: 'error', text: '失败' },
}

let eventSource = null
let pollTimer = null

onMounted(async () => {
  try {
    const res = await fetch('/api/health')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    await res.json()
    backendStatus.value = 'ok'
    await loadTasks()
  } catch {
    backendStatus.value = 'down'
  }
})

function progressPercent() {
  if (!currentTask.value) return 0
  return Math.round((currentTask.value.progress ?? 0) * 100)
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function loadTasks() {
  historyLoading.value = true
  historyError.value = ''
  try {
    const res = await fetch('/api/tasks')
    if (!res.ok) throw new Error(`历史任务加载失败（HTTP ${res.status}）`)
    tasks.value = await res.json()
    taskCount.value = tasks.value.length
  } catch (err) {
    historyError.value = err.message || '历史任务加载失败'
  } finally {
    historyLoading.value = false
  }
}

async function fetchTaskDetail(taskId) {
  detailLoading.value = true
  detailError.value = ''
  detailTask.value = null
  try {
    const res = await fetch(`/api/tasks/${taskId}`)
    if (!res.ok) throw new Error(`任务详情加载失败（HTTP ${res.status}）`)
    detailTask.value = await res.json()
  } catch (err) {
    detailError.value = err.message || '任务详情加载失败'
  } finally {
    detailLoading.value = false
  }
}

function openTaskDetail(task) {
  detailTaskId.value = task.id
  detailTitle.value = task.filename
  drawerVisible.value = true
  fetchTaskDetail(task.id)
}

async function handleUpload({ file: fileInfo, onFinish, onError }) {
  uploading.value = true
  uploadError.value = ''
  currentTask.value = null
  previewCheckDone.value = false
  previewLoading.value = true
  fileAvailability.value = { mono: false, dual: false }
  stopProgress()

  const form = new FormData()
  form.append('file', fileInfo.file)
  form.append('tier', selectedTier.value)

  try {
    const res = await fetch('/api/tasks/upload', { method: 'POST', body: form })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail || `上传失败（HTTP ${res.status}）`)
    }
    const task = await res.json()
    currentTask.value = task
    onFinish()
    startProgress(task.id)
  } catch (err) {
    uploadError.value = err.message || '上传失败，请重试'
    onError()
  } finally {
    uploading.value = false
    loadTasks()
  }
}

function handleFilesChange({ fileList }) {
  // 选择/拖拽文件后自动提交，进入翻译任务
  if (fileList.length && fileList.some((f) => f.status === 'pending')) {
    // Naive UI 在 on-change 回调时内部列表尚未更新，推迟到下一轮事件循环再提交
    setTimeout(() => uploadRef.value?.submit(), 0)
  }
}

function startProgress(taskId) {
  stopProgress()
  const es = new EventSource(`/api/tasks/${taskId}/events`)
  eventSource = es
  es.onmessage = (e) => {
    let evt
    try {
      evt = JSON.parse(e.data)
    } catch {
      return
    }
    applyEvent(evt)
    if (['completed', 'failed'].includes(evt.type)) stopProgress()
  }
  es.onerror = () => {
    // SSE 断开时轮询兜底，避免进度卡死
    stopProgress()
    startPolling(taskId)
  }
}

function startPolling(taskId) {
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/tasks/${taskId}`)
      if (!res.ok) return
      const task = await res.json()
      applyEvent({
        type: task.status,
        status: task.status,
        progress: task.progress,
        error: task.error_message,
      })
      if (['completed', 'failed'].includes(task.status)) stopProgress()
    } catch {
      // 后端暂不可达，等待下一轮
    }
  }, 2000)
}

function applyEvent(evt) {
  if (!currentTask.value) return
  currentTask.value.status = evt.status || currentTask.value.status
  if (typeof evt.progress === 'number') currentTask.value.progress = evt.progress
  if (evt.error) currentTask.value.error_message = evt.error
  if (['completed', 'failed'].includes(evt.type)) loadTasks()
  if (currentTask.value.status === 'completed' && !previewCheckDone.value) {
    checkPreview(currentTask.value.id)
  }
}

async function checkPreview(taskId) {
  previewCheckDone.value = true
  previewLoading.value = true
  try {
    const [mono, dual] = await Promise.all([
      fetch(`/api/tasks/${taskId}/files/mono`, { method: 'HEAD' })
        .then((r) => r.ok)
        .catch(() => false),
      fetch(`/api/tasks/${taskId}/files/dual`, { method: 'HEAD' })
        .then((r) => r.ok)
        .catch(() => false),
    ])
    fileAvailability.value = { mono, dual }
    // 若当前档位不可用，自动切到可用的那个，避免预览空白
    if (!mono && dual) previewMode.value = 'dual'
    else if (!dual && mono) previewMode.value = 'mono'
  } finally {
    previewLoading.value = false
  }
}

function previewUrl() {
  if (!currentTask.value) return ''
  return `/api/tasks/${currentTask.value.id}/files/${previewMode.value}`
}

function downloadUrl(kind) {
  if (!currentTask.value) return ''
  return `/api/tasks/${currentTask.value.id}/files/${kind}?download=1`
}

function stopProgress() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onUnmounted(stopProgress)
</script>

<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN">
    <n-layout class="page-layout">
      <n-layout-header bordered class="page-header">
        <div class="page-header-inner">
          <span class="brand">docwise-web</span>
          <span class="brand-sub">文档翻译智能体</span>
        </div>
      </n-layout-header>

      <n-layout-content content-style="padding: 0">
        <main class="page-main">
          <section class="page-hero">
            <h1>文档翻译智能体</h1>
            <p class="tagline">Agent 是大脑，程序是手脚</p>
            <p class="description">
              上传英文文献 PDF，获得「像原文档的中文版」：
              翻译、结构保留排版、质检一条龙。
            </p>
            <div class="tech-tags">
              <n-tag round>Vue 3</n-tag>
              <n-tag round type="info">Vite</n-tag>
              <n-tag round type="success">Naive UI</n-tag>
            </div>
          </section>

          <section class="page-section">
            <n-card title="上传英文文献 PDF" class="upload-card">
              <div class="tier-picker">
                <div class="tier-picker-head">
                  <n-text strong>翻译档位</n-text>
                  <n-text depth="3" class="tier-picker-sub">
                    不同档位走不同翻译引擎，请在上传前选择
                  </n-text>
                </div>
                <n-radio-group v-model:value="selectedTier" :disabled="uploading">
                  <n-radio-button
                    v-for="tier in tierOptions"
                    :key="tier.value"
                    :value="tier.value"
                  >
                    {{ tier.label }} · {{ tier.desc }}
                  </n-radio-button>
                </n-radio-group>
              </div>

              <n-upload
                ref="uploadRef"
                accept="application/pdf"
                :max="1"
                :default-upload="false"
                :custom-request="handleUpload"
                :disabled="uploading"
                :on-change="handleFilesChange"
              >
                <n-upload-dragger>
                  <div class="upload-hint">点击或拖拽 PDF 到此处</div>
                  <div class="upload-sub">上传后自动开始翻译，实时显示进度</div>
                </n-upload-dragger>
              </n-upload>

              <n-alert
                v-if="uploadError"
                type="error"
                class="upload-feedback"
                :show-icon="true"
              >
                {{ uploadError }}
              </n-alert>

              <div v-if="currentTask" class="task-progress">
                <div class="task-progress-head">
                  <div class="task-progress-title">
                    <n-text strong>{{ currentTask.filename }}</n-text>
                    <n-tag
                      v-if="currentTask.tier"
                      size="small"
                      :bordered="false"
                      type="warning"
                    >
                      档位：{{ tierTextMap[currentTask.tier] || currentTask.tier }}
                    </n-tag>
                  </div>
                  <n-tag
                    :type="statusTypeMap[currentTask.status] || 'default'"
                    :bordered="false"
                  >
                    {{ statusTextMap[currentTask.status] || currentTask.status }}
                  </n-tag>
                </div>
                <n-progress
                  type="line"
                  :percentage="progressPercent()"
                  :status="currentTask.status === 'failed' ? 'error' : currentTask.status === 'completed' ? 'success' : 'default'"
                  :processing="currentTask.status === 'in_progress'"
                  indicator-placement="inside"
                  :height="18"
                />
                <n-alert
                  v-if="currentTask.error_message"
                  type="error"
                  class="task-error"
                  :show-icon="true"
                >
                  {{ currentTask.error_message }}
                </n-alert>

                <div
                  v-if="currentTask.status === 'completed'"
                  class="result-panel"
                >
                  <div class="result-toolbar">
                    <n-radio-group v-model:value="previewMode" size="small">
                      <n-radio-button
                        value="mono"
                        :disabled="previewCheckDone && !fileAvailability.mono"
                      >
                        纯中文
                      </n-radio-button>
                      <n-radio-button
                        value="dual"
                        :disabled="previewCheckDone && !fileAvailability.dual"
                      >
                        中英对照
                      </n-radio-button>
                    </n-radio-group>
                    <n-space size="small">
                      <n-button
                        size="small"
                        tag="a"
                        :href="downloadUrl('mono')"
                        download
                        :disabled="previewCheckDone && !fileAvailability.mono"
                      >
                        下载纯中文 PDF
                      </n-button>
                      <n-button
                        size="small"
                        tag="a"
                        :href="downloadUrl('dual')"
                        download
                        :disabled="previewCheckDone && !fileAvailability.dual"
                      >
                        下载双语 PDF
                      </n-button>
                    </n-space>
                  </div>

                  <n-empty
                    v-if="previewCheckDone && !fileAvailability[previewMode]"
                    :description="
                      previewMode === 'dual'
                        ? '该任务暂无双语稿可预览'
                        : '该任务暂无中文稿可预览'
                    "
                    class="result-empty"
                  />
                  <n-spin v-else :show="previewLoading" size="small">
                    <iframe
                      v-if="fileAvailability[previewMode]"
                      :key="previewMode"
                      class="pdf-preview"
                      :src="previewUrl()"
                      title="译文预览"
                    />
                  </n-spin>
                </div>
              </div>
            </n-card>
          </section>

          <section class="page-section">
            <n-card title="历史记录" class="history-card">
              <template #header-extra>
                <n-button size="small" quaternary @click="loadTasks">刷新</n-button>
              </template>
              <n-spin :show="historyLoading">
                <n-empty
                  v-if="!historyLoading && !historyError && tasks.length === 0"
                  description="暂无历史任务，上传 PDF 后会自动出现在这里"
                  class="history-empty"
                />
                <n-alert v-else-if="historyError" type="error" :show-icon="true">
                  {{ historyError }}
                </n-alert>
                <div v-else-if="tasks.length" class="task-list">
                  <div v-for="task in tasks" :key="task.id" class="task-row">
                    <div class="task-row-info">
                      <div class="task-row-name">
                        <n-text strong>{{ task.filename }}</n-text>
                        <n-tag
                          :type="statusTypeMap[task.status] || 'default'"
                          size="small"
                          :bordered="false"
                        >
                          {{ statusTextMap[task.status] || task.status }}
                        </n-tag>
                        <n-tag v-if="task.tier" size="small" :bordered="false">
                          {{ tierTextMap[task.tier] || task.tier }}
                        </n-tag>
                      </div>
                      <div class="task-row-meta">
                        <span>{{ formatTime(task.created_at) }}</span>
                        <span v-if="task.status === 'in_progress'">
                          进度 {{ Math.round((task.progress ?? 0) * 100) }}%
                        </span>
                      </div>
                    </div>
                    <n-button size="small" type="primary" ghost @click="openTaskDetail(task)">
                      回看
                    </n-button>
                  </div>
                </div>
              </n-spin>
            </n-card>
          </section>

          <section class="page-section">
            <n-grid :cols="3" :x-gap="16" responsive="screen" item-responsive>
              <n-gi span="3 s:1 m:1" v-for="feature in [
                { title: '翻译', desc: '英文文献自动翻译为中文，忠实原文表达。' },
                { title: '结构保留排版', desc: '图表、标题、公式布局尽量贴近原文档。' },
                { title: '质检一条龙', desc: '翻译完成后提供质量检查与修订建议。' },
              ]" :key="feature.title">
                <n-card :title="feature.title" class="feature-card">
                  <n-text depth="3">{{ feature.desc }}</n-text>
                </n-card>
              </n-gi>
            </n-grid>
          </section>

          <section class="page-section status-row">
            <span>后端状态：</span>
            <n-tag :type="statusMeta[backendStatus].type" :bordered="false">
              {{ statusMeta[backendStatus].text }}
            </n-tag>
            <n-text v-if="backendStatus === 'ok' && taskCount !== null" depth="3" class="task-count">
              任务列表共 {{ taskCount }} 条
            </n-text>
          </section>
        </main>
      </n-layout-content>

      <n-layout-footer bordered class="page-footer">
        © 2026 docwise-web · 阶段 0 骨架 · Vue3 + Vite + Naive UI
      </n-layout-footer>
    </n-layout>

    <n-drawer v-model:show="drawerVisible" placement="right" :width="'min(720px, 100vw)'">
      <n-drawer-content>
        <template #header>
          <div class="drawer-title">
            <n-text strong>{{ detailTitle }}</n-text>
            <n-tag
              v-if="detailTask"
              :type="statusTypeMap[detailTask.status] || 'default'"
              :bordered="false"
            >
              {{ statusTextMap[detailTask.status] || detailTask.status }}
            </n-tag>
          </div>
        </template>

        <n-spin :show="detailLoading">
          <n-alert v-if="detailError" type="error" :show-icon="true" class="detail-error">
            {{ detailError }}
            <template #action>
              <n-button size="small" @click="fetchTaskDetail(detailTaskId)">
                重试
              </n-button>
            </template>
          </n-alert>

          <template v-else-if="detailTask">
            <div class="detail-meta">
              <span>创建时间：{{ formatTime(detailTask.created_at) }}</span>
              <span>档位：{{ tierTextMap[detailTask.tier] || detailTask.tier }}</span>
              <span v-if="detailTask.status === 'in_progress'">
                进度：{{ Math.round((detailTask.progress ?? 0) * 100) }}%
              </span>
            </div>

            <n-alert
              v-if="detailTask.status === 'failed' && detailTask.error_message"
              type="error"
              :show-icon="true"
              class="detail-error"
            >
              {{ detailTask.error_message }}
            </n-alert>

            <div class="block-section-title">
              <n-text strong>分块结果</n-text>
              <n-text depth="3" class="block-count">
                共 {{ detailTask.blocks?.length ?? 0 }} 块
              </n-text>
            </div>

            <n-empty
              v-if="!detailTask.blocks?.length"
              description="该任务暂无分块结果（任务尚未处理完成）"
              class="detail-empty"
            />

            <div v-else class="block-list">
              <div
                v-for="(block, index) in detailTask.blocks"
                :key="`${block.block_id}-${index}`"
                class="block-card"
              >
                <div class="block-card-head">
                  <n-text depth="3">{{ block.block_id }}</n-text>
                  <n-tag
                    :type="blockStatusMeta[block.status]?.type || 'default'"
                    size="small"
                    :bordered="false"
                  >
                    {{ blockStatusMeta[block.status]?.text || block.status }}
                  </n-tag>
                </div>
                <div class="block-pair">
                  <div class="block-side">
                    <div class="block-label">原文</div>
                    <div class="block-text">{{ block.text }}</div>
                  </div>
                  <div class="block-side">
                    <div class="block-label">译文</div>
                    <div class="block-text">{{ block.translated || '—' }}</div>
                  </div>
                </div>
                <n-alert
                  v-if="block.error"
                  type="error"
                  class="block-error"
                  :show-icon="true"
                >
                  {{ block.error }}
                </n-alert>
              </div>
            </div>
          </template>
        </n-spin>
      </n-drawer-content>
    </n-drawer>
  </n-config-provider>
</template>
