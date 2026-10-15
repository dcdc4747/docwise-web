"""收口检查执行器：纯函数，**不碰数据库、不调模型**。

流程（顺序不能换）：

1. **判语言**（E1）—— 词表分中英两套，判不出就明示，**绝不静默失效**；
2. **判引用制式**（E2）—— `numeric` / `author-year` / `unknown`；
   判不出时「该引未引」整族归 `unknown` 档（**不硬猜**）——
   否则一份著者-出版年制的稿子会被"无 `[n]` → 报"全部误报；
3. **跑规则** —— 逐条产出 `findings`，每条带 `rule_ref`（说清按哪条判的）。

报告形状照契约 §2.7；`ruleset_version` 是本次新增字段，
用来让旧报告说清"按第几版规则跑的"。

`severity` 只有 `report` 与 `unknown` 两档：中间档会被读成"建议看看"，
等于把不确定说成了结论。
"""

from __future__ import annotations

import hashlib
import re

from .rules import (
    AUTHOR_YEAR_RE,
    CSL_AUTHOR_FIELDS,
    CSL_REQUIRED_FIELDS,
    HEDGES,
    MARKERS,
    NUMERIC_RE,
    RULESET_VERSION,
    SELF_REF_WINDOW,
    SELF_REFS,
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])|(?<=[.!?])\s+|\n+")
_NUMERIC_RE = re.compile(NUMERIC_RE)
_AUTHOR_YEAR_RE = re.compile(AUTHOR_YEAR_RE)

# 判语言/制式的最少证据量：太少就不判（**不硬猜**）
_MIN_LETTERS_FOR_LANG = 30
_MAX_PER_RULE = 5


def split_sentences(text: str) -> list[tuple[int, str]]:
    """切句，带起始偏移。

    切不干净也没关系——**句子只用来定位与展示，不用来判对错**。
    """
    out: list[tuple[int, str]] = []
    cursor = 0
    for chunk in _SENTENCE_SPLIT_RE.split(text or ""):
        piece = chunk or ""
        stripped = piece.strip()
        if stripped:
            out.append((cursor + piece.index(stripped), stripped))
        cursor += len(piece)
    return out


def detect_language(text: str) -> tuple[str, str]:
    """判正文语言 → `(lang, evidence)`；`lang ∈ {zh, en, unknown}`。"""
    cjk = len(_CJK_RE.findall(text or ""))
    latin = len(_LATIN_RE.findall(text or ""))
    total = cjk + latin
    if total < _MIN_LETTERS_FOR_LANG:
        return "unknown", f"正文可判字母只有 {total} 个，不足以判断语言"
    ratio = cjk / total
    if ratio >= 0.5:
        return "zh", f"汉字 {cjk} / 拉丁字母 {latin}"
    return "en", f"汉字 {cjk} / 拉丁字母 {latin}"


def detect_citation_style(text: str) -> tuple[str, str]:
    """判引用制式 → `(style, evidence)`。

    `style ∈ {numeric, author-year, unknown}`；**一处标注都没有时不硬猜**。
    """
    numeric = len(_NUMERIC_RE.findall(text or ""))
    author_year = len(_AUTHOR_YEAR_RE.findall(text or ""))
    if numeric == 0 and author_year == 0:
        return "unknown", "全篇既无 `[n]` 也无「（作者，年份）」，判不出引用制式"
    if numeric >= author_year * 2:
        return "numeric", f"`[n]` {numeric} 处 / 「（作者，年份）」{author_year} 处"
    if author_year >= numeric * 2:
        return "author-year", f"「（作者，年份）」{author_year} 处 / `[n]` {numeric} 处"
    return "unknown", f"`[n]` {numeric} 处与「（作者，年份）」{author_year} 处量级接近"


def _numbers_in_text(text: str) -> list[int]:
    """正文里所有 `[n]` 编号（`[1-3]` 展开成 1、2、3）。"""
    numbers: list[int] = []
    for mark in _NUMERIC_RE.findall(text or ""):
        for part in mark.strip("[]").split(","):
            part = part.strip()
            span = re.split(r"[-–—]", part)
            # ⚠️ 先判长度再取 span[1]：单编号 `[1]` 切出来只有一段，
            # 顺序写反就是 IndexError（单测当场抓过）。
            if len(span) == 2:
                pair = (span[0].strip(), span[1].strip())
            else:
                pair = ("", "")
            low, high = pair
            if low.isdigit() and high.isdigit():
                start, stop = int(low), int(high)
                if 0 < stop - start <= 50:
                    numbers.extend(range(start, stop + 1))
                    continue
            if part.isdigit():
                numbers.append(int(part))
    return numbers


def _fingerprint(rule_code: str, sentence: str) -> str:
    """`(规则号, 句子)` 的指纹。

    ⚠️ **不能用 finding 序号或 run_id 当键**：重跑一次，id 全变了，
    用户的"这条我认过了"就会全丢——所以处置（下一版做）认的是这个指纹。
    """
    raw = f"{rule_code}\x00{sentence.strip()}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _grams(text: str) -> set[str]:
    """中文按二字组、英文按词——判"字面重合"够用且可解释。"""
    clean = re.sub(r"[\s\W_]+", "", text or "")
    if len(clean) < 2:
        return {clean} if clean else set()
    return {clean[i : i + 2] for i in range(len(clean) - 1)}


def _suggest_for(sentence: str, materials: list[dict] | None) -> dict | None:
    """给「该引未引」挑一条**候选素材**（契约 §2.7 的 `suggest`）。

    挑不出就给 `None`——**宁可说"挑不出"，也不硬塞一条不相关的**。
    """
    if not materials or not sentence:
        return None
    target = _grams(sentence)
    if not target:
        return None
    best: tuple[float, dict] | None = None
    for material in materials:
        quote = material.get("translated_quote") or material.get("text_quote") or ""
        candidate = _grams(quote)
        if not candidate:
            continue
        score = len(target & candidate) / len(target | candidate)
        if best is None or score > best[0]:
            best = (score, material)
    if best is None or best[0] <= 0:
        return None
    material = best[1]
    return {
        "material_id": material.get("id"),
        "page": material.get("page"),
        "quote": (material.get("text_quote") or "")[:80],
    }


class _Report:
    """攒 findings：**统一发号、统一统计**（id 只用于展示，指纹才是身份）。"""

    def __init__(self) -> None:
        self.findings: list[dict] = []

    def add(
        self,
        *,
        rule_code: str,
        kind: str,
        severity: str,
        sentence: str,
        reason: str,
        rule_ref: str,
        suggest: dict | None = None,
    ) -> None:
        self.findings.append(
            {
                "id": f"f{len(self.findings) + 1}",
                "fingerprint": _fingerprint(rule_code, sentence),
                "rule_id": rule_code,
                "kind": kind,
                "severity": severity,
                "sentence": sentence[:200],
                "reason": reason,
                "suggest": suggest,
                "rule_ref": rule_ref,
            }
        )


def _run_missing_citation(
    report: _Report,
    *,
    doc_text: str,
    lang: str,
    style: str,
    materials: list[dict],
) -> None:
    """R1：该引未引（三类检查里的"核心"，纵深全在这里）。"""
    marks = _NUMERIC_RE if style == "numeric" else _AUTHOR_YEAR_RE
    self_refs = SELF_REFS[lang]
    hedges = HEDGES[lang]
    for offset, sentence in split_sentences(doc_text):
        if marks.search(sentence):
            continue  # 已有标注 → 不报
        if any(word in sentence for word in hedges):
            continue  # 模糊限定 → 不报
        hit = next((word for word in MARKERS[lang] if word in sentence), None)
        if hit is None:
            continue
        # 自指豁免：命中词前方 8 字内出现自指词 → 一律不报（"本研究表明"）
        before = (doc_text or "")[max(0, offset - SELF_REF_WINDOW) : offset]
        # ⚠️ 连命中词一起看：`本研究表明` 的「本研究」是**跨在命中词边界上的**
        # （只看到"表明"之前那一个"本"字，就漏掉豁免了——单测真抓过这条）。
        head = before + sentence[: sentence.index(hit) + len(hit)]
        if any(word in head for word in self_refs):
            continue
        report.add(
            rule_code="R1",
            kind="missing_citation",
            severity="report",
            sentence=sentence,
            reason=f"命中标记词「{hit}」，句内无引用标注（{style}）",
            rule_ref="形态 §3.3 ①",
            suggest=_suggest_for(sentence, materials),
        )


def _run_citation_format(
    report: _Report, *, doc_text: str, citations: list[dict]
) -> None:
    """R2/R3/R4：正文编号与文献表条目的一一对应、连续性。"""
    in_text = _numbers_in_text(doc_text)
    orders = [int(item.get("order") or 0) for item in citations if item.get("order")]
    text_set, order_set = set(in_text), set(orders)

    for number in sorted(text_set - order_set)[:_MAX_PER_RULE]:
        report.add(
            rule_code="R2",
            kind="missing_citation",
            severity="report",
            sentence=f"[{number}]",
            reason=f"正文引了 `[{number}]`，文献表里没有对应条目",
            rule_ref="形态 §3.3 ③ 文内编号与文后条目一一对应",
        )
    for number in sorted(order_set - text_set)[:_MAX_PER_RULE]:
        report.add(
            rule_code="R3",
            kind="format",
            severity="report",
            sentence=f"[{number}]",
            reason=f"文献表第 {number} 条在正文里从没被引用过",
            rule_ref="形态 §3.3 ③ 文内编号与文后条目一一对应",
        )
    gaps = sorted(set(range(1, max(text_set) + 1)) - text_set) if text_set else []
    if gaps:
        report.add(
            rule_code="R4",
            kind="format",
            severity="report",
            sentence=f"缺号：{gaps[:10]}",
            reason=f"编号从 1 到 {max(text_set)} 之间缺 {len(gaps)} 个号",
            rule_ref="形态 §3.3 ③ 引文编号连续性",
        )


def _run_csl_fields(report: _Report, *, citations: list[dict]) -> None:
    """R5：条目字段完整性（输入是我们插入引文时生成的 CSL-JSON）。"""
    for item in citations[:_MAX_PER_RULE]:
        csl = item.get("csl_json") or {}
        missing = [field for field in CSL_REQUIRED_FIELDS if not csl.get(field)]
        if not any(csl.get(field) for field in CSL_AUTHOR_FIELDS):
            missing.append("author")
        if missing:
            report.add(
                rule_code="R5",
                kind="format",
                severity="report",
                sentence=f"[{item.get('order')}] {csl.get('title') or '（无题名）'}",
                reason="条目缺字段：" + "、".join(missing),
                rule_ref="形态 §3.3 ③ 条目字段完整性",
            )


def run_check(
    doc_text: str,
    *,
    citations: list[dict] | None = None,
    materials: list[dict] | None = None,
) -> dict:
    """跑一次收口检查。

    - `doc_text`：稿子正文（契约 N22 的入参）；
    - `citations`：引文列表，每条至少带 `order` 与 `csl_json`；
    - `materials`：素材卡列表（给「该引未引」挑候选出处）。

    ⭐ 三个入参**都可以缺**：缺了不是报错，而是少做那几条能做的检查并如实说明。
    """
    citations = citations or []
    materials = materials or []
    report = _Report()

    lang, lang_evidence = detect_language(doc_text)
    style, style_evidence = detect_citation_style(doc_text)
    notes = [f"语言：{lang}（{lang_evidence}）"]

    if lang == "unknown":
        notes.append(f"引用制式：{style}（{style_evidence}）")
        report.add(
            rule_code="R7",
            kind="unknown",
            severity="unknown",
            sentence=(doc_text or "")[:60],
            reason=f"判不出正文语言（{lang_evidence}）；词表只有中英两套，**这一项没判**",
            rule_ref="形态 §3.3 E1 语言盲区",
        )
    elif style == "unknown":
        notes.append(f"引用制式：{style}（{style_evidence}）")
        report.add(
            rule_code="R7",
            kind="unknown",
            severity="unknown",
            sentence=(doc_text or "")[:60],
            reason=(
                f"{style_evidence}；「该引未引」的判据是「无 `[n]` → 报」，"
                "制式判不准时硬报会把著者-出版年制的稿子全部误报，**整族不判**"
            ),
            rule_ref="形态 §3.3 E2 引用制式盲区",
        )
    else:
        notes.append(f"引用制式：{style}（{style_evidence}）")
        _run_missing_citation(
            report, doc_text=doc_text, lang=lang, style=style, materials=materials
        )

    _run_citation_format(report, doc_text=doc_text, citations=citations)
    _run_csl_fields(report, citations=citations)

    reported = sum(1 for item in report.findings if item["severity"] == "report")
    unknown = sum(1 for item in report.findings if item["severity"] == "unknown")
    return {
        "ruleset_version": RULESET_VERSION,
        "run_id": None,
        "step": {"lang": lang, "citation_style": style, "notes": notes},
        "findings": report.findings,
        "summary": {"reported": reported, "unknown": unknown},
    }
