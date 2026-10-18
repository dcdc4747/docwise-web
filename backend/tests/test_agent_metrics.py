"""术语一致率的单测。

口径都是"算出来的数字"，不是观感——所以每条规则都钉一个
用例：只出现规范写法、只出现别名、同段混用、没出现、
空正文、引用标记、例子截断、缺 `zh` 的词条。

有几条边界值得记住：
- `missing` 不进分母（没谈到不等于写错）；
- 分母为 0 时 `rate` 必须是 `None`，不许用 1.0 冒充全对；
- 同段混用才是 `conflict`，跨段各用一种写法按 `alias` 算。
"""

from __future__ import annotations

from app.agent.metrics import format_term_report, term_consistency

TERMS = [{"term": "chiral", "zh": "手性", "aliases": ["手征"]}]


def test_only_canonical_is_ok() -> None:
    result = term_consistency("手性中心很清楚。", TERMS)
    row = result["rows"][0]
    assert row["status"] == "ok"
    assert row["hits"] == 1
    assert row["alias_hits"] == 0
    assert result["rate"] == 1.0
    assert result["total"] == 1
    assert result["ok"] == 1


def test_only_alias_is_alias() -> None:
    result = term_consistency("手征中心很清楚。", TERMS)
    row = result["rows"][0]
    assert row["status"] == "alias"
    assert row["hits"] == 0
    assert row["alias_hits"] == 1
    assert row["used_aliases"] == ["手征"]
    assert result["rate"] == 0.0
    assert result["total"] == 1
    assert result["ok"] == 0


def test_conflict_in_same_paragraph() -> None:
    result = term_consistency("这一段先说手性，后面又写手征。", TERMS)
    row = result["rows"][0]
    assert row["status"] == "conflict"
    assert row["hits"] == 1
    assert row["alias_hits"] == 1
    assert result["rate"] == 0.0
    assert result["total"] == 1


def test_forms_in_different_paragraphs_are_alias_not_conflict() -> None:
    result = term_consistency("第一段说手性。\n第二段写手征。", TERMS)
    row = result["rows"][0]
    assert row["status"] == "alias"
    assert row["hits"] == 1
    assert row["alias_hits"] == 1


def test_missing_term_stays_out_of_denominator() -> None:
    terms = TERMS + [{"term": "enzyme", "zh": "酶"}]
    result = term_consistency("手性中心。", terms)
    assert result["total"] == 1
    assert result["ok"] == 1
    assert len(result["rows"]) == 2
    missing = result["rows"][1]
    assert missing["status"] == "missing"
    assert missing["hits"] == 0
    assert missing["alias_hits"] == 0
    assert missing["examples"] == []


def test_rate_none_when_no_term_appears() -> None:
    result = term_consistency("这里没有术语。", TERMS)
    assert result["rate"] is None
    assert result["total"] == 0
    assert result["ok"] == 0
    assert result["rows"][0]["status"] == "missing"
    assert "无法计算" in format_term_report(result)


def test_empty_text_and_empty_terms() -> None:
    empty_text = term_consistency("", TERMS)
    assert empty_text["rate"] is None
    assert empty_text["total"] == 0
    assert empty_text["rows"][0]["status"] == "missing"

    empty_terms = term_consistency("正文里有 chiral", [])
    assert empty_terms == {"rate": None, "total": 0, "ok": 0, "rows": []}


def test_citation_markers_do_not_change_counts() -> None:
    zh = term_consistency("手性[1]与手性[2]都出现。", TERMS)
    assert zh["rows"][0]["hits"] == 2
    assert zh["rows"][0]["status"] == "ok"

    # 英文正文用英文规范写法（`hits` 只数 `zh`，不数 `term`）
    en = term_consistency(
        "chiral[1] and CHIRAL[2].", [{"term": "chiral", "zh": "chiral"}]
    )
    assert en["rows"][0]["hits"] == 2
    assert en["rows"][0]["status"] == "ok"


def test_examples_bounded_to_two_and_forty_chars() -> None:
    text = "前" * 60 + "手性" + "后" * 60
    examples = term_consistency(text, TERMS)["rows"][0]["examples"]
    assert 1 <= len(examples) <= 2
    assert all(len(example) <= 40 for example in examples)
    assert any("…" in example for example in examples)

    many = "\n".join(f"第{i}段写手性" for i in range(6))
    examples = term_consistency(many, TERMS)["rows"][0]["examples"]
    assert len(examples) == 2


def test_repeated_hits_counted() -> None:
    result = term_consistency("手性，手性，再一个手性。", TERMS)
    row = result["rows"][0]
    assert row["hits"] == 3
    assert row["status"] == "ok"


def test_english_match_is_case_insensitive_and_word_bounded() -> None:
    terms = [{"term": "chiral", "zh": "chiral"}]
    result = term_consistency(
        "Chiral and CHIRAL, but not chirality.", terms
    )
    row = result["rows"][0]
    assert row["hits"] == 2
    assert row["status"] == "ok"


def test_missing_zh_falls_back_to_term() -> None:
    terms = [{"term": "chiral", "aliases": ["手征"]}]
    result = term_consistency("chiral 与 手征 同时出现。", terms)
    row = result["rows"][0]
    assert row["zh"] == "chiral"
    assert row["hits"] == 1
    assert row["alias_hits"] == 1
    assert row["status"] == "conflict"


def test_invalid_term_entries_are_skipped() -> None:
    terms = [{"aliases": ["孤儿别名"]}, "not-a-dict", {"term": "  "}]
    assert term_consistency("随便写点正文", terms) == {
        "rate": None,
        "total": 0,
        "ok": 0,
        "rows": [],
    }


def test_format_report_shows_percentage_and_conflict_advice() -> None:
    terms = [
        {"term": "chiral", "zh": "手性", "aliases": ["手征"]},
        {"term": "enzyme", "zh": "酶"},
        {"term": "catalyst", "zh": "催化剂"},
        {"term": "solvent", "zh": "溶剂"},
    ]
    result = term_consistency(
        "手性 与 手征 混用；酶；催化剂；溶剂。", terms
    )
    assert result["rate"] == 0.75
    assert format_term_report(result) == (
        "术语一致率 75%（3/4）；"
        "「chiral」同时出现「手性」与「手征」，建议统一"
    )


def test_format_report_shows_alias_advice() -> None:
    report = format_term_report(term_consistency("手征中心。", TERMS))
    assert report == (
        "术语一致率 0%（0/1）；"
        "「chiral」用了别名「手征」，建议统一为「手性」"
    )


def test_format_report_all_consistent() -> None:
    report = format_term_report(term_consistency("手性中心。", TERMS))
    assert report == "术语一致率 100%（1/1），术语用法一致"


def test_conflict_examples_show_both_forms() -> None:
    result = term_consistency("先说手性，再说手征。", TERMS)
    examples = result["rows"][0]["examples"]
    assert examples
    assert any("手性" in item and "手征" in item for item in examples)


def test_format_report_tolerates_empty_dict() -> None:
    assert format_term_report({}) == "术语一致率无法计算（术语表为空）"


def test_format_report_tolerates_bad_rate() -> None:
    result = {"rate": "不是数字", "total": 1, "ok": 1, "rows": []}
    assert "无法计算" in format_term_report(result)
