<template>
  <!-- ============ 弹层：文档信息 / 详情 / 问题反馈 / 删除确认 / 换档位重译 ============ -->
  <div v-if="panel" class="confirm-mask" @click.self="closePanel">
    <div class="card confirm-card" :class="{ wide: panel === 'blocks' }">
      <template v-if="panel === 'delete'">
        <h3>删除这篇论文？</h3>
        <p>
          「{{ panelTask && panelTask.filename }}」的结果文件与磁盘产物会一起清掉，不能恢复。
          只是想重来一遍的话，选「重试翻译（本档）」更稳。
        </p>
        <div class="confirm-ops">
          <button class="btn ghost" @click="closePanel">再想想</button>
          <button class="btn danger" :disabled="taskActionBusy" @click="deleteTask(panelTask)">确认删除</button>
        </div>
      </template>

      <template v-else-if="panel === 'retier'">
        <h3>换档位重译</h3>
        <p>
          会新建一个任务（原任务保留）。原稿不在结果产物里，所以需要你重新选一次这份 PDF。
        </p>
        <div class="confirm-list">
          <button
            v-for="tier in tierOptions"
            :key="tier.value"
            class="btn"
            @click="pickTierForRetranslate(tier.value)"
          >
            以「{{ tier.label }}」重译 —— {{ tier.note }}
          </button>
        </div>
        <div class="confirm-ops">
          <button class="btn ghost" @click="closePanel">取消</button>
        </div>
      </template>

      <template v-else-if="panel === 'feedback'">
        <h3>问题反馈</h3>
        <p>把下面这段复制给管理员即可——里面带着任务号，排查时能直接定位到这篇。</p>
        <div class="feedback-pre">{{ feedbackText }}</div>
        <div class="confirm-ops">
          <button class="btn ghost" @click="closePanel">关闭</button>
          <button class="btn primary" @click="copyFeedback">复制反馈信息</button>
        </div>
      </template>

      <template v-else-if="panel === 'info'">
        <h3>文档信息</h3>
        <div v-if="panelLoading" class="muted">正在读取…</div>
        <div v-else class="detail-meta">
          <div v-for="row in panelFactRows" :key="row.k"><b>{{ row.k }}</b>：{{ row.v }}</div>
        </div>
        <div class="confirm-ops">
          <button class="btn ghost" @click="closePanel">关闭</button>
        </div>
      </template>

      <template v-else>
        <h3>详情</h3>
        <div v-if="panelLoading" class="muted">正在读取…</div>
        <div v-else-if="taskDetailError" style="color: var(--danger)">{{ taskDetailError }}</div>
        <template v-else>
          <div class="detail-meta">
            <div v-for="row in panelFactRows" :key="row.k"><b>{{ row.k }}</b>：{{ row.v }}</div>
          </div>
          <div class="block-section-title">
            <b>分块处理状态</b>
            <span class="block-count muted">
              共 {{ panelData && panelData.blocks ? panelData.blocks.length : 0 }} 块（排查用；阅读请点「继续读」）
            </span>
          </div>
          <div
            v-if="!panelData || !panelData.blocks || !panelData.blocks.length"
            class="muted"
            style="padding: 24px 0; text-align: center"
          >
            该任务暂无分块结果（任务尚未处理完成）
          </div>
          <div v-else class="block-list">
            <div v-for="block in panelData.blocks" :key="block.block_id" class="block-card">
              <div class="block-card-head">
                <span class="muted">{{ block.block_id }}</span>
                <span
                  class="chip"
                  :class="block.status === 'success' ? 'ok' : block.status === 'failed' ? 'fail' : 'warn'"
                >
                  {{ block.status }}
                </span>
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
              <div v-if="block.error" class="block-error" style="color: var(--danger)">{{ block.error }}</div>
            </div>
          </div>
        </template>
        <div class="confirm-ops">
          <button class="btn ghost" @click="closePanel">关闭</button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
/**
 * 任务弹层：文档信息 / 分块详情 / 问题反馈 / 删除确认 / 换档位重译。
 *
 * **纯搬迁**：这五张卡的标记语言整段来自 `App.vue`，一个类名、一句文案都没改。
 * 它是外壳的一部分（遮罩盖住整屏、点外关闭），所以由 `App.vue` 挂载；
 * 状态与动作在 `stores/useLibrary`（`deleteTask` 要 `closePanel()`，放同一个模块里就没有接线）。
 */
import {
  closePanel,
  copyFeedback,
  deleteTask,
  feedbackText,
  panel,
  panelData,
  panelFactRows,
  panelLoading,
  panelTask,
  pickTierForRetranslate,
  taskActionBusy,
  tierOptions,
} from '../stores/useLibrary'
import { taskDetailError } from '../stores/useReader'
</script>
