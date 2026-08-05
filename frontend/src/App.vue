<script setup>
import { onMounted, ref } from 'vue'
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
  NText,
} from 'naive-ui'

const backendStatus = ref('checking')
const taskCount = ref(null)

const statusMeta = {
  checking: { type: 'default', text: '检测中…' },
  ok: { type: 'success', text: '已连接' },
  down: { type: 'error', text: '未连接（请先启动后端）' },
}

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

function handlePlaceholderUpload() {
  // 阶段 0 骨架：PDF 上传接口由后端负责人在后续阶段提供
}
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
                accept="application/pdf"
                :max="1"
                :default-upload="false"
                :custom-request="handlePlaceholderUpload"
              >
                <n-upload-dragger>
                  <div class="upload-hint">点击或拖拽 PDF 到此处</div>
                  <div class="upload-sub">阶段 0 骨架演示 · 翻译功能即将上线</div>
                </n-upload-dragger>
              </n-upload>
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
            <n-text v-if="backendStatus === 'ok'" depth="3" class="task-count">
              任务列表共 {{ taskCount ?? '?' }} 条
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
