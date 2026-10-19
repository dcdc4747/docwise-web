"""「该引未引」规则检测的单测。

八条规则各钉一条正例或反例；重点是**别瞎报**：
已引的不报、自指的不报、标题行不报、判不出来不报。
"""

from __future__ import annotations

import pytest

from app.agent.citation_gaps import find_citation_gaps, summarize_gaps


def test_reporting_verb_is_flagged() -> None:
    body = "研究表明，睡眠不足会降低记忆力。"
    gaps = find_citation_gaps(body)
    assert len(gaps) == 1
    assert gaps[0]["sentence"] == body
    assert gaps[0]["reason"] == "引述他人研究的典型句式"
    assert gaps[0]["chars"] == len(body)
    assert gaps[0]["line_no"] == 1


def test_english_reporting_verb_is_flagged() -> None:
    gaps = find_citation_gaps("Studies show that sleep matters.")
    assert [gap["reason"] for gap in gaps] == ["引述他人研究的典型句式"]


def test_existing_citation_is_not_flagged() -> None:
    for body in (
        "研究表明，睡眠不足会降低记忆力[1]。",
        "研究表明，睡眠不足会降低记忆力[1,2]。",
        "研究表明，睡眠不足会降低记忆力[1-3]。",
        # 分隔符两侧有空格也算引用（规则 2 的宽松写法）
        "研究表明，睡眠不足会降低记忆力[1, 2]。",
    ):
        assert find_citation_gaps(body) == []


@pytest.mark.parametrize(
    "sentence",
    [
        "两组差异显著（p < 0.05）。",
        "风险比为 1.8（95% CI 1.1–2.9）。",
        "OR=2.4，说明关联更强。",
        "HR=0.7，干预组风险更低。",
        "样本量为 n=42。",
        "均值是 12.3 ± 2.1。",
    ],
)
def test_statistics_are_flagged(sentence: str) -> None:
    gaps = find_citation_gaps(sentence)
    assert len(gaps) == 1
    assert gaps[0]["reason"] == "带统计量，需要出处"


def test_statistics_without_evidence_are_not_flagged() -> None:
    assert find_citation_gaps("两组差异显著，但没有给出具体数字。") == []


def test_percent_and_year_is_flagged() -> None:
    body = "2020 年，该平台已有 47% 的用户使用移动端。"
    gaps = find_citation_gaps(body)
    assert len(gaps) == 1
    assert gaps[0]["reason"] == "含具体数据，需要出处"


def test_percent_without_year_is_not_flagged() -> None:
    assert find_citation_gaps("约有 47% 的用户使用移动端。") == []


def test_year_without_percent_is_not_flagged() -> None:
    assert find_citation_gaps("该标准于 2020 年发布。") == []


def test_self_reference_is_not_flagged() -> None:
    for body in (
        "本文基于 2020 年的调查，覆盖 47% 的样本。",
        "本研究采用问卷调查法。",
        "我们在 2020 年覆盖了 47% 的样本。",
    ):
        assert find_citation_gaps(body) == []


def test_heading_lines_are_skipped() -> None:
    body = "# 研究表明，2020 年有 47% 的数据有误\n\n### 小标题\n正文没有问题。"
    assert find_citation_gaps(body) == []


def test_line_number_points_at_sentence_start() -> None:
    body = "# 一、引言\n\n\n研究表明，47% 的样本有缺失。"
    gaps = find_citation_gaps(body)
    assert len(gaps) == 1
    assert gaps[0]["line_no"] == 4


def test_limit_truncates() -> None:
    body = "研究表明甲。\n研究表明乙。\n研究表明丙。"
    gaps = find_citation_gaps(body, limit=2)
    assert [gap["sentence"] for gap in gaps] == ["研究表明甲。", "研究表明乙。"]


def test_limit_is_capped_at_30() -> None:
    body = "\n".join(f"研究表明第 {index} 条。" for index in range(35))
    assert len(find_citation_gaps(body, limit=100)) == 30


def test_non_positive_limit_returns_nothing() -> None:
    assert find_citation_gaps("研究表明。", limit=0) == []
    assert find_citation_gaps("研究表明。", limit=-3) == []


def test_each_sentence_is_reported_once() -> None:
    body = "研究表明，2020 年有 47% 的数据（p < 0.05）。"
    gaps = find_citation_gaps(body)
    assert len(gaps) == 1
    # 规则 3 优先于 4 / 5：同一句只留一条 reason
    assert gaps[0]["reason"] == "引述他人研究的典型句式"


def test_sentences_are_split_in_order() -> None:
    body = "研究表明甲。2020 年已有 47% 的样本。"
    gaps = find_citation_gaps(body)
    assert [gap["sentence"] for gap in gaps] == [
        "研究表明甲。",
        "2020 年已有 47% 的样本。",
    ]


def test_english_period_splits_sentences() -> None:
    body = "Studies show the effect. In 2020 the sample covered 47%."
    gaps = find_citation_gaps(body)
    assert [gap["sentence"] for gap in gaps] == [
        "Studies show the effect.",
        "In 2020 the sample covered 47%.",
    ]


def test_multiline_sentence_keeps_start_line() -> None:
    body = "研究表明，\n47% 的样本。"
    gaps = find_citation_gaps(body)
    assert len(gaps) == 1
    assert gaps[0]["sentence"] == "研究表明， 47% 的样本。"
    assert gaps[0]["line_no"] == 1


def test_summarize_gaps_counts() -> None:
    gaps = [{"sentence": "甲"}, {"sentence": "乙"}, {"sentence": "丙"}]
    assert summarize_gaps(gaps) == "有 3 句像是引述他人成果但没有引用标记"


def test_summarize_gaps_without_hits() -> None:
    text = summarize_gaps([])
    assert text == "未发现疑似该引未引的句子"
    # 0 条时不许编成「有 0 句」
    assert "0" not in text


# ============================================================ 自指豁免（句中）
def test_own_data_with_numbers_is_not_reported() -> None:
    """方法段写「共纳入 120 例（n=120）」是自己的工作，不该被当"该引未引"。

    用户实测后拍板：这种句子数字开头、句首没有自指词，旧规则挡不住，
    校对的提示会变成噪声。
    """
    body = "共纳入 120 例（n=120），年龄 45±12 岁。"
    assert find_citation_gaps(body) == []


def test_own_survey_with_percent_is_not_reported() -> None:
    body = "我们调查了 47% 的用户，回收有效问卷 300 份。"
    assert find_citation_gaps(body) == []


def test_self_ref_in_middle_suppresses_whole_sentence() -> None:
    """句中自指 → 整句不报（这是**有意的漏报**，写进用例免得被当 bug 修掉）。"""
    body = "已有研究表明该指标有效，我们据此改进了评分口径。"
    assert find_citation_gaps(body) == []


def test_other_people_work_still_reported() -> None:
    """没有自指的"研究表明"仍然要报——豁免不能把功能吃掉。"""
    gaps = find_citation_gaps("研究表明该方法在长文本上更稳。")
    assert len(gaps) == 1
    assert "引述" in gaps[0]["reason"]


def test_collected_data_phrases_are_exempt() -> None:
    for sentence in (
        "共收集样本 500 份。",
        "共招募受试者 30 名。",
        "笔者对 12 家企业做了访谈。",
    ):
        assert find_citation_gaps(sentence) == [], sentence
