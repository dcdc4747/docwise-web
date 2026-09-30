"""块分级的单测。

用例全部取自**真实样本里出现过的行**（两份 arXiv 论文的实测文本 + 那份扫描版中文通知
OCR 出来的文本），不是编的——分级判错在界面上是"标题被当正文"这种一眼可见的问题，
但没人会去逐块核对，所以要靠这些真实样本把它钉住。

最要紧的两条边界：
1. **中文期刊的"（一）xxx"既可能是小标题、也可能是正文段首**——靠行尾标点区分
   （实测：正文那句以"。"收尾）；
2. **题名只认首页最前面几块**——同一句话挪到后面的页就不是题名了。
"""

from __future__ import annotations

from app.blocktypes import BLOCK_TYPES, classify, classify_blocks


def test_english_numbered_headings() -> None:
    assert classify("1 Introduction", "p0_b5") == "heading"
    assert classify("2.1 Methods", "p2_b3") == "heading"
    assert classify("3.4.1 Notes on the proof", "p5_b1") == "heading"


def test_english_section_words() -> None:
    assert classify("Abstract", "p0_b1") == "heading"
    assert classify("References", "p9_b0") == "heading"
    assert classify("Materials and Methods", "p3_b0") == "heading"


def test_all_caps_short_line_is_heading() -> None:
    # 化学那份 arXiv 用罗马数字编号，靠"全大写短行"这条抓到
    assert classify("I. INTRODUCTION", "p0_b4") == "heading"
    assert classify("ABSTRACT", "p0_b1") == "heading"


def test_all_caps_junk_from_real_layout_is_not_heading() -> None:
    """实测抓到的两条：作者署名行与页脚都全大写，但都不是标题。

    这两个串是从 task 31/34 的真实块里捞出来的（英文杂志版式）——
    第一版"全大写就算标题"把两条都吃成了 heading。
    """
    assert (
        classify(
            "BY MADELINE COHEN, AARON PIERCE, BRIAN BLAHO & AMY DIETRICH", "p0_b5"
        )
        == "body"
    )
    assert classify("20AALLSPECTRUMIWWW.AALLNET.ORG", "p0_b12") == "body"
    # OCR 把署名行切碎后剩出来的碎片（以标点开头）
    assert classify("&AMY DIETRICH", "p0_b11") == "body"


def test_stray_fragment_in_title_zone_is_not_title() -> None:
    """实测：英文杂志首页头部会掉出 `L` 这种碎片块，不能当文献题名。"""
    assert classify("L", "p0_b0") == "body"


def test_chinese_numbered_headings() -> None:
    # 扫描版中文通知（OCR）里真实出现的小标题
    assert classify("二、组织机构", "p1_b4") == "heading"
    assert classify("六、赛程安排", "p3_b3") == "heading"
    assert classify("（一）主办单位", "p1_b5") == "heading"


def test_chinese_body_starting_with_paren_number_is_not_heading() -> None:
    """正文段首也长这样，靠行尾的"。"区分——判错就是整篇正文被当标题。"""
    line = (
        "（一）本次竞赛报名面向普通高等学校全日制在校学生开放，参赛学生范围包括研究生、"
        "本科生及高职高专学生，参赛专业不受限制。"
    )
    assert classify(line, "p2_b0") == "body"


def test_caption_prefixes() -> None:
    assert classify("Figure 1: The algorithm in one picture.", "p4_b7") == "caption"
    assert (
        classify("Fig. 3. Rotational dynamics of the chiral molecule", "p6_b2")
        == "caption"
    )
    assert (
        classify("Table 2: Hyperparameters used in all experiments", "p7_b1")
        == "caption"
    )
    assert classify("图 1 赛程安排", "p3_b0") == "caption"
    assert classify("表 2 各赛项参赛范围", "p4_b2") == "caption"


def test_title_zone_only_on_first_page() -> None:
    """题名只认首页最前面几块；同一句话挪到第三页就是正文。"""
    line = "Chiral Temporal Structures in Molecular Rotational Dynamics"

    assert classify(line, "p0_b0") == "title"
    assert classify(line, "p0_b2") == "title"
    assert classify(line, "p3_b0") == "body"


def test_title_zone_needs_no_terminal_punctuation() -> None:
    """题名区里以句号收尾的，是正文开头，不是题名。"""
    line = "We give a deterministic algorithm that solves a nonsingular linear system。"

    assert classify(line, "p0_b1") == "body"


def test_long_body_paragraph_is_body() -> None:
    line = (
        "We give a deterministic algorithm that solves a nonsingular linear system "
        "over the rationals in about mn log(kappa/epsilon) bit operations, improving "
        "on the previous best bound for this problem."
    )
    assert classify(line, "p1_b0") == "body"


def test_reference_entry_is_body() -> None:
    line = (
        "[12] J. A. Kelner, Acceleration of Euclidean algorithm and rational number "
        "reconstruction. SIAM Journal on Computing, 32(2):548-556, 2003."
    )
    assert classify(line, "p15_b3") == "body"


def test_empty_text_is_body() -> None:
    assert classify("", "p0_b0") == "body"
    assert classify("   ", "p0_b0") == "body"


def test_classify_blocks_fills_type_in_place() -> None:
    blocks = [
        {"block_id": "p0_b0", "text": "Solving Linear Systems in Bit Operations"},
        {"block_id": "p0_b1", "text": "Abstract"},
        {"block_id": "p1_b0", "text": "Figure 2: Running time."},
        {"block_id": "p1_b1", "text": "The proof follows from Lemma 3."},
    ]

    result = classify_blocks(blocks)

    assert result is blocks
    assert [item["type"] for item in blocks] == ["title", "heading", "caption", "body"]


def test_type_vocabulary_is_fixed() -> None:
    """类型词表就是前端要支持的四个值——加值前先想好界面上怎么表现。"""
    assert BLOCK_TYPES == ("title", "heading", "caption", "body")
