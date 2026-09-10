/**
 * 诚实进度（F 批）的文案逻辑：与组件解耦，方便单测。
 *
 * 设计原则：**只翻译事实，不编数字**。
 * - 后端给什么就显示什么（`engine_progress` 来自引擎自己打的进度条）；
 * - 后端没给（`null`）就返回"引擎还在准备"，而不是造一个百分比；
 * - 时间类文案只在有意义时才出现（引擎自报 0 秒 = 精度不够，不显示；刚点下去不显示"已用 0 秒"）。
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

/** 引擎自报的分页进度（没有就返回 null，绝不编）。 */
export function engineText(engine) {
  if (!engine || typeof engine.done !== 'number' || !engine.total) return null
  const rate = engine.rate ? ` · ${engine.rate.toFixed(2)} 页/秒` : ''
  return `正在翻译 · 第 ${engine.done}/${engine.total} 页${rate}`
}

/** 阶段一行字：任务状态 +（有的话）引擎自报的页进度。 */
export function stageTextFor(task, engine) {
  if (!task) return ''
  switch (task.status) {
    case 'pending':
      return queueText(task)
    case 'in_progress':
      // 引擎还没打进度条时只说"还在准备"，不把内部实现细节端给用户
      return engineText(engine) || '正在翻译 · 引擎还在准备'
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
 */
export function etaTextFor(task, etaSeconds) {
  if (!task || task.status !== 'in_progress') return ''
  if (typeof etaSeconds !== 'number' || etaSeconds <= 0) return ''
  return `引擎预计还需 ${formatDuration(etaSeconds)}`
}
