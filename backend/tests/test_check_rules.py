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
from app.check.rules import RULES

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


def test_disabled_rule_never_appears():
    disabled = {rule["code"] for rule in RULES if not rule["enabled"]}
    assert disabled == {"R6"}  # 术语一致性本轮没启用（要术语表对齐）
    report = run_check(ZH_NUMERIC, citations=CITATIONS, materials=MATERIALS)
    assert not (disabled & {item["rule_id"] for item in report["findings"]})
