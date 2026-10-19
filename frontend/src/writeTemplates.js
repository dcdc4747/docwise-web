/**
 * 写作模板的**结构层** —— 纯数据 + 纯函数（无请求、无 DOM、无状态）。
 *
 * 为什么单独一个文件：模板的章节与提示要能被单测逐条钉住，而它们跟请求、跟组件生命周期
 * 都没有关系；放进 `WriteView.vue` 就只能在组件里"顺手 assert 一下"，改坏了没人拦得住。
 *
 * ⚠️ **一个模板只给"结构"，不给正文**：写进正文的只有 `## 章节标题`，
 * **不塞任何提示文字**（2026-10-19 用户明确否掉了把提示刻进正文的做法）。
 * 写作要点在界面上按节列出，正文由用户自己写，或由 AI 的写入通道（`ops`）填。
 *
 * ─────────────────────────────────────────────────────────────
 * 2026-10-19 按**真实投稿规范**重写（上一版被用户质疑"离谱"，核对后确实有问题）：
 * ① 旧版把「题名」当成正文的一节 —— 题名是**篇首信息**，不是小节；
 * ② 旧版只有一种 IMRaD —— 但 IEEE 会议要 Index Terms + 罗马数字节号，
 *    APA 风格的英文期刊引言**不带标题**，Nature 系 Methods 放在参考文献之后；
 * ③ 旧版中文期刊缺 中图分类号 / 英文摘要 —— 缺一个就会被编辑退回；
 * ④ 旧版学位论文缺 中英文摘要 / 目录 / 致谢 / 附录。
 *
 * 现在给**五个真实体例**（依据见 `docs/写作模板依据_20261019.md`）：
 *  - `tpl-journal`  中文期刊论文（GB/T 7714 顺序编码制）
 *  - `tpl-en-journal` 英文期刊论文（IMRaD / APA 7）
 *  - `tpl-ieee`     IEEE 会议论文（Index Terms + 罗马数字节号 + 单数 Acknowledgment）
 *  - `tpl-thesis`   学位论文（中文，含中英文摘要/目录/致谢/附录）
 *  - `tpl-report`   研究报告（内部报告，非投稿体例）
 *
 * ⚠️ 边界：模板只给**章节结构与写作要点**，**不实现**各刊版式
 * （页边距/字号/行距/栏数/图表格式）——那要用各刊自己的 Word/LaTeX 模板。
 *
 * 字段口径（`WriteView.vue` 的模板菜单与 `templateLabel()` 都读它）：
 * `{ id, name, note, style, sections: [{ heading, hint }] }`
 * - `id`：存进草稿的 `template_id`（契约 §2.7，`str(64)`）——`tpl-journal` / `tpl-thesis`
 *   两个老 id **不许改名**（老稿子里存着它们）；
 * - `note`：菜单上那一行章节清单，与 `sections` 的标题逐条对应（有用例守着）；
 * - `style`：该体例默认的参考文献样式提示（给用户看的，不做自动排版）；
 * - `hint`：给写作者看的一句话要点，**只在界面显示**，不进正文。
 */

/** 五个内置模板。顺序就是菜单顺序（中文期刊最常用，排第一）。 */
export const WRITE_TEMPLATES = [
  {
    id: 'tpl-journal',
    name: '中文期刊论文',
    note: '中文摘要 · 关键词 · 中图分类号 · 英文摘要与关键词 · 引言 · 材料与方法 · 结果与分析 · 讨论 · 结论 · 参考文献',
    style: 'GB/T 7714（顺序编码制）',
    sections: [
      {
        heading: '中文摘要',
        hint: '200–300 字，目的—方法—结果—结论四句话；不引文献、不写"本文首次"这类空话，数字与正文一致。',
      },
      {
        heading: '关键词',
        hint: '3–8 个，从题名与摘要里选；学科通用词优先，不用自造缩略语。',
      },
      {
        heading: '中图分类号',
        hint: '按《中国图书馆分类法》给 1–2 个（如 TP391.1）；不确定就查同刊近期文章的写法。',
      },
      {
        heading: '英文摘要与关键词',
        hint: '与中文摘要逐句对应，不另写内容；英文题名、作者拼音、单位按期刊格式给。',
      },
      {
        heading: '引言',
        hint: '研究背景与意义、国内外现状（引用要落到具体工作）、本文要解决的问题与创新点、全文结构。',
      },
      {
        heading: '材料与方法',
        hint: '数据来源、样本量、仪器或算法、评价指标；判据与阈值写清楚，让别人能重做。',
      },
      {
        heading: '结果与分析',
        hint: '只报测到什么（图表编号 + 数字），解释放讨论；每个数要能追到一次实验或一份样本。',
      },
      {
        heading: '讨论',
        hint: '结果意味着什么、与已有研究一致还是相反、边界在哪（样本、场景、假设）、局限。',
      },
      {
        heading: '结论',
        hint: '2–3 条，每条都能在结果里找到对应；不引入结果里没出现过的论点。',
      },
      {
        heading: '参考文献',
        hint: 'GB/T 7714 顺序编码制：正文按出现顺序编号 [1][2]…，文后一一对应（作者. 题名[J]. 刊名, 年, 卷(期): 页码.）。',
      },
    ],
  },
  {
    id: 'tpl-en-journal',
    name: '英文期刊论文',
    note: 'Abstract · Keywords · Introduction · Method · Results · Discussion · Conclusion · References',
    style: 'APA 7（作者—年份）',
    sections: [
      {
        heading: 'Abstract',
        hint: '≤250 words (APA 7), one paragraph, no citations: aim, method, key results, conclusion.',
      },
      {
        heading: 'Keywords',
        hint: '3–6 terms, lowercase except proper nouns; prefer the journal thesaurus terms.',
      },
      {
        heading: 'Introduction',
        hint: 'APA 正文里引言**不加节标题**（这一行只为让你有落笔处）：问题、已有工作、缺口、目的与假设。',
      },
      {
        heading: 'Method',
        hint: 'Participants / Materials / Procedure 三个子块；样本、工具、流程、分析策略写全到可复制。',
      },
      {
        heading: 'Results',
        hint: '只报结果与统计量（M, SD, p, effect size）；图表各自独立可读，不与正文重复叙述。',
      },
      {
        heading: 'Discussion',
        hint: '解释结果、与文献对话、理论与实践含义、局限与未来方向；不要把结论重复一遍。',
      },
      {
        heading: 'Conclusion',
        hint: '一段话收口：回答了什么、边界在哪；有的刊要求并入 Discussion，按目标刊定。',
      },
      {
        heading: 'References',
        hint: 'APA 7：作者 (年份). 题名. 刊名, 卷(期), 页码. https://doi.org/…；正文用 (Author, 2020) 引用。',
      },
    ],
  },
  {
    id: 'tpl-ieee',
    name: 'IEEE 会议论文',
    note: 'Abstract · Index Terms · I. Introduction · II. Related Work · III. Method · IV. Experiments · V. Conclusion · Acknowledgment · References',
    style: 'IEEE（顺序编码，罗马数字节号）',
    sections: [
      {
        heading: 'Abstract',
        hint: '150–250 words, one paragraph, no references, no undefined abbreviations —— IEEE 模板的硬要求。',
      },
      {
        heading: 'Index Terms',
        hint: '按**字母序**排 3–5 个术语（不是关键词表顺序），写在摘要之后、正文之前。',
      },
      {
        heading: 'I. Introduction',
        hint: '节号用罗马数字大写（I.、II.、III.…），二级用 A.、B.；引言最后一段点明贡献。',
      },
      {
        heading: 'II. Related Work',
        hint: '按问题分组，不比先后；每组收尾写清与本文差在哪一条假设或哪一步做法。',
      },
      {
        heading: 'III. Method',
        hint: '先符号与假设，再模型/算法；公式用 (1)(2) 编号，复杂度与实现细节（硬件、超参）写明。',
      },
      {
        heading: 'IV. Experiments',
        hint: '数据集、基线、指标、主表、消融；IEEE 正文图题在**图下**、表题在**表上**。',
      },
      {
        heading: 'V. Conclusion',
        hint: 'IEEE 常规只写一节 Conclusion（不加 s）：结果 + 局限 + 后续工作，一段话。',
      },
      {
        heading: 'Acknowledgment',
        hint: 'IEEE 用单数 Acknowledgment（不是 Acknowledgements），放在结论之后、参考文献之前。',
      },
      {
        heading: 'References',
        hint: 'IEEE：[1] A. B. Author, "Title," Journal, vol. x, no. x, pp. xx–xx, Year. 按正文出现顺序编号。',
      },
    ],
  },
  {
    id: 'tpl-thesis',
    name: '学位论文（中文）',
    note: '中文摘要 · Abstract · 目录 · 绪论 · 相关工作 · 方法 · 实验 · 结论与展望 · 参考文献 · 致谢 · 附录',
    style: 'GB/T 7714 + 学位论文规范',
    sections: [
      {
        heading: '中文摘要',
        hint: '500–1000 字（硕博）：研究问题、方法、主要结果、创新点；与英文摘要逐句对应。',
      },
      {
        heading: 'Abstract',
        hint: '与中文摘要对应，不另加内容；专业术语用本领域通行译法。',
      },
      {
        heading: '目录',
        hint: '用标题样式自动生成（别手打）；章、节、页码一致，图表目录与符号表按学校要求附在目录后。',
      },
      {
        heading: '绪论',
        hint: '研究背景与意义、国内外研究现状（要有述评，不是罗列）、研究内容与技术路线、论文结构。',
      },
      {
        heading: '相关工作',
        hint: '按问题分组；每节收尾点明"已有工作的不足"与"本文补哪一块"。',
      },
      {
        heading: '方法',
        hint: '假设与符号先列、再模型/算法；关键推导给编号，复杂度与成本一并写明。',
      },
      {
        heading: '实验',
        hint: '数据、基线、指标、主结果、消融、失败案例；失败案例也要写，别只留跑通的那组。',
      },
      {
        heading: '结论与展望',
        hint: '回答了绪论里的哪个问题、创新点、局限、下一步；不把"未来工作"写成已完成。',
      },
      {
        heading: '参考文献',
        hint: 'GB/T 7714；数量与年限按学校要求（一般近五年占一定比例）。',
      },
      {
        heading: '致谢',
        hint: '导师、课题组、基金（写项目编号）；不写与论文无关的内容。',
      },
      {
        heading: '附录',
        hint: '放正文放不下的推导、代码、问卷、补充表格；附录条目要在正文里被引用到。',
      },
    ],
  },
  {
    id: 'tpl-report',
    name: '研究报告',
    note: '问题 · 背景 · 方法 · 发现 · 建议',
    style: '内部报告（无投稿体例）',
    sections: [
      {
        heading: '问题',
        hint: '一句话写清要回答什么，并给出"答上了没有"的判断标准；不要把三个问题塞进一段。',
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
        hint: '按重要性排，每条给数字或原话证据并标出处；不确定的地方照实说不确定。',
      },
      {
        heading: '建议',
        hint: '每条建议对应一条发现，写清谁来做、代价多大；不写"加强重视"这类空话。',
      },
    ],
  },
]

/** 命中给整份，不命中返回 null（不编一个空模板）。 */
export function templateById(id) {
  const hit = WRITE_TEMPLATES.find((item) => item.id === id)
  return hit || null
}

/**
 * 生成结构骨架（Markdown）：**只有标题**，不往正文里塞任何提示文字。
 * 写作要点在界面上按节列出（2026-10-19 用户明确否掉了把提示刻进正文）。
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
    lines.push(`## ${section.heading}`)
    lines.push('')
  }
  return `${lines.join('\n').replace(/\n+$/, '')}\n`
}
