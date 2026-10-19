r"""「该引未引」检测：挑出像在引述他人成果、却没引用标记的句子。

为什么用规则而不是模型
----------------------
模型判「该不该引」会瞎报，而且贵。规则版能给出**可解释的判据**，
判错了也能改规则。所以这里**高精度优先**：判不出来就不报。

八条规则（每条都能人工复核）
----------------------------
1. 分句：按中文 `。！？` 与英文 `. ` 切；`#` 开头的标题行跳过。
2. 已引不报：句内有 `[1]` / `[1,2]` / `[1-3]` 这类标记。
3. 报告类动词：`研究表明` / `研究发现` / `调查显示` / `数据显示` /
   `文献指出` / `已有研究` / `studies show` /
   `research suggests` / `it has been shown` 命中即报，
   reason 为「引述他人研究的典型句式」。
4. 统计量：`p<0.05` / `p = 0.03` / `95% CI` / `OR=` / `HR=` /
   `n=` / `N=` / `±` 命中即报，reason 为「带统计量，需要出处」。
5. 百分比 + 年份同句（如 `2020 年 …… 47%`）→ 报，
   reason 为「含具体数据，需要出处」。
6. 每句只报一次：按规则 3 → 4 → 5 依次判，命中即止；
   同时命中时给优先级高的那条 reason。
7. `limit` 默认 10、最大 30；`chars` 是句子长度；`line_no` 是
   句子第一个字在原文里的行号（1 起）。
8. 自指不报（**句中任意位置**，不只句首）：`本文` / `本研究` / `我们` /
   `共纳入` / `共收集` / `笔者` 等，那是作者自己的工作，要不要引用是另一回事。
   放宽到句中的原因：方法段常写成「共纳入 120 例（n=120），年龄 45±12 岁」，
   句首没有自指词。**代价是会漏报**（「已有研究表明 X，我们认为 Y」整句不报）。

两个刻意的收窄（都是为了少误报）
--------------------------------
- 引用标记除题面的 `\[\d+(?:[,\-–]\d+)*\]` 外，还容忍分隔符两侧
  的空格（`[1, 2]` 同样是引用）——这只会**减少**误报；
- 年份必须写成 `2020 年`，或英文 `in 2020` 这类带介词的写法；
  **裸数字不算**，免得把「2020 条记录」当成数据年份。
"""

from __future__ import annotations

import re
from collections.abc import Iterator

# limit 的硬上限：再多就不是「提示」，而是拿噪声淹没作者
_MAX_LIMIT = 30

# 引用标记：题面 `\[\d+(?:[,\-–]\d+)*\]`，额外容忍分隔符两侧空格
_CITATION_RE = re.compile(r"\[\s*\d+(?:\s*[,\-–]\s*\d+)*\s*\]")

# 自指（**句中任意位置**）：作者自己的工作，不要求引用。
# 为什么放宽到句中：方法段常写成「共纳入 120 例（n=120），年龄 45±12 岁」，
# 数字开头、句首没有自指词，旧规则挡不住 → 校对会把自己的数据当"该引未引"报出来。
# 代价是漏报（「已有研究表明 X，我们认为 Y」会整句不报），按用户要求：宁可漏，不可烦。
_SELF_REF_RE = re.compile(
    r"本文|本研究|本实验|本调查|本次研究|本研究团队"
    r"|我们|课题组|笔者"
    r"|共纳入|共收集|共调查|共招募|纳入分析"
)

# 报告类动词：中英两套，英文不分大小写
_REPORT_RE = re.compile(
    r"研究表明|研究发现|调查显示|数据显示|文献指出|已有研究"
    r"|studies\s+show|research\s+suggests|it\s+has\s+been\s+shown",
    re.IGNORECASE,
)

# 统计量：每一条都对应题面里点名的一种写法
_STAT_RES = (
    # p<0.05 / p = 0.03 / P 值 = 0.01
    re.compile(r"(?<![A-Za-z0-9])[pP]\s*(?:值)?\s*[<>=]\s*0?\.\d+"),
    # 95% CI / 95 % CI（不要求词边界：中文里常写成「95%CI为」）
    re.compile(r"95\s*%\s*CI", re.IGNORECASE),
    # OR= / HR=
    re.compile(r"(?<![A-Za-z0-9])(?:OR|HR)\s*=\s*\d"),
    # n= / N =
    re.compile(r"(?<![A-Za-z0-9])[nN]\s*=\s*\d"),
    # ±
    re.compile(r"±"),
)

# 百分比：47% / 47.5 % / 47 percent / 百分之四十七
_PERCENT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|percent\b)|百分之[零〇一二三四五六七八九十百\d]+",
    re.IGNORECASE,
)

# 年份：中文必须带「年」；英文只认带介词的自然写法
_YEAR_RE = re.compile(
    r"(?:19|20)\d{2}\s*年"
    r"|\b(?:in|since|by|during|from|before|after)\s+(?:19|20)\d{2}\b",
    re.IGNORECASE,
)


def _text_with_lines(body_md: str) -> tuple[str, list[int]]:
    """去掉标题行与空行，拼成待切文本，并记下每个字符来自第几行。"""
    chars: list[str] = []
    line_of: list[int] = []
    for line_no, line in enumerate(body_md.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if chars:
            chars.append("\n")
            line_of.append(line_no)
        chars.extend(stripped)
        line_of.extend([line_no] * len(stripped))
    return "".join(chars), line_of


def _split_sentences(text: str) -> Iterator[tuple[int, int]]:
    """按中文句末标点与英文 `. ` 切句，返回半开区间 `[start, end)`。"""
    start = 0
    for index, char in enumerate(text):
        followed_by_space = char == "." and (
            index + 1 == len(text) or text[index + 1].isspace()
        )
        if char in "。！？" or followed_by_space:
            yield start, index + 1
            start = index + 1
    if start < len(text):
        yield start, len(text)


def _reason_for(sentence: str) -> str | None:
    """按规则 3 → 4 → 5 判这句为什么该引；都不命中返回 None。"""
    if _REPORT_RE.search(sentence):
        return "引述他人研究的典型句式"
    if any(pattern.search(sentence) for pattern in _STAT_RES):
        return "带统计量，需要出处"
    if _PERCENT_RE.search(sentence) and _YEAR_RE.search(sentence):
        return "含具体数据，需要出处"
    return None


def find_citation_gaps(body_md: str, limit: int = 10) -> list[dict]:
    """返回疑似「该引未引」的句子，每项含四个键。

    - `sentence`：句子原文（已去掉首尾空白，跨行时并成一个空格）；
    - `reason`：命中的判据（规则 3 / 4 / 5 之一，见模块说明）；
    - `chars`：句子长度；
    - `line_no`：句子第一个字在 `body_md` 里的行号（1 起）。

    规则 1 / 2 / 8 只做过滤：标题行、带引用标记、自指的句子一律不报。
    `limit` 默认 10、最大 30；判定顺序固定，判不出来不报。
    """
    if limit <= 0 or not body_md:
        return []
    limit = min(limit, _MAX_LIMIT)

    text, line_of = _text_with_lines(body_md)
    gaps: list[dict] = []
    for start, end in _split_sentences(text):
        first = start
        while first < end and text[first].isspace():
            first += 1
        if first >= end:
            continue

        sentence = " ".join(text[first:end].split())
        if _SELF_REF_RE.search(sentence):
            continue
        if _CITATION_RE.search(sentence):
            continue

        reason = _reason_for(sentence)
        if reason is None:
            continue

        gaps.append(
            {
                "sentence": sentence,
                "reason": reason,
                "chars": len(sentence),
                "line_no": line_of[first],
            }
        )
        if len(gaps) >= limit:
            break
    return gaps


def summarize_gaps(gaps: list[dict]) -> str:
    """一句话汇总（给 note / 界面用）。

    0 条时如实说「未发现」，不写「有 0 句」这种编出来的话。
    """
    if not gaps:
        return "未发现疑似该引未引的句子"
    return f"有 {len(gaps)} 句像是引述他人成果但没有引用标记"
