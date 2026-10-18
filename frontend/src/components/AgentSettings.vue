<script setup>
/**
 * 设置弹窗：**自定义类配置**都收在这里（接口地址 / API Key / 强度 / 厂商 / 手填模型名）。
 *
 * 为什么单独一个弹窗：输入框旁边的按钮只该干一件事——**选模型**。
 * 把"填密钥、改地址、换厂商"塞进那个按钮，看起来就像把设置页糊在对话框上。
 * 这里照主流 agent 工具的做法：设置是独立入口、有分区，输入框旁边只有模型。
 */
import { computed, reactive, ref, watch } from 'vue'

import {
  agentConfig,
  agentScenes,
  agentSaveNote,
  agentSettingsOpen,
  openSettings,
  saveAgentConfig,
} from '../stores/useAgent'

const open = agentSettingsOpen
const config = agentConfig
const saveNote = agentSaveNote

const section = ref('model')
const saving = ref(false)
const form = reactive({ baseUrl: '', model: '', tier: 'standard', apiKey: '' })
const customModel = ref(false)

const scenes = agentScenes
const providers = computed(() => (config.value && config.value.providers) || [])
const keyHint = computed(() => (config.value && config.value.key_hint) || '')
const currentProvider = computed(() => {
  const base = form.baseUrl
  if (!base) return 'deepseek'
  const hit = providers.value.find((p) => p.base_url === base)
  return hit ? hit.id : 'local'
})

/** 当前厂商的预设模型（去重）+ 已保存的那个（否则下拉显示不出来）。 */
const modelOptions = computed(() => {
  const all = (config.value && config.value.tier_models) || {}
  const seen = new Set()
  for (const model of Object.values(all[currentProvider.value] || {})) {
    if (model) seen.add(model)
  }
  if (form.model) seen.add(form.model)
  return [...seen]
})

watch(modelOptions, (options) => {
  if (!form.model && options.length) form.model = options[0]
})

watch(
  [open, config],
  () => {
    if (!open.value) return
    const cfg = config.value || {}
    form.baseUrl = cfg.base_url || ''
    form.model = cfg.model || ''
    form.tier = cfg.tier || 'standard'
    form.apiKey = ''
    customModel.value = false
  },
  { immediate: true },
)

function pickProvider(id) {
  customModel.value = false
  const hit = providers.value.find((p) => p.id === id)
  if (!hit) return
  form.baseUrl = hit.base_url
  const tierModels = (config.value && config.value.tier_models) || {}
  const guess = (tierModels[id] || {})[form.tier]
  if (guess) form.model = guess
}

function pickModel(value) {
  if (value === '__custom') {
    customModel.value = true
    return
  }
  customModel.value = false
  form.model = value
}

async function save() {
  saving.value = true
  try {
    const ok = await saveAgentConfig({ ...form })
    if (ok) openSettings(false)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div v-if="open" class="agent-modal" @click.self="openSettings(false)">
    <div class="agent-modal-card" role="dialog" aria-label="设置">
      <aside class="agent-modal-nav">
        <div class="agent-modal-title">设置</div>
        <button
          type="button"
          :class="{ on: section === 'model' }"
          @click="section = 'model'"
        >
          模型
        </button>
        <button
          type="button"
          :class="{ on: section === 'ability' }"
          @click="section = 'ability'"
        >
          能力
        </button>
        <button type="button" disabled title="还没做">通用设置</button>
        <button type="button" disabled title="还没做">插件</button>
      </aside>

      <div class="agent-modal-body">
        <header>
          <b>{{ section === 'model' ? '模型' : '通用' }}</b>
          <button type="button" title="关闭" @click="openSettings(false)">×</button>
        </header>

        <p v-if="section === 'model'" class="agent-modal-hint">
          填入各厂商的 API 密钥即可使用其模型；密钥只写不读。
        </p>

        <!-- 能力：每个场景能用哪些工具（来自 /api/agent/scenes 的 tools） -->
        <div v-if="section === 'ability'" class="agent-ability">
          <p class="agent-modal-hint">
            下面是各场景**当前真正挂上的工具**（不是规划）。清单与
            <code class="agent-inline-code">docs/agent工具箱_20261018.md</code> 一一对应。
          </p>
          <div v-for="scene in scenes" :key="scene.id" class="agent-ability-block">
            <div class="agent-ability-head">
              <b>{{ scene.title }}</b>
              <span class="agent-ability-count">{{ (scene.tools || []).length }} 个工具</span>
            </div>
            <div class="agent-ability-chips">
              <span v-for="name in scene.tools || []" :key="name" class="agent-ability-chip">
                {{ name }}
              </span>
              <span v-if="!(scene.tools || []).length" class="agent-modal-hint">
                这个场景还没挂工具
              </span>
            </div>
          </div>
          <p v-if="!scenes.length" class="agent-modal-hint">场景还没加载到。</p>
        </div>

        <template v-if="section === 'model'">
        <label>
          <span>厂商</span>
          <select :value="currentProvider" @change="pickProvider($event.target.value)">
            <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </label>
        <label>
          <span>接口地址</span>
          <input v-model="form.baseUrl" type="text" placeholder="https://api.deepseek.com/v1" />
        </label>
        <label>
          <span>模型</span>
          <select :value="form.model" @change="pickModel($event.target.value)">
            <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
            <option value="__custom">自定义…</option>
          </select>
        </label>
        <label v-if="customModel">
          <span>手填模型名</span>
          <input v-model="form.model" type="text" placeholder="例如 deepseek-reasoner" />
        </label>
        <label>
          <span>强度</span>
          <select v-model="form.tier">
            <option value="fast">快（便宜，适合多轮查库）</option>
            <option value="standard">标准</option>
            <option value="strong">强（贵，复杂推理）</option>
          </select>
        </label>
        <label>
          <span>API Key</span>
          <input
            v-model="form.apiKey"
            type="password"
            :placeholder="keyHint || '留空 = 不动已保存的密钥'"
          />
        </label>

        <div class="agent-modal-ops">
          <span class="agent-note">{{ saveNote }}</span>
          <button class="btn primary sm" type="button" :disabled="saving" @click="save">
            保存
          </button>
        </div>
        </template>
      </div>
    </div>
  </div>
</template>
