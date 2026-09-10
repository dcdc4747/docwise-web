<script setup>
import { onMounted, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NInput,
  NModal,
  NSpace,
  NText,
} from 'naive-ui'
import { apiJson } from '../auth'

const users = ref([])
const tasks = ref([])
const loading = ref(false)
const error = ref('')

const resetVisible = ref(false)
const resetTarget = ref(null)
const newPassword = ref('')
const resetError = ref('')

const statusText = {
  pending: '等待中',
  in_progress: '翻译中',
  completed: '已完成',
  failed: '失败',
}

const taskColumns = [
  { title: 'ID', key: 'id', width: 60 },
  { title: '文件名', key: 'filename', ellipsis: { tooltip: true } },
  { title: '所属账号', key: 'owner', width: 120 },
  {
    title: '状态',
    key: 'status',
    width: 90,
    render: (row) => statusText[row.status] || row.status,
  },
  { title: '档位', key: 'tier', width: 70 },
  {
    title: '创建时间',
    key: 'created_at',
    width: 140,
    render: (row) => (row.created_at || '—').replace('T', ' ').slice(0, 16),
  },
]

function formatTime(value) {
  return value ? value.replace('T', ' ').slice(0, 16) : '—'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [userList, taskList] = await Promise.all([
      apiJson('/api/admin/users'),
      apiJson('/api/admin/tasks?limit=200'),
    ])
    users.value = userList
    tasks.value = taskList
  } catch (err) {
    error.value = err.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function openReset(row) {
  resetTarget.value = row
  newPassword.value = ''
  resetError.value = ''
  resetVisible.value = true
}

async function submitReset() {
  if (newPassword.value.length < 8) {
    resetError.value = '密码至少 8 位'
    return
  }
  try {
    await apiJson(`/api/admin/users/${resetTarget.value.id}/password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_password: newPassword.value }),
    })
    resetVisible.value = false
  } catch (err) {
    resetError.value = err.message || '重置失败'
  }
}

async function toggleActive(row) {
  try {
    await apiJson(`/api/admin/users/${row.id}/active`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: !row.is_active }),
    })
    await load()
  } catch (err) {
    error.value = err.message || '操作失败'
  }
}

async function toggleRole(row) {
  try {
    await apiJson(`/api/admin/users/${row.id}/role`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role: row.role === 'admin' ? 'user' : 'admin' }),
    })
    await load()
  } catch (err) {
    error.value = err.message || '操作失败'
  }
}

onMounted(load)
</script>

<template>
  <div class="admin-page">
    <n-card class="admin-card">
      <template #header>
        <div class="admin-head">
          <span class="admin-title">管理后台</span>
          <n-text depth="3" class="admin-sub">账号、任务总览与维护操作</n-text>
        </div>
      </template>
      <template #header-extra>
        <n-button size="small" quaternary :loading="loading" @click="load">
          刷新
        </n-button>
      </template>

      <n-alert v-if="error" type="error" :show-icon="true" class="admin-error">
        {{ error }}
      </n-alert>

      <div class="admin-section-title">账号（{{ users.length }}）</div>
      <div class="admin-user-list">
        <div v-for="row in users" :key="row.id" class="admin-user-row">
          <div class="admin-user-info">
            <b>{{ row.username }}</b>
            <span class="admin-user-meta">
              {{ row.role === 'admin' ? '管理员' : '普通用户' }} ·
              {{ row.is_active ? '启用' : '已停用' }} ·
              论文 {{ row.task_count }} 篇 ·
              最后登录 {{ formatTime(row.last_login_at) }}
            </span>
          </div>
          <n-space size="small" class="admin-user-actions">
            <n-button size="tiny" quaternary @click="openReset(row)">
              重置密码
            </n-button>
            <n-button size="tiny" quaternary @click="toggleActive(row)">
              {{ row.is_active ? '停用' : '启用' }}
            </n-button>
            <n-button size="tiny" quaternary @click="toggleRole(row)">
              {{ row.role === 'admin' ? '降为用户' : '设为管理员' }}
            </n-button>
          </n-space>
        </div>
        <n-text v-if="!users.length" depth="3">暂无账号</n-text>
      </div>

      <div class="admin-section-title">全部任务（最近 {{ tasks.length }} 条）</div>
      <n-data-table
        :columns="taskColumns"
        :data="tasks"
        :bordered="false"
        size="small"
        :row-key="(row) => row.id"
      >
        <template #empty>
          <n-text depth="3">暂无任务</n-text>
        </template>
      </n-data-table>

      <template #footer>
        <n-text depth="3" class="admin-tip">
          管理员可查看全部账号与任务、重置密码、停用账号、调整角色；
          不能停用或降级自己（避免把后台锁死）。忘记密码也可用
          <code>backend/scripts/reset_password.py</code>。
        </n-text>
      </template>
    </n-card>

    <n-modal
      v-model:show="resetVisible"
      preset="card"
      title="重置密码"
      :style="{ width: '420px' }"
    >
      <n-space vertical>
        <n-text depth="3">
          为账号 {{ resetTarget && resetTarget.username }} 设置新密码
        </n-text>
        <n-input
          v-model:value="newPassword"
          type="password"
          show-password-on="click"
          placeholder="新密码（至少 8 位）"
        />
        <n-alert v-if="resetError" type="error" :show-icon="true">
          {{ resetError }}
        </n-alert>
      </n-space>
      <template #footer>
        <n-space justify="end">
          <n-button size="small" @click="resetVisible = false">取消</n-button>
          <n-button size="small" type="primary" @click="submitReset">确定</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>
