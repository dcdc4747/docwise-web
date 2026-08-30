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

let eventSource = null
let pollTimer = null

onMounted(async () => {
  try {
    const res = await fetch('/api/health')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    await res.json()
    backendStatus.value = 'ok'
    try {
      const tasksRes = await fetch('/api/tasks')
      if (tasksRes.ok) {
        const tasks = await tasksRes.json()
        taskCount.value = tasks.length
      }
    } catch {
      // 任务列表接口暂不可用时忽略
    }
  } catch {
    backendStatus.value = 'down'
  }
})

function progressPercent() {
  if (!currentTask.value) return 0
  return Math.round((currentTask.value.progress ?? 0) * 100)
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
  form.append('tier', 'fast')

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
                  <n-text strong>{{ currentTask.filename }}</n-text>
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
  </n-config-provider>
</template>
