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

import statistics

from app.blocktypes import (
    BLOCK_TYPES,
    _body_height,
    classify,
    classify_blocks,
)


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


# ── 版面信号（2026-09-30 起）：真样本实测出来的阈值与护栏 ──────────────


def _block(block_id: str, text: str, unit_h: float, bold: float = 0.0) -> dict:
    return {
        "block_id": block_id,
        "text": text,
        "layout": {"unit_h": unit_h, "bold": bold, "y0": 100.0, "page_h": 800.0},
    }


def test_cjk_text_with_latin_acronym_is_not_all_caps_heading() -> None:
    """**真 bug 的回归用例**：中文里夹 `AI`/`AIGC` 的正文段曾被"全大写"判成标题。

    Python 的 `str.isupper()` 只看"有大小写的字符"——`…生成式AI 驱动下` 里唯一有大小写的
    就是 `AI`，于是整段被判成全大写。中文样本（257 块）因此误判出 **9 个正文段**当标题。
    """
    line = (
        "现有文献已就生成式人工智能在营销领域的应用展开了一定探索。"
        "部分研究聚焦于生成式AI 驱动下"
    )

    assert classify(line, "p1_b13") == "body"


def test_layout_bigger_than_body_is_heading() -> None:
    """中文排版靠"字号大一点"：实测正文 10.0pt、标题 12.0pt（1.2 倍）。"""
    blocks = [
        _block("p1_b0", "这是一段正文，长度足够代表正文基准字号。", 10.0),
        _block("p1_b1", "1. 引言", 12.0),
    ]

    classify_blocks(blocks)

    assert [b["type"] for b in blocks] == ["body", "heading"]


def test_layout_bold_but_smaller_than_body_is_heading_in_arxiv() -> None:
    """arXiv 反着来：章节标题**加粗但字号比正文小**（实测 0.90 倍）。

    所以字号与加粗两条判据都得留——只留一条会漏掉一半文档。
    """
    blocks = [
        _block("p0_b0", "Some body paragraph that is reasonably long here.", 10.0),
        _block("p0_b1", "I. INTRODUCTION", 9.0, bold=1.0),
    ]

    classify_blocks(blocks)

    assert [b["type"] for b in blocks] == ["body", "heading"]


def test_layout_huge_font_is_not_heading() -> None:
    """比正文大 8.95 倍的是**首字下沉碎片**（真样本 `L`），不是标题。"""
    blocks = [
        _block("p0_b0", "这是一段正文，用来定基准。", 10.5),
        _block("p0_b1", "L", 94.2),
    ]

    classify_blocks(blocks)

    assert [b["type"] for b in blocks] == ["body", "body"]


def test_layout_bold_author_line_is_not_heading() -> None:
    """署名行是粗体、字号也接近正文——**只有全大写才算标题**这条把它挡在外面。"""
    blocks = [
        _block("p0_b3", "这是一段正文，用来定基准字号。", 10.0),
        _block("p0_b8", "Sheng Wu", 11.0, bold=1.0),
    ]

    classify_blocks(blocks)

    assert [b["type"] for b in blocks] == ["body", "body"]


def test_title_is_the_largest_block_in_title_zone() -> None:
    """题名＝题名区里**字号最大**的那块。

    实测中文样本：p0_b0 页眉 9pt、p0_b1 引用行 9pt、**p0_b2 真题名 22pt**——
    按"第一块"判会把引用行当题名。
    """
    blocks = [
        _block("p0_b0", "E-Commerce Letters 电子商务评论, 2026", 9.0),
        _block(
            "p0_b1",
            "文章引用: 吴晟. 生成式人工智能赋能网络营销的机制与路径研究",
            9.0,
        ),
        _block("p0_b2", "生成式人工智能赋能网络营销的机制与路径研究", 22.0),
        _block("p0_b5", "摘 要", 12.0),
    ]

    classify_blocks(blocks)

    assert [b["type"] for b in blocks] == ["body", "body", "title", "heading"]


def test_without_layout_still_uses_text_shape() -> None:
    """**老任务（没有版面信号）的行为必须与以前完全一致**——这是硬要求。"""
    blocks = [
        {"block_id": "p0_b0", "text": "Solving Linear Systems"},
        {"block_id": "p0_b1", "text": "1 Introduction"},
        {"block_id": "p1_b0", "text": "Figure 2: Running time."},
        {"block_id": "p1_b1", "text": "We prove the bound by induction."},
    ]

    classify_blocks(blocks)

    assert [b["type"] for b in blocks] == ["title", "heading", "caption", "body"]


def test_letter_numbered_subsection_is_heading() -> None:
    """`A. Geometrical measure`：arXiv 化学那份 20 多条小节标题全靠这条（实测）。"""
    assert classify("A. Geometrical measure", "p3_b4") == "heading"
    assert classify("B. Dynamical measure", "p3_b9") == "heading"


# ── 实施审查（2026-10-01）点名要补的几类用例 ──────────────────────


def test_long_big_line_is_not_heading() -> None:
    """**"大 + 短"才判标题**：EBSCO 那类 1.60 倍的"导语（deck）"是一整句话。

    实测过：只抬阈值不管用——1.25 既挡不住 1.60 的导语，又会漏掉 1.20 的真标题
    （中文样本的 `Keywords`）。所以判据是"明显大 **且** 够短"。
    """
    deck = (
        "Moving beyond transactions to strategic collaboration in a rapidly "
        "evolving legal market"
    )
    blocks = [
        _block("p0_b0", "这是一段正文，用来定基准字号。", 10.5),
        _block("p0_b1", deck, 16.8),
    ]

    classify_blocks(blocks)

    assert [b["type"] for b in blocks] == ["body", "body"]


def test_mixed_signal_document_does_not_downgrade_silently() -> None:
    """同一篇里"一部分块有信号、一部分没有"时，没信号的块走文字形状判据。

    踩过的坑：早先按**单块**判"这篇有没有信号"，于是没信号的块会把题名兜底也跳过，
    被静默降级。现在按**全篇**判（`has_signal`），批处理里一次算好传下去。
    """
    blocks = [
        _block("p0_b0", "E-Commerce Letters 电子商务评论, 2026", 9.0),
        _block("p0_b1", "生成式人工智能赋能网络营销的机制与路径研究", 22.0),
        # 正文要够多，基准才落在正文上（真实文档就是这样）
        _block("p0_b5", "这是一段正文，长度足够代表正文的基准字号。" * 3, 10.0),
        _block("p1_b1", "这也是一段正文，同样足够长。" * 4, 10.0),
        # 这两块没有版面信号，但命中文字形状规则 → 不能因为缺信号就降级
        {"block_id": "p1_b0", "text": "1 Introduction"},
        {"block_id": "p2_b0", "text": "Figure 3: Running time."},
    ]

    classify_blocks(blocks)

    assert [b["type"] for b in blocks] == [
        "body",
        "title",
        "body",
        "body",
        "heading",
        "caption",
    ]


def test_broken_layout_values_never_crash() -> None:
    """契约被破坏（字符串 / 负数 / NaN / 缺键 / 不是 dict）时，
    **只退化为文字形状**，不许抛异常。

    分级跑在任务详情接口的请求路径上——判错只是少个样式，**不能让详情 500**。
    """
    broken = [
        {"block_id": "p0_b0", "text": "正文一", "layout": {"unit_h": "abc"}},
        {"block_id": "p0_b1", "text": "正文二", "layout": {"unit_h": -5}},
        {"block_id": "p0_b2", "text": "正文三", "layout": {"unit_h": float("nan")}},
        {"block_id": "p0_b3", "text": "1 引言", "layout": {}},
        {"block_id": "p0_b4", "text": "正文四", "layout": "不是字典"},
        {"block_id": "p0_b5", "text": "正文五"},
    ]

    classify_blocks(broken)  # 不抛异常即通过

    assert [b["type"] for b in broken] == [
        "body",
        "body",
        "body",
        "heading",  # 命中编号规则，与有没有布局信号无关
        "body",
        "body",
    ]


def test_letter_numbering_requires_punctuation() -> None:
    """`A. Geometrical measure` 是小节标题，但 `A second approach …` 是正文续行。

    早先的正则把标点写成可选，于是单个大写字母开头的续行会被判成标题——**块是行**，
    这种续行很常见。现在字母后必须有点号/括号。
    """
    assert classify("A. Geometrical measure", "p3_b4") == "heading"
    assert classify("A second approach to the same problem", "p3_b5") == "body"
    assert classify("I cannot prove this here", "p3_b6") == "body"


def test_body_height_is_character_weighted() -> None:
    """正文基准是**按字符数加权**的中位数——不是朴素中位数。

    为什么值得单独测：朴素中位数会被页眉/页脚/图注那群**短块**带偏（实测就踩过：
    某页基准落到 8.5pt，于是 10pt 的**正文长段**被算成"比正文大 18%"）。这里构造一份
    "短块多、长块少"的样本，两种算法结果不同，锁住这个设计。
    """
    blocks = [
        _block("p0_b0", "正" * 300, 10.0),
        _block("p0_b1", "文" * 250, 10.0),
        _block("p0_b2", "页脚" * 5, 9.0),
        _block("p0_b3", "图注" * 5, 9.0),
        _block("p0_b4", "脚注" * 5, 9.0),
    ]

    assert _body_height(blocks) == 10.0  # 按字数加权 → 取到正文那两块的 10.0
    assert statistics.median([10.0, 10.0, 9.0, 9.0, 9.0]) == 9.0  # 朴素中位数会得到 9.0


def test_title_zone_skips_caption_block() -> None:
    """首页**大字号图注**不能当文献题名（journal 常见版式）。

    否则它会抢走题名：真题名降级成正文，而那块被标成 `title` 而不是 `caption`。
    """
    blocks = [
        _block("p0_b0", "Figure 1: Overview of the proposed pipeline.", 20.0),
        _block("p0_b1", "这是一段正文，长度足够用来定基准字号。", 10.0),
    ]

    classify_blocks(blocks)

    assert [b["type"] for b in blocks] == ["caption", "body"]
