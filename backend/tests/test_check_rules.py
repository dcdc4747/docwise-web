"""收口检查引擎的用例（M4）。

重点盯**三处最容易做歪的地方**（形态 §3.3 的两个盲区 + "宁可少报"）：

- **E2 引用制式**：一份**著者-出版年制**的稿子（全文没有 `[n]`）**不许被全部误报**
  ——验收样例里这一篇就是判据核心（没有这道闸，它会被爆出 4 处、全是误报）；
- **E1 语言**：**英文稿不许静默失效**（词表是中文的，一句都报不出来还说支持，
  比报错更危险）；
- **自指豁免**："本研究表明…"是作者自己的工作 → **一律不报**；
- 以及"判不出就说判不出"（`unknown` 是一等公民，不是静默跳过）。
"""

from __future__ import annotations

import pytest

from app.check.engine import (
    detect_citation_style,
    detect_language,
    run_check,
    split_sentences,
)
from app.check.rules import HEDGES, RULES, RULES_BY_CODE, SELF_REF_WINDOW, SELF_REFS

ZH_NUMERIC = (
    "本文研究酶催化反应的动力学。"
    "研究表明，温度升高会显著加快反应速率，但选择性下降[1]。"
    "有学者认为，溶剂极性对选择性有决定性影响[2-3]。"
    "我们前期实验发现，固定化酶在 45℃ 下最稳定。"
    "本研究表明，该体系存在明显的补偿效应。"
)

ZH_AUTHOR_YEAR = (
    "酶催化反应的动力学已有大量研究。"
    "研究表明，温度升高会加快反应速率（张三，2020）。"
    "有学者认为溶剂极性决定选择性（Smith，2019）。"
    "一般认为，固定化能提高稳定性（李四，2021）。"
    "相关研究显示，补偿效应普遍存在（Wang et al.，2022）。"
)

EN_NUMERIC = (
    "This work studies the kinetics of enzyme catalysis. "
    "Research shows that higher temperature accelerates the reaction "
    "but reduces selectivity [1]. "
    "Studies have shown that solvent polarity dominates the selectivity [2]. "
    "Our previous experiments found the enzyme most stable at 45 C. "
)

CITATIONS = [
    {"order": 1, "csl_json": {"type": "article-journal", "title": "Temperature"}},
    {"order": 2, "csl_json": {"type": "article-journal", "title": "Solvent"}},
    {"order": 3, "csl_json": {"type": "article-journal", "title": "Immobilization"}},
]

MATERIALS = [
    {
        "id": 7,
        "page": 3,
        "text_quote": "The reaction rate rises with temperature.",
        "translated_quote": "反应速率随温度升高而加快，但选择性下降。",
    },
    {
        "id": 9,
        "page": 2,
        "text_quote": "Stability is highest for the immobilized form.",
        "translated_quote": "固定化酶的稳定性最高。",
    },
]


# ⚠️ 判语言的阈值是 30 个可判字母、判制式要求**全篇至少有一处标注**：
# 样本太短、或一处标注都没有时，引擎会走"判不出 → 整族不判"那条路（那是**对的**），
# 所以下面凡是要验 R1 的样本，都补一句够长的正文 + 一处标注。
MARKED = "已有结果见[1]。"
ONE_CITATION = [
    {
        "order": 1,
        "csl_json": {
            "type": "article-journal",
            "title": "Temperature",
            "author": [{"literal": "X"}],
        },
    },
]
LONG_HEAD = "酶催化动力学的研究由来已久。"


def kinds(report: dict) -> list[str]:
    return [item["kind"] for item in report["findings"]]


def sentences_of(report: dict) -> str:
    return " ".join(item["sentence"] for item in report["findings"])


# ---------------------------------------------------------------- 判语言（E1）


def test_lang_zh():
    assert detect_language(ZH_NUMERIC)[0] == "zh"


def test_lang_en():
    assert detect_language(EN_NUMERIC)[0] == "en"


def test_lang_too_little_text_is_unknown():
    lang, evidence = detect_language("好。")
    assert lang == "unknown"
    assert "不足以判断" in evidence


# ---------------------------------------------------------------- 判制式（E2）


def test_style_numeric():
    assert detect_citation_style(ZH_NUMERIC)[0] == "numeric"


def test_style_author_year():
    assert detect_citation_style(ZH_AUTHOR_YEAR)[0] == "author-year"


def test_style_unknown_when_no_mark_at_all():
    style, evidence = detect_citation_style("这篇文章没有任何引用。")
    assert style == "unknown"
    assert "判不出引用制式" in evidence


# ---------------------------------------------------------------- R1 该引未引


def test_r1_only_reports_sentences_without_marks():
    report = run_check(ZH_NUMERIC, citations=CITATIONS, materials=MATERIALS)
    hits = sentences_of(report)
    assert "温度升高会显著加快反应速率" not in hits  # 有 [1]
    assert "溶剂极性对选择性有决定性影响" not in hits  # 有 [2-3]
    assert "本研究表明" not in hits  # 自指豁免
    assert "我们前期实验" not in hits


def test_r1_suggest_carries_page_and_quote():
    doc = LONG_HEAD + MARKED + "研究表明，温度升高会加快反应速率但选择性下降。"
    report = run_check(doc, citations=ONE_CITATION, materials=MATERIALS)
    finding = report["findings"][0]
    assert finding["kind"] == "missing_citation"
    assert finding["severity"] == "report"
    assert finding["suggest"]["material_id"] == 7
    assert finding["suggest"]["page"] == 3
    assert finding["suggest"]["quote"]


def test_r1_suggest_none_when_nothing_matches():
    doc = LONG_HEAD + MARKED + "研究表明，某种完全无关的现象存在。"
    report = run_check(doc, citations=ONE_CITATION, materials=[])
    assert report["findings"][0]["suggest"] is None


def test_r1_hedge_is_exempt():
    doc = LONG_HEAD + MARKED + "研究表明，该机制可能并不成立。"
    assert run_check(doc, citations=ONE_CITATION, materials=[])["findings"] == []


@pytest.mark.parametrize(
    "tail",
    ("本研究表明，该体系存在补偿效应。", "我们研究发现，该体系存在补偿效应。"),
)
def test_r1_self_reference_is_exempt(tail):
    doc = LONG_HEAD + MARKED + tail
    assert run_check(doc, citations=ONE_CITATION, materials=[])["findings"] == []


def test_e2_author_year_is_not_reported():
    """⭐ 没有这道闸，这一篇会被"无 `[n]` → 报"全部误报（验收样例的 N=4、M=0）。"""
    report = run_check(ZH_AUTHOR_YEAR)
    assert report["step"]["citation_style"] == "author-year"
    assert report["summary"]["reported"] == 0
    assert report["summary"]["unknown"] == 0


def test_e1_english_is_not_silently_ignored():
    """⭐ 英文稿必须报得出来（词表是中文的话，这里会是 0 条）。"""
    report = run_check(EN_NUMERIC)
    assert report["step"]["lang"] == "en"
    assert report["summary"]["reported"] >= 1


def test_unknown_style_goes_to_unknown_bucket():
    """⭐ 制式判不出时整族归 unknown，而不是硬报。"""
    doc = (
        "酶催化反应在工业上应用广泛，相关数据积累较多。"
        "研究表明，温度会加快反应速率。"
        "有学者认为溶剂极性更关键。"
    )
    report = run_check(doc)
    assert report["step"]["citation_style"] == "unknown"
    assert report["summary"]["reported"] == 0
    assert report["summary"]["unknown"] == 1
    assert kinds(report) == ["unknown"]
    assert "整族不判" in report["findings"][0]["reason"]


# ---------------------------------------------------------------- R2–R5 格式


def test_r2_number_without_entry():
    report = run_check("研究表明，温度会加快反应速率[9]。", citations=CITATIONS)
    assert "missing_citation" in kinds(report)
    assert any("[9]" in item["sentence"] for item in report["findings"])


def test_r3_entry_never_cited():
    report = run_check("研究表明，温度会加快反应速率[1]。", citations=CITATIONS)
    reasons = " ".join(item["reason"] for item in report["findings"])
    assert "从没被引用过" in reasons


def test_r4_gap_in_numbering():
    doc = "研究表明，温度会加快反应速率[1]。有学者认为溶剂更关键[4]。"
    report = run_check(doc, citations=CITATIONS)
    assert any(item["rule_id"] == "R4" for item in report["findings"])
    assert "缺号" in sentences_of(report)


def test_r5_incomplete_entry_fields():
    broken = [{"order": 1, "csl_json": {"type": "article-journal"}}]
    report = run_check("研究表明，温度会加快反应速率[1]。", citations=broken)
    finding = next(item for item in report["findings"] if item["rule_id"] == "R5")
    assert "title" in finding["reason"]
    assert "author" in finding["reason"]


def test_r4_range_1_to_3_is_expanded():
    citations = [
        {
            "order": n,
            "csl_json": {
                "type": "article-journal",
                "title": f"T{n}",
                "author": [{"literal": "X"}],
            },
        }
        for n in (1, 2, 3)
    ]
    report = run_check("研究表明，温度会加快反应速率[1-3]。", citations=citations)
    assert report["summary"]["reported"] == 0


# ---------------------------------------------------------------- 报告本身


def test_report_shape_follows_contract():
    report = run_check(ZH_NUMERIC, citations=CITATIONS, materials=MATERIALS)
    assert set(report) == {"ruleset_version", "run_id", "step", "findings", "summary"}
    assert set(report["step"]) >= {"lang", "citation_style", "notes"}
    assert set(report["summary"]) == {"reported", "unknown"}
    assert report["ruleset_version"] >= 1
    expected = {
        "id",
        "fingerprint",
        "rule_id",
        "kind",
        "severity",
        "sentence",
        "reason",
        "suggest",
        "rule_ref",
    }
    for item in report["findings"]:
        assert set(item) >= expected
        assert item["severity"] in {"report", "unknown"}


def test_severity_has_only_two_levels():
    report = run_check(ZH_NUMERIC, citations=CITATIONS, materials=MATERIALS)
    assert {item["severity"] for item in report["findings"]} <= {"report", "unknown"}


def test_fingerprint_is_stable_across_runs():
    first = run_check("研究表明，温度会加快反应速率。", citations=[])
    second = run_check("研究表明，温度会加快反应速率。", citations=[])
    assert first["findings"][0]["fingerprint"] == second["findings"][0]["fingerprint"]
    assert first["findings"][0]["fingerprint"] != ""


def test_fingerprint_uses_rule_and_sentence():
    """换一条规则命中同一句 → 指纹不同（不然"这条我认过了"会串味）。"""
    doc = "研究表明，温度会加快反应速率[9]。"
    report = run_check(doc, citations=[])
    prints = {item["rule_id"]: item["fingerprint"] for item in report["findings"]}
    assert len(set(prints.values())) == len(prints)


def test_split_sentences_keeps_offsets():
    parts = split_sentences("第一句。第二句！\n第三句")
    assert [text for _, text in parts] == ["第一句。", "第二句！", "第三句"]


def test_empty_text_reports_unknown_not_crash():
    report = run_check("")
    assert report["step"]["lang"] == "unknown"
    assert report["summary"]["reported"] == 0
    assert report["summary"]["unknown"] == 1


def test_no_rule_is_left_disabled():
    """⭐ **没有未启用的规则了**（R6 术语一致性已启用）。

    这条原来断言"R6 还没启用"——那是个占位。现在把它翻过来：规则表里不该再留
    一条"写了但不跑"的规则（骗自己也骗读者），同时钉住 R6 的 `kind` 名。
    """
    disabled = {rule["code"] for rule in RULES if not rule["enabled"]}
    assert disabled == set()
    assert RULES_BY_CODE["R6"]["kind"] == "term_inconsistent"
    # 这篇的文献没有术语表 → R6 一条都不该报（只进筛子账）
    report = run_check(ZH_NUMERIC, citations=CITATIONS, materials=MATERIALS)
    assert "term_inconsistent" not in kinds(report)


# ------------------------------------------------- 模糊词表（words/hedges，MIT）

# 英文样本要**够长**（判语言要 ≥30 个字母）
# 且**带一处引用标注**（否则制式判不出、整族不判）
MARKED_EN = "Prior work is summarized elsewhere [1]."
ONE_EN_CITATION = [
    {
        "order": 1,
        "csl_json": {
            "type": "article-journal",
            "title": "T",
            "author": [{"literal": "X"}],
        },
    }
]


@pytest.mark.parametrize(
    "hedge",
    ("presumably", "seems", "could", "roughly", "unlikely", "more or less"),
)
def test_new_en_hedges_do_actually_exempt(hedge):
    """新收的英文模糊词**必须真的能豁免**（收了不生效＝白收）。

    ⭐ 用**差分**验，而不是"结果为空就算过"：同一句话**去掉那个模糊词就该报**——
    这才证明是它在起作用，而不是因为别的原因碰巧没报。
    """
    with_hedge = f"{MARKED_EN} Studies reported that the effect was {hedge} small here."
    without_hedge = f"{MARKED_EN} Studies reported that the effect was small here."
    assert run_check(with_hedge, citations=ONE_EN_CITATION)["findings"] == []
    report = run_check(without_hedge, citations=ONE_EN_CITATION)
    assert report["summary"]["reported"] == 1


@pytest.mark.parametrize(
    "word",
    ("always", "actually", "really", "quite", "most", "several", "about"),
)
def test_over_suppressing_words_stay_out(word):
    """程度/频率/数量词**坚决不收**：收了等于把「没引用」洗成「不用引用」。"""
    assert word not in HEDGES["en"]


@pytest.mark.parametrize("word", ("found", "suggested", "noted", "argued", "claimed"))
def test_reporting_verbs_are_markers_not_hedges(word):
    """报告动词两边都当词＝一命中就被豁免，**永远报不出「该引未引」**。"""
    assert word not in HEDGES["en"]
    doc = f"{MARKED_EN} Studies {word} that the effect is large in this setting."
    assert run_check(doc, citations=ONE_EN_CITATION)["summary"]["reported"] == 1


@pytest.mark.parametrize("word", ("says", "read", "indicate"))
def test_other_verbs_are_neither(word):
    """既不是标记词、也不该混进模糊词表（不然凭空多一堆豁免）。"""
    assert word not in HEDGES["en"]


# ------------------------------------------------- 筛子账（写进 step.notes）


def test_ledger_is_reported_in_notes():
    """⭐ 报告要如实写"命中几句、各因何被豁免、报了几处"。

    ZH_NUMERIC 这篇：句 2 / 句 3 有引用，句 4「我们」自指、句 5「本研究表明」也是自指
    → 命中 4 句、报出 0 处（**这正是"宁可少报"该有的样子，账要摆出来**）。
    """
    report = run_check(ZH_NUMERIC, citations=CITATIONS, materials=MATERIALS)
    ledger = next(n for n in report["step"]["notes"] if n.startswith("该引未引："))
    assert "命中标记词 4 句" in ledger
    assert "已有引用 2" in ledger
    assert "属作者自指 2" in ledger
    assert "报出 0 处" in ledger


def test_ledger_says_loudly_when_everything_was_exempted():
    """全部被豁免时要说清「不是失灵」——否则读起来跟"什么都没查出来"一样。

    ⚠️ 只盯 **R1**：`summary.reported` 是全规则合计，这份极简引文还会触发 R5（缺字段），
    拿全局计数来验"该引未引"会把两件事搅在一起。
    """
    report = run_check(ZH_NUMERIC, citations=CITATIONS, materials=MATERIALS)
    assert [f for f in report["findings"] if f["rule_id"] == "R1"] == []
    assert any("不是失灵" in note for note in report["step"]["notes"])
    # 真报了 R1 的稿子就不该出现这句话（别把它当固定文案）
    reported = run_check(
        f"{MARKED_EN} Studies reported that the effect is large here.",
        citations=ONE_EN_CITATION,
    )
    r1 = [f for f in reported["findings"] if f["rule_id"] == "R1"]
    assert len(r1) == 1
    assert not any("不是失灵" in note for note in reported["step"]["notes"])


# ------------------------------------------------- 词表自身的毛病（可达性）


def test_en_self_ref_phrases_are_dead_under_the_eight_char_window():
    """⚠️ 记录一个**已知缺陷**：英文自指短语比 8 字窗长，实际永远豁免不了。

    窗口是「命中词前 8 个字符 + 命中词本身」，所以**长度超过 8 的自指项**（短语形态）
    在英文里基本进不来 —— 真正生效的只有 `we` / `our`（验收样例二靠的就是 `We`）。

    ⚠️ **故意不改**：放宽窗口会让验收样例一的句 6（"本研究提出的…降低了"）从"报"
    变成"不报"，而那一处正是样例文档**要求暴露的已知误报** —— 改了等于把验收数字
    偷偷改掉。所以这里把它**钉成记录在案的事实**，而不是悄悄放过。
    """
    dead = {w for w in SELF_REFS["en"] if len(w) > SELF_REF_WINDOW}
    assert dead == {"this study", "this work", "this paper", "the present study"}
    assert {w for w in SELF_REFS["en"] if len(w) <= SELF_REF_WINDOW} == {"we", "our"}


def test_short_en_self_ref_still_works():
    """短的自指词是好的（英语稿就靠它）。"""
    doc = LONG_HEAD + MARKED + "We found an average improvement of 4.7% here."
    assert run_check(doc, citations=ONE_CITATION, materials=[])["findings"] == []


# ------------------------------------------------- 术语一致性（R6）


def _term_findings(report: dict) -> list[dict]:
    return [item for item in report["findings"] if item["kind"] == "term_inconsistent"]


def _term_ledger(report: dict) -> str:
    """R6 的那本筛子账（写进 `step.notes`）。"""
    return next(
        note for note in report["step"]["notes"] if note.startswith("术语一致性：")
    )


def _term_report(doc: str, terms: list[dict]) -> dict:
    """跑一次带术语表的检查（R6 用例都从这里过，口径只写一处）。"""
    return run_check(doc, citations=CITATIONS, terms=terms)


# 两篇被引文献把**同一个术语**译成了两个名字（跨文献译名分歧）
TERMS_CONFLICT = [
    {
        "term": "self-supervised pretraining",
        "cn": "自监督预训练",
        "source_name": "survey_2024.pdf",
        "task_id": 11,
    },
    {
        "term": "self-supervised pretraining",
        "cn": "自监督式预训练",
        "source_name": "methods_2023.pdf",
        "task_id": 12,
    },
]


def test_r6_reports_the_version_used_and_who_else_uses_the_other():
    """⭐ 正文用了其中一版、另一版来自**别篇**被引文献 → 报，且两版并列。"""
    doc = LONG_HEAD + MARKED + "我们采用自监督预训练来缓解标注不足。"
    report = _term_report(doc, TERMS_CONFLICT)

    hits = _term_findings(report)
    assert len(hits) == 1
    assert hits[0]["rule_id"] == "R6"
    assert hits[0]["severity"] == "report"
    assert "自监督预训练" in hits[0]["sentence"]
    # 两版并列 + 哪版来自哪篇（**不说"错了"、不替你改**）
    assert "自监督预训练" in hits[0]["reason"]
    assert "自监督式预训练" in hits[0]["reason"]
    assert "survey_2024.pdf" in hits[0]["reason"]
    assert "methods_2023.pdf" in hits[0]["reason"]
    assert "改不改由你定" in hits[0]["reason"]


def test_r6_reports_when_one_sentence_holds_both_versions():
    """同一句里两版并存 —— 最实的一种不一致，也要报。"""
    doc = LONG_HEAD + MARKED + "有人写自监督预训练，有人写自监督式预训练。"
    report = _term_report(doc, TERMS_CONFLICT)

    hits = _term_findings(report)
    assert len(hits) == 1
    assert "2 种写法" in hits[0]["reason"]
    assert "自监督预训练" in hits[0]["reason"]
    assert "自监督式预训练" in hits[0]["reason"]


def test_r6_stays_silent_when_the_draft_uses_neither_version():
    """正文一处都没用到 → **不报**（文献层面的分歧与你的稿子无关），只记账。"""
    doc = LONG_HEAD + MARKED + "本文只讨论数据增强策略。"
    report = _term_report(doc, TERMS_CONFLICT)

    assert _term_findings(report) == []
    ledger = _term_ledger(report)
    # ⚠️ 账上的 N 是**去重后的术语条数**：`TERMS_CONFLICT` 两篇论文里的同一个 `term`
    # 只算一条（多引一篇不该把 N 灌大）。
    assert "比对 1 条术语" in ledger
    assert "译名分歧 1 组" in ledger
    assert "正文命中 0 句" in ledger
    assert "报出 0 处" in ledger
    assert any("不是失灵" in note for note in report["step"]["notes"])


def test_r6_without_terms_explains_in_notes_and_adds_no_unknown():
    """⭐ **有引用、但那些文献没有术语表** → 只写 notes。

    验收样例二正是这种稿子：**不许报 `unknown` 发现**（那等于偷偷改它的 N）。
    """
    report = run_check(ZH_NUMERIC, citations=CITATIONS, materials=MATERIALS)
    assert _term_findings(report) == []
    assert any("被引文献还没有术语表" in note for note in report["step"]["notes"])
    assert report["summary"]["unknown"] == 0


def test_r6_without_citations_only_explains_in_notes():
    """**没有引用** → 只写 notes，一条都不报（连术语表都不比）。"""
    doc = LONG_HEAD + MARKED + "我们采用自监督预训练来缓解标注不足。"
    report = run_check(doc, materials=MATERIALS, terms=TERMS_CONFLICT)

    assert _term_findings(report) == []
    assert any("草稿还没有引用" in note for note in report["step"]["notes"])


def test_r6_skips_blank_and_same_as_term_translations():
    """`cn` 为空串、或与 `term` 同名 → 跳过（拿它去报只会制造噪音）。"""
    terms = [
        {"term": "noise", "cn": "", "source_name": "a.pdf", "task_id": 1},
        {"term": "noise", "cn": "noise", "source_name": "b.pdf", "task_id": 2},
    ]
    doc = LONG_HEAD + MARKED + "noise 这个词在正文里出现过。"
    report = _term_report(doc, terms)

    assert _term_findings(report) == []
    assert "比对 0 条术语" in _term_ledger(report)


def test_r6_same_paper_two_names_is_not_reported():
    """两版出自**同一篇** → 不报（那是那篇自己的写法，与我们这篇稿子无关）。"""
    terms = [
        {"term": "X", "cn": "甲方案", "source_name": "same.pdf", "task_id": 1},
        {"term": "X", "cn": "乙方案", "source_name": "same.pdf", "task_id": 1},
    ]
    doc = LONG_HEAD + MARKED + "我们使用甲方案来完成这件事。"
    report = _term_report(doc, terms)

    assert _term_findings(report) == []
    ledger = _term_ledger(report)
    assert "译名分歧 1 组" in ledger  # 分歧照样计入账
    assert "正文命中 1 句" in ledger
    assert "报出 0 处" in ledger


def test_r6_ledger_counts_sentences_and_reports():
    """一本账：比对几条、分歧几组、正文命中几句、报了几处。"""
    doc = (
        LONG_HEAD
        + MARKED
        + "甲方案用了自监督预训练。"
        + "乙方案用了自监督式预训练。"
    )
    report = _term_report(doc, TERMS_CONFLICT)

    ledger = _term_ledger(report)
    assert "比对 1 条术语" in ledger  # 去重后的术语条数（见上一条用例的说明）
    assert "译名分歧 1 组" in ledger
    assert "正文命中 2 句" in ledger
    assert "报出 2 处" in ledger
    assert len(_term_findings(report)) == 2
