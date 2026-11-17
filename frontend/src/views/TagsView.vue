<template>
  <!-- 标签（契约 N6）—— 2026-10-17 新开的一屏。
       与「集合」的区别要说清：集合是**容器**（一篇可以进多个），标签是**特征**
       （主题 / 方法 / 状态），两者都不复制文献。 -->
  <section class="kn">
    <header class="kn-top">
      <div>
        <h1 class="kn-t">标签</h1>
        <p class="kn-sub">
          按主题 / 方法 / 状态给文献打标记。<strong>一个标签可以贴在很多篇上</strong>，一篇也能有多个标签。
        </p>
      </div>
      <div class="kn-ops">
        <span class="kn-count">{{ countsText }}</span>
        <button type="button" class="btn ghost sm" @click="load">刷新</button>
      </div>
    </header>

    <p v-if="error" class="kn-note kn-note-err">{{ error }}</p>

    <ul v-if="tags.length" class="kn-list">
      <li v-for="item in tags" :key="item.name" class="card kn-row">
        <button type="button" class="kn-row-main" @click="openTag(item)">
          <span class="kn-name">{{ item.name }}</span>
          <span class="kn-num">{{ item.count ?? 0 }} 篇</span>
        </button>
        <span v-if="kindLabel(item.kind)" class="chip kn-kind">{{ kindLabel(item.kind) }}</span>
        <button
          type="button"
          class="btn ghost sm"
          :title="`删除标签「${item.name}」（文献不会被删）`"
          @click="removeTag(item)"
        >删除</button>
      </li>
    </ul>

    <div v-else-if="!loading" class="kn-empty">
      还没有标签。标签是在文献上加的（阅读页 / 详情里），加过之后这里就会出现；
      你点一个标签，就能筛出贴了它的那些文献。删除标签只移除标记，不会删文献。
    </div>

    <!-- 诚实说明：这一版**只有"看 + 筛"**，还没有"在这页新建标签 / 批量贴"。
         下一张卡再做（接口 N7 已经在，`PUT /api/tasks/{id}/tags` 是全量替换）。 -->
    <p class="kn-note kn-hint">
      <strong>贴标签</strong>在「历史记录」的卡片上直接做（点「＋ 标签」；再点一下标签就等于摘掉它）。
      这一页可以删标签（只移除标记，文献仍在）；改名仍不支持——标签按「名字 + 类型」唯一，改名等于合并。
    </p>
  </section>
</template>

<script setup>
/**
 * 标签整页（N6）。**只做"看 + 点进去筛"**，不做编辑——编辑牵扯"N7 是全量替换"，
 * 得配一个能显示当前标签的编辑面板（还差一个读接口），别在这版硬凑。
 */
import { computed, onMounted, ref } from 'vue'

import { apiJson } from '../auth'
import { navigate } from '../router'
import { loadTasksAndSync } from '../stores/useLibrary'
import { loadKnowledge, tags } from '../stores/useKnowledge'

const loading = ref(false)
const error = ref('')

const countsText = computed(() => (tags.value.length ? `${tags.value.length} 个标签` : '还没有标签'))

const KIND_LABEL = { topic: '主题', method: '方法', status: '状态' }

function kindLabel(kind) {
  return KIND_LABEL[kind] || ''
}

async function load() {
  loading.value = true
  error.value = ''
  await loadKnowledge()
  loading.value = false
}

onMounted(load)

/** 点标签 = 去历史记录按它筛（契约 N8 的 `tag[]`，多选由筛选条继续做）。 */
async function openTag(item) {
  await loadTasksAndSync({ tag: [item.name] })
  navigate('library')
}

/** 删标签：只清标记，不动文献；接口会一并清掉任务上的挂点。 */
async function removeTag(item) {
  if (!window.confirm(`删除标签「${item.name}」？文献不会被删，只是不再带这个标记。`)) return
  error.value = ''
  try {
    await apiJson(`/api/tags/${item.id}`, { method: 'DELETE' })
    await load()
  } catch (err) {
    error.value = `没删掉（${err?.message || '网络或服务异常'}）`
  }
}
</script>
