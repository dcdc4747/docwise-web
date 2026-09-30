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

import re

# 类型词表（前端按这四个值给样式；新增值要先想好界面上怎么表现）
BLOCK_TYPES = ("title", "heading", "caption", "body")

# 图注 / 表注：Figure 1 / Fig. 3: / Table 2 / Scheme 1 / 图 1 / 表 2
_CAPTION_RE = re.compile(
    r"^(?:fig(?:ure)?|tab(?:le)?|scheme|chart|图|表)\s*[.．]?\s*\d+", re.IGNORECASE
)
# 西文编号标题：1 Introduction / 2.1 Methods / 3.4.1 Notes
# （要求编号后紧跟空白，避免把 "2023年正式纳入…" 这种正文当成标题）
_NUMBERED_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,3}[.、)．]?\s+\S")
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

    收紧过一轮：作者署名、页脚这类"全大写但明显不是标题"的串要挡在外面——
    见 `_ALL_CAPS_MAX` 的注释（那两条是真样本上抓出来的）。
    罗马数字编号（`I.` / `II.`）先剥掉再判，否则那个点号会把化学那份的章节标题误杀。
    """
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


def classify(text: str, block_id: str | None = None) -> str:
    """给一块文字判类型。`block_id` 用来认"首页最前面那几块"（题名区）。"""
    line = (text or "").strip()
    if not line:
        return "body"
    if _CAPTION_RE.match(line):
        return "caption"
    if _looks_like_heading(line):
        return "heading"
    # 题名区里、且不像句子（行尾没有标点）的短块，按题名处理
    if (
        _in_title_zone(block_id)
        and _TITLE_MIN <= len(line) <= _TITLE_MAX
        and line[-1] not in _TERMINAL
    ):
        return "title"
    return "body"


def classify_blocks(blocks: list[dict]) -> list[dict]:
    """就地给一批块补 `type`（元素形如 `{"block_id", "text", ...}`）。"""
    for block in blocks:
        block["type"] = classify(block.get("text") or "", block.get("block_id"))
    return blocks
