/**
 * 环节台账的文案映射（**全站唯一一份**）。
 *
 * 为什么抽出来：`MeView`（「AI 使用台账」表）与 `ProcessView`（「处理过程」一屏）看的是
 * **同一张表**（契约 §2.5：N17 与 N26 同源），措辞要是各写一份，迟早出现"同一件事两个说法"。
 *
 * ⚠️ `actor` 的两套文案**不是重复**，是两个场景，别合并：
 * - `actorText()`：表格里那一列「走了什么」的**短标签**（列窄，放不下长句）；
 * - `actorChip()`：**数据模型契约 §2.8 的映射表逐字写死**的芯片文案
 *   （`● 不出本机` / `▲ 正文发往模型 API`）——**照抄，不许改**。
 *
 * 这一列为什么重要：`actor` 是**"数据流向"的证据**。`api` 意味着正文真的发往了云端模型 API，
 * 所以对外口径只能是「服务自持 + 文献存本地」，**不能说"数据不出本机"**。
 */

/** 环节 → 人话（表头那一列的取值，`stage` 就是台账表的"行标题"，契约 §2.8）。 */
export const STAGE_TEXT = {
  extract: '取字',
  ocr: '扫描件 OCR',
  translate: '逐段翻译',
  understanding: '导读 / 术语',
  ask: '问答',
  check: '收口检查',
  cite: '引文',
  edit: '译文编辑',
}

/** 环节人话；认不出的阶段**原样显示**（不编、不吞）。 */
export function stageText(stage) {
  if (!stage) return '—'
  return STAGE_TEXT[stage] ? `${STAGE_TEXT[stage]}` : String(stage)
}

/** 表格里的短标签（列窄）。 */
export function actorText(actor) {
  if (actor === 'local') return '本地处理'
  if (actor === 'api') return '发往模型 API'
  if (actor === 'user') return '你（人工）'
  return actor ? String(actor) : '—'
}

/**
 * 数据流向芯片（契约 §2.8 映射表**逐字**：`● 不出本机` / `▲ 正文发往模型 API`）。
 *
 * ⚠️ 这两个字符串是**证据的一部分**，不是装饰：改一个字符就等于改了对外口径。
 */
export function actorChip(actor) {
  if (actor === 'local') return '● 不出本机'
  if (actor === 'api') return '▲ 正文发往模型 API'
  if (actor === 'user') return '● 你（人工）'
  return actor ? String(actor) : '—'
}

/** 芯片的样式类：只有 `api` 才算"发出去了"（`user`/未知一律按本机侧显示，别夸大）。 */
export function actorFlowClass(actor) {
  return actor === 'api' ? 'is-api' : 'is-local'
}
