/**
 * 写作模板的**结构层** —— 纯数据 + 纯函数（无请求、无 DOM、无状态）。
 *
 * 为什么单独一个文件：模板的章节与提示要能被单测逐条钉住，而它们跟请求、跟组件生命周期
 * 都没有关系；放进 `WriteView.vue` 就只能在组件里"顺手 assert 一下"，改坏了没人拦得住。
 *
 * ⚠️ **一个模板只给"结构"，不给正文**（2026-10-19 用户取消"不代写"红线之后仍然是这条边界）：
 * 写进正文的是 `## 章节标题` + 一行 `<!-- 写作提示：… -->`，**没有一句成文的稿子**。
 * 正文由用户自己写，或由 AI 的写入通道（`apply-revision` / `ops`）填——那两条路都带撤销。
 *
 * 三个中文写作场景（都是 Markdown）：
 * ① `tpl-journal` 期刊论文；② `tpl-thesis` 学位论文；③ `tpl-report` 研究报告。
 *
 * 字段口径（`WriteView.vue` 的模板菜单与 `templateLabel()` 都读它）：
 * `{ id, name, note, sections: [{ heading, hint }] }`
 * - `id`：存进草稿的 `template_id`（契约 §2.7，`str(64)`）——**老的两个 id 不许改名**；
 * - `note`：菜单上那一行章节清单，与 `sections` 的标题逐条对应（有用例守着，别让它飘）；
 * - `hint`：**给写作者看的一句话提示**，进 `<!-- 写作提示：… -->`，不上屏。
 */

/** 三个内置模板。顺序就是菜单顺序（期刊论文排第一，最常用）。 */
export const WRITE_TEMPLATES = [
  {
    id: 'tpl-journal',
    name: '期刊论文',
    note: '题名 · 摘要 · 关键词 · 引言 · 方法 · 结果 · 讨论 · 结论 · 参考文献',
    sections: [
      {
        heading: '题名',
        hint: '研究对象 + 方法 + 最重要的结论，一句话说完；不写缩写，不用副标题补信息。',
      },
      {
        heading: '摘要',
        hint: '背景一句、方法一句、结果一句（带数字）、结论一句；不引文献，不写正文里没有的数据。',
      },
      {
        heading: '关键词',
        hint: '3 到 6 个名词，按学科习惯写；缩写只在全称已在本篇出现过时才用。',
      },
      {
        heading: '引言',
        hint: '这个问题为什么重要、别人做到哪一步、本文补上哪一块；最后一段可以先摆一句结论。',
      },
      {
        heading: '方法',
        hint: '数据或材料从哪来、怎么处理、判据与阈值各是什么；别人照这一步能不能重做出同一份结果。',
      },
      {
        heading: '结果',
        hint: '只报测到什么（数字、图表编号），解释留给讨论；每个数都要追得到一次实验或一份样本。',
      },
      {
        heading: '讨论',
        hint: '结果意味着什么、与已有研究一致还是相反、边界在哪（样本、场景、假设）。',
      },
      {
        heading: '结论',
        hint: '不超过三条，每条都能在结果里找到对应；不新增结果里没出现过的论点。',
      },
      {
        heading: '参考文献',
        hint: '按目标期刊的格式列全（作者、年份、题名、出处、DOI）；正文里的每个编号都要对得上一条。',
      },
    ],
  },
  {
    id: 'tpl-thesis',
    name: '学位论文',
    note: '绪论 · 相关工作 · 方法 · 实验 · 结论 · 参考文献',
    sections: [
      {
        heading: '绪论',
        hint: '研究背景、问题定义、研究意义、本文结构（每章一句话）；问题定义要能被后面的实验判对错。',
      },
      {
        heading: '相关工作',
        hint: '按问题分组，不按时间罗列；每组结尾写清与本文的差别在哪一条假设或哪一步做法上。',
      },
      {
        heading: '方法',
        hint: '先列假设与符号，再写模型或算法；关键步骤给公式编号，复杂度和成本一并写明。',
      },
      {
        heading: '实验',
        hint: '数据与基线、评价指标、主结果表、消融与失败案例；失败案例也要写，别只留跑通的那组。',
      },
      {
        heading: '结论',
        hint: '回答了绪论里的哪个问题、局限在哪、下一步做什么；不把「未来工作」写成已完成的成果。',
      },
      {
        heading: '参考文献',
        hint: '按本校学位论文格式（GB/T 7714）列；正文引用过的每一条都要在这里出现，反之亦然。',
      },
    ],
  },
  {
    id: 'tpl-report',
    name: '研究报告',
    note: '问题 · 背景 · 方法 · 发现 · 建议',
    sections: [
      {
        heading: '问题',
        hint: '一句话写清要回答什么，并给出「答上了没有」的判断标准；不要把三个问题塞进一段。',
      },
      {
        heading: '背景',
        hint: '谁遇到过这个问题、现有做法与它们的代价；只写与这个问题直接相关的部分。',
      },
      {
        heading: '方法',
        hint: '数据来源、样本量、时间范围、分析口径；口径一变结论就不成立的地方要当场写明。',
      },
      {
        heading: '发现',
        hint: '按重要性排，每条给数字或原话证据并标出处；推不出结论的地方写「判不出」，不硬下判断。',
      },
      {
        heading: '建议',
        hint: '每条建议对应上面哪一条发现、谁来做、多久能看到效果；没有发现支撑的建议不要写。',
      },
    ],
  },
]

/**
 * 按 id 取模板；**不认识就返回 `null`**（不编一个空模板出来骗调用方）。
 *
 * @param {string} id 模板标识（草稿上的 `template_id`）
 * @returns {{id: string, name: string, note: string, sections: {heading: string, hint: string}[]} | null}
 */
export function templateById(id) {
  const key = String(id ?? '')
  return WRITE_TEMPLATES.find((item) => item.id === key) || null
}

/**
 * 生成一份**结构骨架**（Markdown 源码），供"写入骨架"直接追加到正文。
 *
 * 输出形状（每个 section 两行 + 一个空行）：
 *
 * ```
 * # 题名（给了 title 才有这一行）
 *
 * ## 章节标题
 * <!-- 写作提示：一句话提示 -->
 * ```
 *
 * ⚠️ **只有标题行、提示行和空行**：一句成文的正文都没有（有用例逐行守着）。
 * 提示写成 HTML 注释，是为了让它**待在源码里、不出现在预览的版面上**——
 * 它是写给写作者自己看的，不是稿子的一部分。
 *
 * @param {string} id 模板标识
 * @param {{title?: string}} [options] `title` 非空时作为 `#` 一级标题写在最前面
 * @returns {string} Markdown 骨架；不认识的 id 返回空串
 */
export function buildSkeleton(id, { title } = {}) {
  const template = templateById(id)
  if (!template || !template.sections.length) return ''
  const lines = []
  // 标题只取一行：换行会把它拆成两行 markdown（第二行就不是标题了）
  const headline = String(title ?? '')
    .replace(/\s+/g, ' ')
    .trim()
  if (headline) lines.push(`# ${headline}`, '')
  for (const section of template.sections) {
    // ⚠️ 只写标题，**不写提示**：2026-10-19 用户明确否掉了把提示刻进正文
    //    （"感觉写了一堆文字刻上去而已"）。提示由界面在骨架栏里逐条列出。
    lines.push(`## ${section.heading}`)
    lines.push('')
  }
  return `${lines.join('\n').replace(/\n+$/, '')}\n`
}
