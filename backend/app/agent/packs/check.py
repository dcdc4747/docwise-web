"""收口检查工具包：把"校对"做成模型能调的一只**只读**工具。

复用什么（**不重复造轮子**）：

- 编号断档、条目字段：`app/check/engine.py` 的 `run_check`（纯函数、不碰库）；
- 术语比对：同一份引擎的 R6（被引文献术语表 → 译名分歧）。

本文件只补两处引擎没覆盖的：

1. **空引用措辞**（"相关研究表明"…）：引擎 R1 要先判出引用制式才跑，
   一份还没插过任何引文的草稿会整族跳过；这里按句正则兜底。
2. **同一术语的原文与译名在正文里混用**：引擎 R6 只比不同文献的中文译名，
   不比 "chiral / 手性" 这种原文-译名同现。

只读契约：只 SELECT；不写库、不改稿、不落 `CheckRun`。
⚠️ 不许 import pydantic_ai（结构用例钉着）。
"""

from __future__ import annotations

import json
import re

from sqlalchemy import select

from ...check.engine import run_check as audit_text
from ...check.engine import split_sentences
from ...check.rules import AUTHOR_YEAR_RE, NUMERIC_RE
from ...db import SessionLocal
from ...models import Citation, Draft, Material, TaskUnderstanding
from ..contracts import Pack, ToolResult, ToolSpec

# 单次最多回多少条：多了会挤掉模型的上下文，但统计仍按全量算
_MAX_FINDINGS = 60
_DETAIL_MAX = 200
_SENTENCE_MAX = 120
# 自指豁免窗口：空引用措辞前方这么多字内出现"本研究"就不算别人的断言
_SELF_REF_WINDOW = 6

# 一篇文章最多扫多少张素材卡（只影响"建议引哪条"，不影响判不判）
_MATERIAL_SCAN = 200

# 结果里 kind 的固定顺序（前端/模型都按这个序读，别用 dict 插入序去猜）
_KIND_ORDER = (
    "citation_number",
    "unsourced_claim",
    "term_inconsistent",
    "citation_format",
    "unknown",
)

# 引擎规则号 → (本工具的 kind, level)
_ENGINE_KIND: dict[str, tuple[str, str]] = {
    "R1": ("unsourced_claim", "warn"),
    "R2": ("citation_number", "error"),
    "R3": ("citation_number", "warn"),
    "R4": ("citation_number", "warn"),
    "R5": ("citation_format", "info"),
    "R6": ("term_inconsistent", "warn"),
    "R7": ("unknown", "info"),
}

_NUMERIC_RE = re.compile(NUMERIC_RE)
_AUTHOR_YEAR_RE = re.compile(AUTHOR_YEAR_RE)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_SELF_REF_RE = re.compile(
    r"\b(?:we|our|this study|this work|this paper)\b", re.IGNORECASE
)

# 空引用措辞：只要句子里出现这些词、又没有引用标注，就是"无出处的断言"。
# 长词放前面（"已有研究表明"先于"已有研究"），否则只会匹配到短的那截。
_UNSOURCED_PHRASES = (
    "相关研究表明",
    "相关研究显示",
    "相关研究指出",
    "已有研究表明",
    "已有研究显示",
    "已有研究指出",
    "已有研究",
    "调查研究表明",
    "调查研究显示",
    "调查结果表明",
    "调查显示",
    "研究表明",
    "研究显示",
    "研究指出",
    "数据显示",
    "统计显示",
    "统计表明",
    "文献表明",
    "文献显示",
    "studies have shown",
    "studies show",
    "research has shown",
    "research shows",
    "research indicates",
    "it has been shown",
    "evidence suggests",
)
_UNSOURCED_RE = re.compile(
    "|".join(
        sorted(
            (re.escape(phrase) for phrase in _UNSOURCED_PHRASES),
            key=len,
            reverse=True,
        )
    ),
    re.IGNORECASE,
)

_CN_SELF_REFS = ("我们", "本文", "本工作", "本研究", "本课题组", "笔者", "本团队")


def _draft_id_of(args, scope) -> int | None:
    """从容错的 `args` 与 `ctx.scope` 里取 draft_id；取不到就返回 None。

    `args` 可能是 None / 字符串 / 数字写着"不是数字"——都不许抛异常；
    参数写坏了就退回 scope 里那篇，而不是把整次调用打死。
    """
    candidates = []
    if isinstance(args, dict):
        candidates.append(args.get("draft_id"))
    if isinstance(scope, dict):
        candidates.append(scope.get("draft_id"))
    for raw in candidates:
        if raw in (None, ""):
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def _citations_of(session, draft_id: int) -> list[dict]:
    """草稿的引文，摊成引擎要的形状（`order` + `csl_json`）。"""
    rows = session.scalars(
        select(Citation)
        .where(Citation.draft_id == draft_id)
        .order_by(Citation.order)
    ).all()
    return [
        {"order": row.order, "csl_json": row.csl_json or {}} for row in rows
    ]


def _materials_of(session, user_id: int) -> list[dict]:
    """本人的素材卡（没软删的、新的在前），给"该引未引"挑候选出处。"""
    rows = session.scalars(
        select(Material)
        .where(Material.user_id == user_id, Material.deleted_at.is_(None))
        .order_by(Material.created_at.desc())
        .limit(_MATERIAL_SCAN)
    ).all()
    return [
        {
            "id": row.id,
            "page": row.page,
            "text_quote": row.text_quote,
            "translated_quote": row.translated_quote,
        }
        for row in rows
    ]


def _parse_terms(raw: str | None) -> list[dict]:
    """`terms_json` 是理解层写进去的 JSON；读坏了就当没有，不抛异常。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(data, dict):
        data = data.get("terms") or []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _terms_of(session, user_id: int, draft_id: int) -> list[dict]:
    """被引文献的术语表，摊平成 `{term, cn, source_name}`（给术语比对用）。

    追溯链：`Citation.material_id` → `Material.task_id` →
    `task_understanding.terms_json`。**同一篇文献只收一次**（多张素材卡指向
    同一篇时会重复取到同一份术语表）。源文献已删（`task_id` 为 null）取不到，
    如实少比一篇，不猜。
    """
    rows = session.execute(
        select(
            Material.task_id,
            Material.source_name,
            TaskUnderstanding.terms_json,
        )
        .join(Citation, Citation.material_id == Material.id)
        .join(TaskUnderstanding, TaskUnderstanding.task_id == Material.task_id)
        .where(
            Citation.draft_id == draft_id,
            Material.user_id == user_id,
            Material.task_id.is_not(None),
        )
    ).all()

    out: list[dict] = []
    seen_tasks: set[int] = set()
    for task_id, source_name, terms_json in rows:
        if task_id in seen_tasks:
            continue
        seen_tasks.add(task_id)
        for item in _parse_terms(terms_json):
            term = str(
                item.get("term") or item.get("source") or item.get("en") or ""
            ).strip()
            cn = str(
                item.get("cn") or item.get("target") or item.get("zh") or ""
            ).strip()
            # 空条目、原文与译名完全一样：拿它去报只会制造噪音
            if not term or not cn or term == cn:
                continue
            out.append(
                {"term": term, "cn": cn, "source_name": source_name or ""}
            )
    return out


def _count(text: str, word: str) -> int:
    """数一个词在正文里出现几次；英文按词边界，中文按子串。"""
    if not word:
        return 0
    if _CJK_RE.search(word):
        return text.count(word)
    pattern = rf"\b{re.escape(word)}\b"
    return len(re.findall(pattern, text, re.IGNORECASE))


def _has_citation_marker(sentence: str) -> bool:
    """句内已经有 `[n]` 或「（作者，年份）」就算有出处。"""
    return bool(_NUMERIC_RE.search(sentence) or _AUTHOR_YEAR_RE.search(sentence))


def _has_self_ref(window: str) -> bool:
    """"本研究表明"是作者自己的工作，不该要求引用。"""
    if any(word in window for word in _CN_SELF_REFS):
        return True
    return bool(_LATIN_SELF_REF_RE.search(window))


def _phrase_findings(body: str) -> list[dict]:
    """空引用措辞：按句找，句内有引用标注或属自指的放过。"""
    findings: list[dict] = []
    for _, sentence in split_sentences(body):
        match = _UNSOURCED_RE.search(sentence)
        if match is None:
            continue
        if _has_citation_marker(sentence):
            continue
        start = match.start()
        window = sentence[
            max(0, start - _SELF_REF_WINDOW) : start + len(match.group(0))
        ]
        if _has_self_ref(window):
            continue
        phrase = match.group(0)
        findings.append(
            {
                "kind": "unsourced_claim",
                "level": "warn",
                "detail": (
                    f"「{phrase}」没有标注出处：{sentence[:_SENTENCE_MAX]}"
                )[:_DETAIL_MAX],
                "rule_id": "U1",
                "sentence": sentence[:_SENTENCE_MAX],
            }
        )
    return findings


def _term_findings(
    body: str, terms: list[dict], reported: set[str]
) -> list[dict]:
    """同一术语在正文里混用（原文与译名同现，或多个中文译名并存）。"""
    groups: dict[str, list[str]] = {}
    for item in terms:
        term = item["term"]
        cn = item["cn"]
        groups.setdefault(term, [])
        if cn not in groups[term]:
            groups[term].append(cn)

    findings: list[dict] = []
    for term, cns in groups.items():
        # 引擎 R6 已经报过这个术语（跨文献译名分歧）就不重复报
        if term in reported:
            continue
        used = [(cn, _count(body, cn)) for cn in cns]
        used = [(cn, count) for cn, count in used if count]
        english = _count(body, term)
        parts = [f"「{term}」×{english}"] if english else []
        parts.extend(f"「{cn}」×{count}" for cn, count in used)
        # 只用了一种写法就不算混用
        if len(parts) < 2:
            continue
        findings.append(
            {
                "kind": "term_inconsistent",
                "level": "warn",
                "detail": (
                    f"同一个术语在正文里有 {len(parts)} 种写法："
                    + "、".join(parts)
                    + "（依据被引文献的术语表）"
                )[:_DETAIL_MAX],
                "rule_id": "T1",
                "sentence": "",
            }
        )
    return findings


def _detail_of(finding: dict) -> str:
    """把引擎 finding 压成一句人话（保留句子片段，别只剩规则号）。"""
    rule_id = str(finding.get("rule_id") or "")
    reason = str(finding.get("reason") or "").strip()
    sentence = str(finding.get("sentence") or "").strip()
    # R7 的 sentence 是正文开头截断，不是"哪一句有问题"——别拿它当前缀
    if sentence and rule_id != "R7":
        return f"{sentence[:_SENTENCE_MAX]} —— {reason}"[:_DETAIL_MAX]
    return reason[:_DETAIL_MAX]


def _engine_findings(report: dict) -> list[dict]:
    """把引擎的 findings 映射成统一的 `{kind, level, detail}` 形状。"""
    findings: list[dict] = []
    for item in report.get("findings") or []:
        rule_id = str(item.get("rule_id") or "")
        mapped = _ENGINE_KIND.get(rule_id)
        if mapped is None:
            continue
        kind, level = mapped
        findings.append(
            {
                "kind": kind,
                "level": level,
                "detail": _detail_of(item),
                "rule_id": rule_id,
                "sentence": str(item.get("sentence") or "")[:_SENTENCE_MAX],
            }
        )
    return findings


def _reported_terms(report: dict) -> set[str]:
    """引擎 R6 报过的术语（reason 形如「chiral：…」），避免本地检查重复报。"""
    reported: set[str] = set()
    for item in report.get("findings") or []:
        reason = str(item.get("reason") or "")
        if item.get("rule_id") == "R6" and "：" in reason:
            reported.add(reason.split("：", 1)[0].strip())
    return reported


def _human_note(total: int, actionable: int, info: int) -> str:
    """`note` 只说人话：有多少条需要看一眼、多少条只是说明。"""
    if total == 0:
        return "没查出问题（能算的三类都算过了）"
    if actionable == 0:
        return f"没有需要改的；{info} 条说明（判不出的已如实标出）"
    if info:
        return f"{actionable} 处需要看一眼，另有 {info} 条说明"
    return f"{actionable} 处需要看一眼"


def run_check(ctx, args: dict | None = None) -> ToolResult:
    """跑一遍确定性检查（默认检查 `ctx.scope["draft_id"]` 那篇草稿）。

    判据（全部可算，不调模型）：

    - **编号断档**：正文 `[n]` 与 `citations.order` 对不上——
      引用了不存在的号 / 文献表条目没被引用 / 编号跳号；
    - **无出处的断言**：句子里出现"相关研究表明"这类措辞、又没有 `[n]`
      或「（作者，年份）」；自指（"本研究表明"）放过；
    - **术语不一致**：被引文献的 `terms_json` 里同一术语的中文译名在正文中
      并用了不止一种，或原文与译名同现。

    查不了就明说（`terms_note`），不瞎猜。
    """
    scope = getattr(ctx, "scope", None)
    draft_id = _draft_id_of(args, scope)
    if draft_id is None:
        return ToolResult(
            data="没有指定草稿",
            note="需要 draft_id（或从页面带 scope.draft_id）",
        )

    with SessionLocal() as session:
        draft = session.scalar(
            select(Draft).where(
                Draft.id == draft_id,
                Draft.user_id == ctx.user_id,
            )
        )
        # 别人的草稿一律当"找不到"——不暴露"存在但无权限"
        if draft is None:
            return ToolResult(
                data="找不到这篇草稿",
                note="可能已删除，或不是你自己的草稿",
            )
        body = draft.body_md or ""
        title = draft.title
        citations = _citations_of(session, draft_id)
        materials = _materials_of(session, ctx.user_id)
        terms = _terms_of(session, ctx.user_id, draft_id)

    if not terms:
        terms_note = "没找到可对照的术语表"
        if not citations:
            terms_note = "草稿还没有引用，没找到可对照的术语表"
    else:
        terms_note = f"对照了 {len({item['term'] for item in terms})} 条术语"

    findings: list[dict] = []
    if body.strip():
        report = audit_text(
            body,
            citations=citations,
            materials=materials,
            terms=terms,
        )
        findings = _engine_findings(report)
        seen = {
            item["sentence"].strip()[:60]
            for item in findings
            if item["kind"] == "unsourced_claim"
        }
        findings.extend(
            item
            for item in _phrase_findings(body)
            if item["sentence"].strip()[:60] not in seen
        )
        findings.extend(
            _term_findings(body, terms, _reported_terms(report))
        )

    order = {kind: index for index, kind in enumerate(_KIND_ORDER)}
    findings.sort(key=lambda item: order.get(item["kind"], len(order)))

    by_kind = {kind: 0 for kind in _KIND_ORDER}
    for item in findings:
        by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1
    total = len(findings)
    kept = findings[:_MAX_FINDINGS]
    truncated = total - len(kept)

    actionable = sum(
        1 for item in findings if item["level"] in ("error", "warn")
    )
    info = total - actionable
    if body.strip():
        human = _human_note(total, actionable, info)
    else:
        human = "草稿正文还是空的，没有可检查的内容"

    data = {
        "draft_id": draft_id,
        "title": title,
        "findings": kept,
        "summary": {"total": total, "by_kind": by_kind},
        "terms_note": terms_note,
        "truncated": truncated,
        "note": human,
    }
    return ToolResult(data=data, note=human)


PACK = Pack(
    name="check",
    tools=(
        ToolSpec(
            name="run_check",
            description=(
                "跑一遍确定性校对（不调模型、不改稿）：引文编号是否对得上、"
                "有没有没出处的断言、术语写法是否一致。默认检查当前草稿。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "integer",
                        "description": "草稿 id，省略就用当前草稿",
                    },
                },
            },
            handler=run_check,
            max_result_chars=4000,
        ),
    ),
)
