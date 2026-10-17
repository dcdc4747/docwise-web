<template>
  <div class="me-view">
    <header class="me-top">
      <span class="me-avatar" aria-hidden="true">{{ initial }}</span>
      <div class="me-top-text">
        <div class="me-top-name">{{ me?.display_name || me?.username || '（账号信息未取到）' }}</div>
        <div class="me-top-sub">{{ usernameText }} · {{ roleLabel }}</div>
      </div>
    </header>

    <!-- ============================ ① 身份 ============================ -->
    <section class="me-sec">
      <h2 class="me-sec-t">身份</h2>
      <HonestNote v-if="errors.me" :text="errors.me" />
      <div class="me-field">
        <label class="me-label" for="me-name">显示名</label>
        <input id="me-name" v-model="nameDraft" class="me-input" maxlength="64" placeholder="1–64 个字" />
        <button type="button" class="btn primary me-save" :disabled="!nameDirty || saving" @click="saveName">
          保存
        </button>
        <span v-if="nameHint" class="me-hint">{{ nameHint }}</span>
      </div>
      <dl class="me-facts">
        <div class="me-fact"><dt>用户名</dt><dd>{{ usernameText }}</dd></div>
        <div class="me-fact"><dt>角色</dt><dd>{{ roleLabel }}</dd></div>
        <div class="me-fact"><dt>上次登录</dt><dd>{{ lastLoginText }}</dd></div>
        <div class="me-fact"><dt>账号创建</dt><dd>{{ fmtTime(me?.created_at) }}</dd></div>
      </dl>
      <!-- ⭐ 有地基没盖房的那一处：字段在库里，接口还没带出来。缺就如实说，**不编一个时间** -->
      <HonestNote
        v-if="me && !me.last_login_at"
        text="上次登录暂未记录（后端 _serialize_user 还没带出 last_login_at，见契约 N30）—— 这里不编一个时间。"
      />
    </section>

    <!-- ========================= ② 账号安全 ========================= -->
    <section class="me-sec">
      <h2 class="me-sec-t">账号安全</h2>
      <div class="me-field">
        <label class="me-label" for="me-old">原密码</label>
        <input id="me-old" v-model="pwd.old" type="password" class="me-input" autocomplete="current-password" />
      </div>
      <div class="me-field">
        <label class="me-label" for="me-new">新密码</label>
        <input id="me-new" v-model="pwd.next" type="password" class="me-input" autocomplete="new-password" />
        <span class="me-hint">8–128 位</span>
      </div>
      <div class="me-field">
        <label class="me-label" for="me-repeat">确认新密码</label>
        <input id="me-repeat" v-model="pwd.repeat" type="password" class="me-input" autocomplete="new-password" />
        <button type="button" class="btn primary me-pwd" :disabled="!canChangePassword" @click="changePassword">
          改密码
        </button>
        <span v-if="pwdHint" class="me-hint">{{ pwdHint }}</span>
      </div>
      <HonestNote
        text="改密码不会踢掉其他设备上已登录的会话（有意为之，契约 §1.2 第 2 条）—— 要清设备请用下面的会话列表逐个吊销。"
      />

      <h3 class="me-sub-t">登录设备与会话</h3>
      <!-- ⭐ 2026-10-18：会话以前**只增不减**（每登录一次一条、30 天过期），
           实测一个账号攒到 132 条、页面一屏放不下。后端现在按用户封顶 20 条，
           这里把"一共几台"和"只显示最近的"说清楚，免得以为丢了设备。 -->
      <p v-if="sessions.length" class="me-line me-sessions-sum">
        共 {{ sessionsTotal }} 台设备在线<template v-if="sessionsTotal > sessions.length"
          >，下面只显示最近 {{ sessions.length }} 台</template
        >。标着<b>本机</b>的那条是<b>你现在用的这个浏览器</b>。
      </p>
      <HonestNote v-if="errors.sessions" :text="errors.sessions" />
      <table v-else-if="sessions.length" class="me-table me-sessions">
        <thead>
          <tr>
            <th scope="col">设备</th>
            <th scope="col">登录时间</th>
            <th scope="col">最近活动</th>
            <th scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in sessions" :key="item.id" :class="{ 'me-this': item.current }">
            <td>
              <span class="me-dev">{{ item.user_agent || '未知设备' }}</span>
              <span v-if="item.current" class="me-chip-now">本机</span>
            </td>
            <td class="me-when">{{ fmtShort(item.created_at) }}</td>
            <td class="me-when">{{ fmtShort(item.last_seen_at) }}</td>
            <td>
              <button
                type="button"
                class="btn me-kill"
                :title="item.current ? '吊销这一条 = 退出当前浏览器登录' : '让那台设备立刻下线'"
                @click="revoke(item.id)"
              >
                {{ item.current ? '退出这台' : '吊销' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="me-line">当前没有可吊销的登录会话。</p>
    </section>

    <!-- ========================= ③ 我的数据 ========================= -->
    <section class="me-sec">
      <h2 class="me-sec-t">我的数据</h2>
      <HonestNote v-if="errors.storage" :text="errors.storage" />
      <template v-else-if="storage">
        <p class="me-line">共占用 {{ fmtBytes(storage.total_bytes) }} · 位置 {{ storage.location || '—' }}</p>
        <!-- ⭐ 条形图**必须带文字明细**：只有色块等于什么都没说 -->
        <ul class="me-kinds">
          <li v-for="row in kindRows" :key="row.key" class="me-kind">
            <span class="me-kind-name">{{ row.label }}</span>
            <span class="me-kind-bar" aria-hidden="true">
              <span class="me-kind-fill" :style="{ width: `${row.percent}%` }"></span>
            </span>
            <span class="me-kind-num">{{ row.text }}</span>
          </li>
        </ul>
      </template>
      <div class="me-ops">
        <button type="button" class="btn primary me-export" @click="download('/api/me/export?format=zip', 'docwise-export.zip')">
          一键导出全部数据（zip）
        </button>
        <button type="button" class="btn me-export-md" @click="download('/api/me/export?format=md', 'docwise-export.md')">
          导出为 Markdown
        </button>
        <span v-if="downloadHint" class="me-hint">{{ downloadHint }}</span>
      </div>
      <p class="me-line">
        备份：由 <code>backend/scripts/backup_db.py</code> 用 <code>VACUUM INTO</code> 生成、只保留最近 N 份{{
          backupText
        }}。
      </p>
    </section>

    <!-- ======================= ④ AI 使用台账 ======================= -->
    <section class="me-sec">
      <h2 class="me-sec-t">AI 使用台账</h2>
      <HonestNote v-if="errors.ledger" :text="errors.ledger" />
      <table v-else-if="ledger.length" class="me-table me-ledger">
        <thead>
          <tr>
            <th scope="col">环节</th>
            <th scope="col">走了什么</th>
            <th scope="col">工具</th>
            <th scope="col">产出</th>
            <th scope="col">时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ledger" :key="row.id">
            <td>{{ stageText(row.stage) }}</td>
            <td>
              <span class="me-flow" :class="row.actor === 'api' ? 'is-api' : 'is-local'">{{ actorText(row.actor) }}</span>
            </td>
            <td>{{ row.tool || '—' }}</td>
            <td>{{ row.summary || '—' }}</td>
            <td>{{ fmtTime(row.created_at) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="me-line">还没有环节记录：跑过一次上传 / 导读 / 问答之后，这里会逐条列出每一步。</p>
      <div class="me-ops">
        <button type="button" class="btn me-ledger-csv" @click="download('/api/me/ledger?format=csv', 'docwise-ledger.csv')">
          导出 CSV
        </button>
        <button type="button" class="btn me-ledger-md" @click="download('/api/me/ledger?format=md', 'docwise-ledger.md')">
          导出 Markdown
        </button>
      </div>
      <!-- ⭐ 诚实档：'哪些块被人改过' 依赖块编辑事件（M2 布点之后才有数据）→ 现在就是没有 -->
      <HonestNote text="人改记录：暂无人改记录（哪些块被人改过依赖块编辑事件，要 M2 布点之后才有数据）—— 不硬编。" />
      <HonestNote
        text="口径：服务自持 + 文献存本地；外文翻译、扫描件逐段翻译、导读与问答四处仍会调用云端模型 API（「走了什么」那一列就是逐条的机器证据）。"
      />
    </section>

    <!-- ========================== ⑤ 偏好 ========================== -->
    <section class="me-sec">
      <h2 class="me-sec-t">偏好</h2>
      <div class="me-field">
        <label class="me-label" for="me-view-def">默认读法</label>
        <select id="me-view-def" v-model="prefs.defaultView" class="me-input">
          <option v-for="item in VIEW_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </div>
      <fieldset class="me-field me-fieldset">
        <legend class="me-label">翻译档位</legend>
        <label v-for="item in TIER_OPTIONS" :key="item.value" class="me-radio">
          <input v-model="prefs.tier" type="radio" :value="item.value" />
          {{ item.label }}
        </label>
      </fieldset>
      <div class="me-field">
        <label class="me-label" for="me-fs">阅读字号</label>
        <select id="me-fs" v-model="prefs.readingSize" class="me-input">
          <option v-for="item in SIZE_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
        <span class="me-hint">只乘正文 / 译文，不缩放界面（`--fs-scale` 的既有口径）</span>
      </div>
      <label class="me-check">
        <input v-model="prefs.reducedMotion" type="checkbox" />
        动效跟随系统（系统开了"减少动态效果"就不要再动）
      </label>
      <HonestNote text="偏好存在服务端（跟着账号走，换设备也在）；本机留一份缓存，断网时照旧生效。" />
      <HonestNote v-if="prefsError" class="me-prefs-sync" :text="prefsError" />
    </section>

    <!-- ==================== ⑥ 管理 · 危险区 ==================== -->
    <section class="me-sec">
      <h2 class="me-sec-t">管理 · 危险区</h2>
      <div v-if="isAdmin" class="me-field">
        <span class="me-label">管理后台</span>
        <a class="btn me-admin-link" href="#/admin">打开管理后台（仅管理员可见）</a>
      </div>
      <p v-else class="me-line">当前账号不是管理员，管理入口不显示。</p>

      <div class="me-danger">
        <h3 class="me-sub-t">删除账号与全部数据</h3>
        <!-- 危险区三件套之一：**说清不可恢复** -->
        <p class="me-danger-text">
          这会删除你的账号、全部文献与产物、素材卡、草稿、引用与台账记录，
          <strong>且无法恢复</strong>。
        </p>
        <!-- 三件套之二：**引导先导出** -->
        <div class="me-ops">
          <button type="button" class="btn me-export-first" @click="download('/api/me/export?format=zip', 'docwise-export.zip')">
            先导出全部数据
          </button>
        </div>
        <!-- 三件套之三：**二次确认**（勾选 + 亲手打一遍用户名，缺一个都不给点） -->
        <label class="me-check">
          <input v-model="confirm.ack" type="checkbox" />
          我明白：删除后无法恢复
        </label>
        <div class="me-field">
          <label class="me-label" for="me-confirm-name">输入用户名确认</label>
          <input id="me-confirm-name" v-model="confirm.name" class="me-input" :placeholder="usernameText" />
          <button type="button" class="btn me-delete" :disabled="!canDelete" @click="deleteAccount">
            删除账号与全部数据
          </button>
        </div>
        <span v-if="deleteHint" class="me-hint">{{ deleteHint }}</span>
      </div>
    </section>
  </div>
</template>

<script setup>
/**
 * 个人中心（整页，issue #112 / 任务卡：卡④）。
 *
 * 六个区块：**身份 · 账号安全 · 我的数据 · AI 使用台账 · 偏好 · 管理/危险区**。
 * ⚠️ 本页**自己不加路由**（`#/me` 由外壳负责人挂），也不改 `App.vue` / 别人的 `style.css` 段。
 *
 * 四条纪律（都是这个项目里已经吃过亏的地方）：
 * ① **能取到的取，取不到就说**：四个 `me/*` 请求各自 `try/catch`，
 *    某一块挂了**只让那一块显示原因**，不许整页白屏、也不许拿假数据顶上；
 * ② ⭐ **不编时间、不编数**：`last_login_at` 现在还没带出来（契约 N30）就写"暂未记录"，
 *    **不拿 `created_at` 冒充"上次登录"**；
 * ③ ⭐ **危险区三件套一个都不能少**：说清不可恢复 + 引导先导出 + 二次确认（勾选 **且** 手打用户名）；
 * ④ **口径照全站红线**：`actor` 那一列是"数据流向"的机器证据 —— 说"服务自持 + 文献存本地"，
 *    **不说"数据不出本机"**（外文翻译 / 扫描件逐段翻译 / 导读 / 问答四处仍调云端模型 API）。
 */
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'

import { apiJson, authFetch, clearToken } from '../auth'
import { actorText, stageText } from '../ledgerText'
import HonestNote from '../components/HonestNote.vue'
import { loadPrefs, prefsError, readLocalPrefs, savePrefs } from '../stores/usePrefs'

// ---------------------------------------------------------------- 取数
const me = ref(null)
const storage = ref(null)
const sessions = ref([])
/** 还能用的会话一共几台（`items` 只有最近 20 条） */
const sessionsTotal = ref(0)
const ledger = ref([])
const errors = reactive({ me: '', storage: '', sessions: '', ledger: '' })

/** 每一块单独收错误：一块挂了不影响别的块，也不许把整页变成白屏。 */
async function loadBlock(key, path, apply) {
  try {
    const data = await apiJson(path)
    apply(data)
    errors[key] = ''
  } catch (error) {
    errors[key] = `${BLOCK_TITLE[key]}暂时取不到（${error.message}）—— 这一块先空着，不拿假数据顶。`
  }
}

const BLOCK_TITLE = {
  me: '身份',
  storage: '我的数据',
  sessions: '登录设备与会话',
  ledger: 'AI 使用台账',
}

async function load() {
  await Promise.all([
    loadBlock('me', '/api/auth/me', (data) => {
      me.value = data
      nameDraft.value = data?.display_name ?? ''
    }),
    loadBlock('storage', '/api/me/storage', (data) => {
      storage.value = data
    }),
    loadBlock('sessions', '/api/me/sessions', (data) => {
      sessions.value = Array.isArray(data?.items) ? data.items : []
      // `total` 是"还能用的会话一共几台"（列表只回最近 20 条）；旧后端没这个字段时退回条数
      sessionsTotal.value = Number.isFinite(data?.total) ? data.total : sessions.value.length
    }),
    loadBlock('ledger', '/api/me/ledger', (data) => {
      ledger.value = Array.isArray(data?.items) ? data.items : []
    }),
    // ⭐ 偏好单独走一条：它不是"取回来显示"就完了，还要**反写本机缓存**
    //    （阅读页同步读缓存），失败也只影响这一块（`prefsError` 自己会说）
    syncPrefs(),
  ])
}

onMounted(load)

// ---------------------------------------------------------------- ① 身份
const nameDraft = ref('')
const saving = ref(false)
const nameHint = ref('')

const usernameText = computed(() => me.value?.username || '—')
const roleLabel = computed(() => (me.value?.role === 'admin' ? '管理员' : me.value?.role ? '普通用户' : '—'))
const initial = computed(() => {
  const source = me.value?.display_name || me.value?.username || '?'
  return String(source).trim().slice(0, 1).toUpperCase()
})
const isAdmin = computed(() => me.value?.role === 'admin')
const lastLoginText = computed(() => (me.value?.last_login_at ? fmtTime(me.value.last_login_at) : '暂未记录'))
const nameDirty = computed(() => nameDraft.value.trim() !== (me.value?.display_name ?? ''))

async function saveName() {
  const next = nameDraft.value.trim()
  if (!next) {
    nameHint.value = '显示名不能是空的（1–64 个字）'
    return
  }
  saving.value = true
  nameHint.value = ''
  try {
    const updated = await apiJson('/api/me', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ display_name: next }),
    })
    me.value = { ...me.value, ...updated }
    nameDraft.value = me.value.display_name ?? next
    nameHint.value = '已保存'
  } catch (error) {
    nameHint.value = `没保存成功（${error.message}）`
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------- ② 账号安全
const pwd = reactive({ old: '', next: '', repeat: '' })
const pwdHint = ref('')

const canChangePassword = computed(
  () => pwd.old.length > 0 && pwd.next.length >= 8 && pwd.next === pwd.repeat,
)

async function changePassword() {
  pwdHint.value = ''
  try {
    await apiJson('/api/auth/password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ old_password: pwd.old, new_password: pwd.next }),
    })
    pwdHint.value = '密码已更新（其他设备上的会话仍然有效）'
    pwd.old = ''
    pwd.next = ''
    pwd.repeat = ''
  } catch (error) {
    pwdHint.value = `没改成（${error.message}）`
  }
}

async function revoke(id) {
  try {
    await apiJson(`/api/me/sessions/${id}`, { method: 'DELETE' })
    sessions.value = sessions.value.filter((item) => item.id !== id)
  } catch (error) {
    errors.sessions = `吊销失败（${error.message}）`
  }
}

// ---------------------------------------------------------------- ③ 我的数据
const KIND_LABELS = {
  uploads: '上传的原始文献',
  outputs: '产物（译稿 / 导出）',
  backups: '数据库备份',
  db: '数据库本体',
}

const kindRows = computed(() => {
  const by = storage.value?.by_kind || {}
  const total = Math.max(1, Number(storage.value?.total_bytes) || 0)
  return Object.entries(KIND_LABELS).map(([key, label]) => {
    const bytes = Number(by[key]) || 0
    return { key, label, text: fmtBytes(bytes), percent: Math.round((bytes / total) * 100) }
  })
})

const backupText = computed(() => {
  const size = storage.value?.by_kind?.backups
  return Number.isFinite(size) ? `（当前 ${fmtBytes(size)}）` : ''
})

const downloadHint = ref('')

/** 导出 / 备份下载：请求带令牌 → 落成 Blob → 触发一次浏览器下载（`<a>` 带不了请求头）。 */
async function download(path, filename) {
  downloadHint.value = ''
  try {
    const response = await authFetch(path)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    downloadHint.value = `已开始下载 ${filename}`
  } catch (error) {
    downloadHint.value = `导出失败（${error.message}）`
  }
}

// ---------------------------------------------------------------- ④ 台账
// ⚠️ 环节与流向的文案映射**不在本文件**：`ledgerText.js` 是全站唯一一份，
// 「处理过程」一屏（`ProcessView.vue`）读的是**同一张表**，两边必须一个说法。

// ---------------------------------------------------------------- ⑤ 偏好
/**
 * ⚠️ 只有四个值对得上阅读区的模式：`blocks`（段落精读）/ `mono` / `dual`。
 * 早先那个 `pdf`（原版）**已经去掉了** —— v2 的阅读区没有"原版 iframe"这个模式了
 * （PDF 走 `mono` / `dual` 两档，见 `stores/useReader.js` 的 `docModeOptions`），
 * 留着它等于给用户一个**选了不生效**的选项。外壳消费这一项时按同名映射，不认识的回落段落精读。
 */
const VIEW_OPTIONS = [
  { value: 'blocks', label: '段落精读' },
  { value: 'mono', label: '纯中文' },
  { value: 'dual', label: '双语对照' },
]

/** ⚠️ **只有快 / 中两档**：精档已从界面撤下（它一直映射到中档，写着"最准"属不实宣称）。 */
const TIER_OPTIONS = [
  { value: 'fast', label: '快档 · 最快' },
  { value: 'medium', label: '中档 · 平衡' },
]

const SIZE_OPTIONS = [
  { value: 'small', label: '小' },
  { value: 'normal', label: '标准' },
  { value: 'large', label: '大' },
]

/**
 * 偏好（N40/N41）：**服务端权威、本机 `localStorage` 只是缓存**。
 *
 * 两个方向都要走通：
 * - 进来时先按缓存铺（阅读页要**同步**读，等不了网络），再跟服务端对一次（`loadPrefs`）；
 * - 改了以后**先落缓存再推服务端**（`savePrefs`），推失败如实报一句（换设备带不上）。
 *
 * ⚠️ `prefsSyncing` 是必须的：`Object.assign` 回填服务端那份时 watcher 会响一次，
 * 不挡住就会立刻把刚取回来的东西又 PUT 一遍（多余请求，而且容易与迁移那条路打架）。
 */
const prefs = reactive(readLocalPrefs())
let prefsSyncing = false

watch(
  prefs,
  (value) => {
    if (prefsSyncing) return
    savePrefs({ ...value })
  },
  { deep: true },
)

async function syncPrefs() {
  prefsSyncing = true
  await loadPrefs()
  Object.assign(prefs, readLocalPrefs())
  await nextTick()
  prefsSyncing = false
}

// ---------------------------------------------------------------- ⑥ 危险区
const confirm = reactive({ ack: false, name: '' })
const deleting = ref(false)
const deleteHint = ref('')

const canDelete = computed(
  () => confirm.ack && Boolean(me.value?.username) && confirm.name.trim() === me.value.username && !deleting.value,
)

async function deleteAccount() {
  deleting.value = true
  deleteHint.value = ''
  try {
    await apiJson('/api/me', { method: 'DELETE' })
    clearToken()
    deleteHint.value = '账号已删除，本机令牌已清除 —— 刷新后会回到登录页。'
    me.value = null
    sessions.value = []
    ledger.value = []
    storage.value = null
  } catch (error) {
    deleteHint.value = `没删成功（${error.message}）`
  } finally {
    deleting.value = false
  }
}

// ---------------------------------------------------------------- 格式化
function fmtTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * 会话表里的时间：**一行放得下**。
 *
 * ⚠️ 用 `fmtTime` 会在 100px 宽的列里折成两行（"2026/10/18" + "00:03"），
 * 四列都折 → 整张表挤到溢出卡片（用户截图里就是这样）。
 * 会话只关心"哪台、什么时候"，**当年不写年份**（跨年时日期本身看得出来）。
 */
function fmtShort(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (n) => String(n).padStart(2, '0')
  // ⚠️ 不写年份：会话最长 30 天就走完，年份是噪音；而 14 个字的宽度在 5 列布局里会溢出撞到下一列。
  return `${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function fmtBytes(value) {
  const size = Number(value)
  if (!Number.isFinite(size)) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let rest = size
  let index = 0
  while (rest >= 1024 && index < units.length - 1) {
    rest /= 1024
    index += 1
  }
  return `${index === 0 ? rest : rest.toFixed(1)} ${units[index]}`
}
</script>
