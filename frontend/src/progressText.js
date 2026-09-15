/**
 * 诚实进度（F 批）的文案逻辑：与组件解耦，方便单测。
 *
 * 设计原则：**只翻译事实，不编数字**。
 * - 后端给什么就显示什么（`engine_progress` 来自引擎自己打的进度条）；
 * - 后端没给（`null`）就返回"引擎还没报进度"，而不是造一个百分比；
 * - 时间类文案只在有意义时才出现（引擎自报 0 秒 = 精度不够，不显示；刚点下去不显示"已用 0 秒"）；
 * - **秒数一律标来源**（「引擎自报还需约 25 秒」），不写「预计还需」。
 *
 * 这些值是模板里直接渲染的，所以**不要**在 App.vue 里改回普通函数：
 * 模板插值一个函数名（少写括号）会被 Vue `String(fn)` 把函数源码印到页面上
 * —— 这个事故真的发生过（见 PR #51 记录），因此这里的调用方一律用 computed。
 */

/** 排队中："前面还有几篇"（0 / undefined 时只说排队中）。 */
export function queueText(task) {
  const ahead = task?.queue_position
  return ahead ? `排队中 · 前面还有 ${ahead} 篇` : '排队中'
}

/**
 * 引擎自报的分页进度，写法与形态原型一致（`第 3/10 页`）。
 * **引擎没报就返回空串**，由调用方显示「引擎还没报进度」——绝不编一个页数出来。
 */
export function enginePageText(engine) {
  if (!engine || typeof engine.done !== 'number' || !engine.total) return ''
  return `第 ${engine.done}/${engine.total} 页`
}

/** 阶段一行字：任务状态（跑着的时候只说到"正在翻译"，页数交给 enginePageText）。 */
export function stageTextFor(task, engine) {
  if (!task) return ''
  switch (task.status) {
    case 'pending':
      return queueText(task)
    case 'in_progress':
      // 引擎还没打进度条时，只说"还在准备"，不把内部实现细节端给用户
      return enginePageText(engine) ? '正在翻译' : '正在翻译 · 引擎还没报进度'
    case 'completed':
      return '翻译完成'
    case 'cancelled':
      return '已取消'
    default:
      return '翻译失败'
  }
}

/** 把秒数说成人话（"45 秒" / "2 分 5 秒"）。 */
export function formatDuration(seconds) {
  const total = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  if (minutes <= 0) return `${rest} 秒`
  return `${minutes} 分 ${rest} 秒`
}

/**
 * 已耗时：跑着的时候叫"已用"，结束叫"总耗时"。
 * 刚点下去（不足 1 秒）不显示——"已用 0 秒"看着像坏了。
 */
export function elapsedTextFor(task, seconds) {
  if (!task) return ''
  const running = task.status === 'in_progress'
  if (!running) {
    if (typeof seconds !== 'number' || seconds <= 0) return ''
    return `总耗时 ${formatDuration(seconds)}`
  }
  if (typeof seconds !== 'number' || seconds < 1) return ''
  return `已用 ${formatDuration(seconds)}`
}

/**
 * 引擎自报的预计剩余。只在跑着、且引擎给了正数时显示
 * （tqdm 会四舍五入到 0，那不是"马上好"，只是精度不够）。
 * **必须带"引擎自报"与"约"**——这是引擎说的，不是我们的承诺。
 */
export function etaTextFor(task, etaSeconds) {
  if (!task || task.status !== 'in_progress') return ''
  if (typeof etaSeconds !== 'number' || etaSeconds <= 0) return ''
  return `引擎自报还需约 ${formatDuration(etaSeconds)}`
}

/** 把若干段文字拼成一行人话（空的段落直接丢掉，不留孤零零的分隔符）。 */
export function factLine(parts) {
  return (parts || []).filter((part) => part && String(part).trim()).join(' · ')
}

/**
 * L1「进行中任务条」那一行（形态原型：`正在翻译 · 第 3/10 页 · 已用 12 秒 · 引擎自报还需约 25 秒`）。
 * 每一段都来自真数据；引擎没报的段落自动不出现，不拿占位数字凑格式。
 */
export function runningLine(task, engine, elapsedSeconds) {
  return factLine([
    stageTextFor(task, engine),
    enginePageText(engine),
    elapsedTextFor(task, elapsedSeconds),
    etaTextFor(task, engine?.eta_seconds ?? task?.eta_seconds),
  ])
}

/**
 * 相对时间（照原型的"2 天前 / 昨天 / 上周"口径，纯展示用）。
 * 解析不了就返回空串——**不猜**。
 */
export function relativeTime(iso, now = Date.now()) {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (!Number.isFinite(then)) return ''
  const diff = now - then
  if (diff < 0) return '刚刚'
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days === 1) return '昨天'
  if (days < 7) return `${days} 天前`
  if (days < 14) return '上周'
  const date = new Date(then)
  const pad = (value) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}
