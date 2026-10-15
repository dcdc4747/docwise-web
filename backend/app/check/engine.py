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


def _contains(text: str, word: str, lang: str) -> bool:
    """按语言判"这个词有没有出现"。

    ⚠️ 英文必须按**词边界**：用子串会把 `were` 里的 `we`、`foundation` 里的 `found`
    都算命中 —— 前者让自指豁免**误免一大片**，后者凭空多出候选（单测真抓过）。
    中文按子串（中文没有词边界可言）。
    """
    if lang == "zh":
        return word in text
    return re.search(rf"\b{re.escape(word.lower())}\b", text.lower()) is not None


def _find_index(sentence: str, word: str, lang: str) -> int:
    """命中词在句内的位置（英文按词边界找首个位置）。"""
    if lang == "zh":
        return sentence.index(word)
    match = re.search(rf"\b{re.escape(word.lower())}\b", sentence.lower())
    return match.start() if match else 0


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
) -> dict:
    """R1：该引未引（三类检查里的"核心"，纵深全在这里）。

    返回一份**筛子账**（命中几句、各因何被豁免、最后报几处）——报告里如实写出来。
    ⭐ 只说"宁可少报"、不说**为什么少**，读起来与"什么都没查出来"一样；摆出账，
    用户才能判断我们是谨慎还是失灵（也是"词表自检"的第一步）。
    """
    marks = _NUMERIC_RE if style == "numeric" else _AUTHOR_YEAR_RE
    self_refs = SELF_REFS[lang]
    hedges = HEDGES[lang]
    stats = {"markers": 0, "cited": 0, "hedged": 0, "self_ref": 0, "reported": 0}

    for offset, sentence in split_sentences(doc_text):
        hit = next(
            (word for word in MARKERS[lang] if _contains(sentence, word, lang)), None
        )
        if hit is None:
            continue
        stats["markers"] += 1
        if marks.search(sentence):
            stats["cited"] += 1
            continue  # 已有标注 → 不报
        if any(_contains(sentence, word, lang) for word in hedges):
            stats["hedged"] += 1
            continue  # 模糊限定 → 不报
        # 自指豁免：**命中词前方 8 字内**（外加命中词自己）出现自指词 → 一律不报。
        # ⚠️ 这个窗口踩过两次，两次都是"看着合理其实错了"：
        #   ① 只看命中词之前的字：`本研究表明` 的「本研究」**跨在命中词边界上**，
        #      豁免永远不生效；
        #   ② 改成"句首 → 命中词"：窗口过大，于是
        #      `本研究提出的…把边界误差降低了` 这种（本研究在句首、离命中词很远）
        #      也被误免 —— **验收样例一的句 6 就是拿它卡这一条的**
        #      （文档把它列为"8 字窗太窄"的已知误报，该报出来）。
        hit_start = offset + _find_index(sentence, hit, lang)
        window = (doc_text or "")[
            max(0, hit_start - SELF_REF_WINDOW) : hit_start + len(hit)
        ]
        if any(_contains(window, word, lang) for word in self_refs):
            stats["self_ref"] += 1
            continue
        stats["reported"] += 1
        report.add(
            rule_code="R1",
            kind="missing_citation",
            severity="report",
            sentence=sentence,
            reason=f"命中标记词「{hit}」，句内无引用标注（{style}）",
            rule_ref="形态 §3.3 ①",
            suggest=_suggest_for(sentence, materials),
        )
    return stats


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


def _term_reason(
    term: str, sources: dict[str, set[str]], used: list[str]
) -> str | None:
    """一句话里"用了哪版、另一版来自哪篇"的如实并列；不该报时返回 `None`。

    - 同一句里**两版都在** → 报（最实的一种不一致）；
    - 只用了其中一版，而**另一版来自别篇被引文献** → 报；
    - 只用了其中一版，两版其实出自**同一篇** → 不报（那是那篇自己的写法）。
    """

    def describe(cn: str) -> str:
        return f"「{cn}」（来自《{'、'.join(sorted(sources[cn]))}》）"

    if len(used) >= 2:
        pairs = " 与 ".join(describe(cn) for cn in used[:2])
        return f"{term}：同一句里出现了 {len(used)} 种写法 —— {pairs}"

    only = used[0]
    others = [
        cn
        for cn, srcs in sources.items()
        if cn != only and any(src not in sources[only] for src in srcs)
    ]
    if not others:
        # 两版出自同一篇：那是那篇文献自己的写法，与我们这篇稿子无关
        return None
    return (
        f"{term}：这句用的是 {describe(only)}，另一篇被引文献用的是"
        f" {describe(others[0])} —— 两版并列，改不改由你定"
    )


def _run_term_consistency(
    report: _Report,
    *,
    doc_text: str,
    terms: list[dict] | None,
) -> dict:
    """R6：术语一致性（形态 §3.3 ② —— **并列摆出两处，不自动改**）。

    输入是**被引文献**理解层的术语表，已摊平成 `{term, cn, source_name}`。
    查两件事：

    ① **译名分歧**：同一个 `term` 在不同被引文献里有没有 ≥2 个不同的 `cn`；
    ② **正文用到了哪一版**：只在正文真的用到分歧里的版本时才报 ——
       正文一处都没用到时**不报**（文献层面的译名分歧与你的稿子无关），只记账。

    ⚠️ 没有术语表时**只写 notes、绝不报 `unknown` 发现**：那会给"有引用但那些文献
    没有术语表"的稿子凭空加一条 unknown，等于偷偷改验收数字（样例二正是这种）。
    """
    stats = {"terms": 0, "conflicts": 0, "sentences": 0, "reported": 0}
    if not terms:
        return stats

    # ① 收版本：`term -> {cn: {来源文献}}`（同一个 `cn` 可能出现在多篇里）
    versions: dict[str, dict[str, set[str]]] = {}
    for item in terms:
        term = str(item.get("term") or "").strip()
        cn = str(item.get("cn") or "").strip()
        # 空译名、或译名与原文同名 → 拿它去报只会制造噪音
        if not term or not cn or cn == term:
            continue
        source = str(item.get("source_name") or "").strip() or "（未记来源）"
        versions.setdefault(term, {}).setdefault(cn, set()).add(source)
    # 账上的 N = **去重后的术语条数**（一个 `term` 不管出现在几篇里都算一条）——
    # 这样多引一篇也不会把 N 灌大，"比对了几条术语"读起来才是那个意思。
    stats["terms"] = len(versions)

    conflicts = {term: cns for term, cns in versions.items() if len(cns) >= 2}
    stats["conflicts"] = len(conflicts)
    if not conflicts:
        return stats

    # ② 逐句找"这句用了分歧里的哪几版"；一句话最多一条 finding
    #    （指纹是 `(规则号, 句子)`，同一句报两条会让处置认不出是哪一条）
    for _, sentence in split_sentences(doc_text):
        used: dict[str, list[str]] = {}
        for term, cns in conflicts.items():
            hit = [cn for cn in cns if _contains(sentence, cn, "zh")]
            if hit:
                used[term] = hit
        if not used:
            continue
        stats["sentences"] += 1
        parts: list[str] = []
        for term, hit in used.items():
            reason = _term_reason(term, versions[term], hit)
            if reason:
                parts.append(reason)
        if not parts:
            continue
        stats["reported"] += 1
        report.add(
            rule_code="R6",
            kind="term_inconsistent",
            severity="report",
            sentence=sentence,
            reason="；".join(parts),
            rule_ref="形态 §3.3 ② 依据＝被引文献术语表（并列摆出，不自动改）",
        )
    return stats


def run_check(
    doc_text: str,
    *,
    citations: list[dict] | None = None,
    materials: list[dict] | None = None,
    terms: list[dict] | None = None,
) -> dict:
    """跑一次收口检查。

    - `doc_text`：稿子正文（契约 N22 的入参）；
    - `citations`：引文列表，每条至少带 `order` 与 `csl_json`；
    - `materials`：素材卡列表（给「该引未引」挑候选出处）；
    - `terms`：**被引文献**的术语表（摊平成 `{term, cn, source_name}`）—— 给 R6 用。

    ⭐ 四个入参**都可以缺**：缺了不是报错，而是少做那几条能做的检查并如实说明。
    """
    citations = citations or []
    materials = materials or []
    terms = terms or []
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
        stats = _run_missing_citation(
            report, doc_text=doc_text, lang=lang, style=style, materials=materials
        )
        # ⭐ **筛子账**：把"为什么只报这么少"如实写出来（宁可少报要让人看得见为什么少）
        notes.append(
            "该引未引：命中标记词 {markers} 句——已有引用 {cited}、含模糊限定 {hedged}、"
            "属作者自指 {self_ref}，报出 {reported} 处".format(**stats)
        )
        if stats["markers"] and not stats["reported"]:
            notes.append(
                "（本篇命中标记词的句子全部被豁免：有引用 / 模糊限定 / 作者自指——"
                "**不是失灵，是不硬报**）"
            )

    _run_citation_format(report, doc_text=doc_text, citations=citations)
    _run_csl_fields(report, citations=citations)

    # ⭐ R6：三种情况分开说 —— **没数据时只如实说明，绝不报 finding**
    # （报 `unknown` 会给"有引用但那些文献没有术语表"的稿子凭空加一条；验收样例二
    #   正是这种：有引用、没术语表，它那 N=2 不许被这一项改掉）
    if not citations:
        notes.append("术语一致性：草稿还没有引用，没有可比的术语表——这一项没判")
    elif not terms:
        notes.append("术语一致性：被引文献还没有术语表，这一项没判")
    else:
        term_stats = _run_term_consistency(report, doc_text=doc_text, terms=terms)
        # 与 R1 同一本账的口径：把"为什么只报这么少"摆出来
        notes.append(
            "术语一致性：比对 {terms} 条术语——译名分歧 {conflicts} 组、"
            "正文命中 {sentences} 句，报出 {reported} 处".format(**term_stats)
        )
        if term_stats["conflicts"] and not term_stats["sentences"]:
            notes.append(
                "（译名有分歧，但正文一处都没用到——**不是失灵，是不硬报**）"
            )

    reported = sum(1 for item in report.findings if item["severity"] == "report")
    unknown = sum(1 for item in report.findings if item["severity"] == "unknown")
    return {
        "ruleset_version": RULESET_VERSION,
        "run_id": None,
        "step": {"lang": lang, "citation_style": style, "notes": notes},
        "findings": report.findings,
        "summary": {"reported": reported, "unknown": unknown},
    }
