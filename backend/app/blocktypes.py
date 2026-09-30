"""块分级：把"一坨文字块"分成 **文献题名 / 章节标题 / 图注 / 正文**。

这是阶段 3（中立文档对象模型）的第一小步：先让每块**有类型**，段落精读才分得出
标题与正文，图注也才有落点；表格 / 公式类型留到 v2。

**判据只用文字形状**（标题的编号、章节名、图注前缀、全大写短行），**不依赖版面信息**。
这么做是刻意的：

- 三条取字路径（PDF 文字层 / 扫描件 OCR / 外部翻译引擎）只有第一条拿得到字号，
  若在引擎侧各判一遍，三条路的类型口径必然漂移；
- 放后端一处判，**老任务不用重跑也立刻受益**（不用改库、不用回填）；
- 代价如实说：**不带编号、又不与常见章节名重合的标题会判不出来**，会被当正文；
  这里**不猜字号**，也不做"前 N 块一定是标题"之外的位置推断。

想升级成真正的版面判定（字号 + 位置 + 加粗），要等引擎侧把每块的版面属性带回来——
那时这里是同一个入口，换实现不改协议。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 类型词表（前端按这四个值给样式；新增值要先想好界面上怎么表现）
BLOCK_TYPES = ("title", "heading", "caption", "body")

# 图注 / 表注：Figure 1 / Fig. 3: / Table 2 / Scheme 1 / 图 1 / 表 2
_CAPTION_RE = re.compile(
    r"^(?:fig(?:ure)?|tab(?:le)?|scheme|chart|图|表)\s*[.．]?\s*\d+", re.IGNORECASE
)
# 西文编号标题：1 Introduction / 2.1 Methods / 3.4.1 Notes / A. Geometrical measure
# （要求编号后紧跟空白，避免把 "2023年正式纳入…" 这种正文当成标题；
#  最后那支是**字母编号**：arXiv 论文里 `A. xxx` / `B. xxx` 是二级标题，
#  实测化学那份 20 多条小节标题全靠这条）
_NUMBERED_RE = re.compile(
    r"^(?:\d{1,2}(?:\.\d{1,2}){0,3}[.、)．]?|[A-Z][.)．])\s+\S"
)
# 中文编号标题：一、xxx ／ （一）xxx ／ (1) xxx
_CJK_NUM_RE = re.compile(r"^[一二三四五六七八九十]+[、.．]\s*\S")
_CJK_PAREN_RE = re.compile(r"^[（(]\s*[一二三四五六七八九十\d]+\s*[）)]\s*\S")
# 行尾是这些标点 → 是句子，不是标题
_TERMINAL = "。．.；;！!？?，,、"
# 常见章节名（整行就是它）
_SECTION_WORDS = frozenset(
    {
        "abstract",
        "introduction",
        "related work",
        "background",
        "preliminaries",
        "method",
        "methods",
        "methodology",
        "materials and methods",
        "experiments",
        "experimental setup",
        "results",
        "result",
        "discussion",
        "conclusion",
        "conclusions",
        "references",
        "bibliography",
        "acknowledgment",
        "acknowledgments",
        "acknowledgements",
        "appendix",
        "摘要",
        "引言",
        "背景",
        "方法",
        "实验",
        "结果",
        "讨论",
        "结论",
        "参考文献",
        "致谢",
        "附录",
        "目录",
    }
)
# 题名区：首页最前面几块（论文题名常被拆成 2–3 块）
_PAGE_ZERO_RE = re.compile(r"^p0_b(\d+)$")
_TITLE_ZONE_BLOCKS = 2
# 标题 / 题名的长度上限：超过就不是标题了，是正文
_HEADING_MAX = 120
_HEADING_SHORT_MAX = 60
# "比正文大一点"这条的**长度上限**（2026-10-01 加）：
# 实测真标题都短（中文样本 1.20 倍的 `摘 要`/`Keywords`/`参考文献` 是 2–8 个字），
# 而**冒牌货都长**——EBSCO 杂志那类 1.60 倍的"导语（deck）"是一整句话。
# 所以"大 + 短"才判标题；**只抬阈值不管用**（1.25 既挡不住 1.60 的导语，
# 又会漏掉 1.20 的真标题）。
_TITLE_MAX = 150
# 题名区里的下限：实测英文杂志版式会在首页头部产生 `L` 这种碎片块，
# 不设下限它就成了"文献题名"
_TITLE_MIN = 6
# 全大写标题的长度上限与词数上限。实测踩过：作者署名行
# `BY MADELINE COHEN, AARON PIERCE, BRIAN BLAHO & AMY DIETRICH`（58 字符、有逗号）
# 和页脚 `20AALLSPECTRUMIWWW.AALLNET.ORG`（含数字与点）都被"全大写"这条吃进来过。
_ALL_CAPS_MAX = 45
_ALL_CAPS_MAX_WORDS = 4
# 全大写标题的下限：实测那个 `L` 碎片块也是"全大写"，1 个字符当然不是标题
_ALL_CAPS_MIN = 4
# 罗马数字编号前缀（I. / II. / IV)）——判全大写标题前先剥掉
_ROMAN_PREFIX_RE = re.compile(r"^(?:[IVXLC]{1,4}[.、)]\s+)+")


def _in_title_zone(block_id: str | None) -> bool:
    match = _PAGE_ZERO_RE.match(block_id or "")
    return bool(match) and int(match.group(1)) <= _TITLE_ZONE_BLOCKS


def _is_all_caps_heading(line: str) -> bool:
    """全大写短行（ABSTRACT / I. INTRODUCTION / RELATED WORK）。

    收紧过两轮，两条都是真样本上抓出来的：

    - 第一轮：作者署名行（`BY MADELINE COHEN, …`）与页脚
      （`20AALLSPECTRUMIWWW.AALLNET.ORG`）被"全大写"吃进来
      → 限长度、限词数、不许含数字与点号、不许以标点开头；
    - 第二轮（2026-09-30，中文样本实测）：**中文里夹着 `AI`/`AIGC` 的正文段会被误判**——
      Python 的 `str.isupper()` 只看"有大小写的字符"，`…生成式AI 驱动下` 里唯一
      有大小写的就是 `AI`，于是整段被判成全大写。一篇 257 块的文献因此误判出
      **9 个正文段**当标题。→ **含 CJK 的行走不到这条**（中文小标题另有判据）。
    """
    if any("\u4e00" <= char <= "\u9fff" for char in line):
        return False
    if not line.isupper() or not (_ALL_CAPS_MIN <= len(line) <= _ALL_CAPS_MAX):
        return False
    # 以标点开头的一律不算标题：实测 OCR 把作者署名切碎后剩出 `&AMY DIETRICH`
    if not line[0].isalnum():
        return False
    body = _ROMAN_PREFIX_RE.sub("", line)
    if any(char.isdigit() for char in body) or "." in body or "," in body:
        return False
    return len(body.split()) <= _ALL_CAPS_MAX_WORDS


def _looks_like_heading(line: str) -> bool:
    if len(line) > _HEADING_MAX or line[-1] in _TERMINAL:
        return False
    if _NUMBERED_RE.match(line) or _CJK_NUM_RE.match(line) or _CJK_PAREN_RE.match(line):
        return True
    if line.lower().strip(" .:：") in _SECTION_WORDS:
        return True
    return _is_all_caps_heading(line)


def classify(
    text: str,
    block_id: str | None = None,
    layout: dict | None = None,
    body_h: float | None = None,
    has_signal: bool | None = None,
) -> str:
    """给一块文字判类型。

    - `block_id` 用来认"首页最前面那几块"（题名区）；
    - `layout` + `body_h` 是**版面信号**（2026-09-30 起）：`layout` 是该块自己的量
      （见 scripts/extract_blocks.py 的契约），`body_h` 是**全篇正文的基准行高**
      （由 `classify_blocks` 一次算好传下来——单看一块是不知道"大不大"的）。
    **给不出信号时的退路**：没有 layout 的块（老任务、OCR 那两条路）走文字形状判据。

    ⚠️ 注意口径（2026-10-01 更正）：**库层面**是零变化的（block_id / 切段 / 译文 /
    检索 / 问答都不碰），但**分级结果会变**——修掉 `str.isupper()` 那个 bug 之后，
    中文老任务会**少掉**一批被误判成标题的正文段，字母编号那条也会多判一些。
    "与以前完全一致"这句话只对库层面成立，对分级结果不成立。
    """
    line = (text or "").strip()
    if not line:
        return "body"
    if _CAPTION_RE.match(line):
        return "caption"
    if _looks_like_heading(line):
        return "heading"
    if _looks_like_heading_by_layout(line, layout, body_h):
        return "heading"
    # 题名区里、且不像句子（行尾没有标点）的短块，按题名处理。
    # 有版面信号时**不让这条兜底规则抢答**——因为"题名区里字号最大的那块"才是真题名
    # （实测：中文样本首页前几块里，页眉与引用行都是 9pt，真题名 22pt；
    #  这条兜底会把引用行也判成题名）。批处理里由 `_title_block_id` 精确指定。
    if (
        not (has_signal if has_signal is not None else _has_layout(layout))
        and _in_title_zone(block_id)
        and _TITLE_MIN <= len(line) <= _TITLE_MAX
        and line[-1] not in _TERMINAL
    ):
        return "title"
    return "body"


def _has_layout(layout: dict | None) -> bool:
    """这一块自己有没有可用的版面信号。

    ⚠️ **判"这篇有没有信号"不要用它**——那要按全篇判（见 `classify_blocks` 传的
    `has_signal`）。用单块判过的坑：同一篇里一部分块有信号、一部分没有时，
    没信号的那几块会被静默降级（题名兜底被跳过），与"有信号就统一交给版面判定"相反。
    """
    return isinstance(layout, dict) and bool(layout.get("unit_h"))


def _looks_like_heading_by_layout(
    line: str, layout: dict | None, body_h: float | None
) -> bool:
    """**靠版面量**判标题。阈值全部来自真样本实测（2026-09-30）：

    - 中文样本（`cn_paper.pdf` 257 块）：正文 10.0pt，而 `摘 要`/`1. 引言`/
      `2. 理论基础`/`3. …机制分析`/`4. …实现路径`/`5. 结论与展望`/`参考文献`
      **全是 12.0pt = 1.2 倍**；而且这些标题的加粗占比从 0.00 到 1.00 都有
      （`参考文献` 是 0.00、`3.` 只有 0.14）
      → **中文排版里"字号大一点"才是稳的信号，"加粗"不稳**。
    - 化学 arXiv：标题**加粗但字号只有正文的 0.90 倍**（arXiv 惯例），字号判据在这里
      方向是反的 → **必须两条都留**，不能只留一条。
    - 反例（用来定上限，都是实测抓到的）：EBSCO 杂志里 8.95 倍的 `L` 是
      **首字下沉碎片**、1.6 倍的是导语；`BY MADELINE COHEN, …` 是**署名行**
      （粗体、0.90 倍）→ 所以"太大不算标题"（>3 倍判为版面装饰）、
      "全大写署名行不算标题"。

    宁可少判几个，也不把正文标成标题——**判不出来时退回文字形状，不猜**。
    """
    if not isinstance(layout, dict) or not body_h:
        return False
    try:
        unit_h = float(layout.get("unit_h") or 0)
        bold = float(layout.get("bold") or 0)
    except (TypeError, ValueError):
        return False
    if unit_h <= 0 or len(line) > _HEADING_MAX or line[-1] in _TERMINAL:
        return False

    ratio = unit_h / body_h
    # ① 明显大于正文、但不是"超大装饰"（中文样本靠这条：1.2 倍）
    if 1.20 <= ratio <= 3.0 and len(line) <= _HEADING_SHORT_MAX:
        return True
    # ② 加粗 + 接近正文大小（arXiv 靠这条：0.90 倍但粗体）。
    #    护栏（都是实测抓出来的）：必须**全大写**（否则作者署名行 `Sheng Wu`
    #    会被吃成标题）、够短、不以 `BY ` 开头、不以标点开头
    if (
        bold >= 0.6
        and 0.85 <= ratio <= 1.15
        and len(line) <= _ALL_CAPS_MAX
        and line.isupper()
    ):
        head = line.lstrip()
        if head[:3].upper() == "BY " or not head[:1].isalnum():
            return False
        return True
    return False


def _body_height(blocks: list[dict]) -> float | None:
    """全篇"正文基准行高"：**按字符数加权的 unit_h 中位数**。

    踩过的坑（2026-09-30 实测）：一开始按**页**算，结果被页眉/页脚/图注带偏——
    某页的"基准"落到 8.5pt，于是 10pt 的**正文长段**被算成"比正文大 1.18 倍"，
    一篇 257 块的文献误判出 9 个正文段当标题。改成全篇、且**按字符数加权**
    （长块的 unit_h 更能代表正文）之后，这份样本的基准稳定落在 10.0pt，
    与人工看字号直方图（199/257 块是 10.0pt）一致。

    取不到任何 unit_h 时返回 None → 分级器自动退回"只看文字形状"。
    """
    items: list[tuple[float, int]] = []
    for block in blocks:
        layout = block.get("layout")
        if not isinstance(layout, dict):
            continue
        try:
            unit_h = float(layout.get("unit_h") or 0)
        except (TypeError, ValueError):
            continue
        if unit_h > 0:
            items.append((unit_h, len(block.get("text") or "")))
    if not items:
        return None
    items.sort(key=lambda kv: -kv[1])
    half = items[: max(3, len(items) // 2)]  # 字数最多的那一半 = 正文候选
    values = sorted(value for value, _ in half)
    return values[len(values) // 2]


def _title_block_id(blocks: list[dict], body_h: float | None = None) -> str | None:
    """题名区（首页最前面几块）里**字号最大**的那块＝文献题名；没有合格的就不给题名。

    为什么不是"第一块"：实测这份中文样本里，`p0_b0` 是期刊页眉（9pt）、
    `p0_b1` 是引用行（9pt），**真正的题名在 `p0_b2`（22pt）**——按"第一块"判会把
    引用行当题名。

    三条护栏（都是写测试时当场抓出来的，不是设想）：
    ① **够长**（≥ `_TITLE_MIN`）——否则只有 1 个字符的版面碎片 `L`（94pt）会当选题名；
    ② **不像句子**（行尾不能是句末标点）——否则一句正文会当选题名；
    ③ **得比正文明显大**（≥ 1.15 倍）——否则"整页都是正文"的文档也会硬吐一个题名。
    三条都不满足就返回 None：**宁可不给题名，也不乱给**
    （前端对没有题名的文档一切照旧）。
    """
    zone: list[tuple[float, str, str]] = []
    for block in blocks:
        block_id = block.get("block_id") or ""
        match = _PAGE_ZERO_RE.match(block_id)
        if not match or int(match.group(1)) > _TITLE_ZONE_BLOCKS:
            continue
        layout = block.get("layout")
        unit_h = 0.0
        if isinstance(layout, dict):
            try:
                unit_h = float(layout.get("unit_h") or 0)
            except (TypeError, ValueError):
                unit_h = 0.0
        zone.append((unit_h, block_id, (block.get("text") or "").strip()))
    if not zone:
        return None
    zone.sort(key=lambda item: -item[0])
    unit_h, block_id, text = zone[0]
    if unit_h <= 0 or len(text) < _TITLE_MIN or not text or text[-1] in _TERMINAL:
        return None
    # 图注不能当题名：首页大字号图注是常见版式，抢走题名会让真题名降级、图注被标成 title
    if _CAPTION_RE.match(text):
        return None
    if body_h and unit_h < body_h * 1.15:
        return None
    return block_id


def classify_blocks(blocks: list[dict]) -> list[dict]:
    """就地给一批块补 `type`（元素形如 `{"block_id", "text", "layout"?}`）。

    **一批一起看**，因为两件事只有看到全篇才知道：
    "这块字号算不算大"（要跟全篇正文基准比）、"哪块是题名"（要跟首页同区几块比字号）。
    """
    body_h = _body_height(blocks)
    # 有没有信号是**全篇**的事：只要有基准行高，所有块都走"有信号"的分支
    # （没有信号的块由 `classify` 自己退回文字形状）。
    has_signal = body_h is not None
    try:
        title_id = _title_block_id(blocks, body_h)
    except Exception:  # noqa: BLE001 - 判不出来就不给题名，绝不让详情接口挂掉
        logger.warning("选题名失败，本次不指定文献题名", exc_info=True)
        title_id = None
    for block in blocks:
        block_id = block.get("block_id")
        text = block.get("text") or ""
        try:
            if title_id and block_id == title_id:
                block["type"] = "title"
                continue
            block["type"] = classify(
                text, block_id, block.get("layout"), body_h, has_signal
            )
        except Exception:  # noqa: BLE001 - 分级判错只是少个样式，不能让任务详情 500
            logger.warning("块分级失败，按正文处理：%s", block_id, exc_info=True)
            block["type"] = "body"
    return blocks
