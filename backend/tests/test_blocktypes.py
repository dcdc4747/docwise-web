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
    _looks_like_heading_by_region,
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
        "（一）本次活动面向普通高等学校全日制在校学生开放，参与学生范围包括研究生、"
        "本科生及高职高专学生，参与专业不受限制。"
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


def _placed(
    block_id: str, text: str, unit_h: float, x0: float, x1: float, y0: float
) -> dict:
    """带**完整矩形**的块（按坐标贴版面类别要用 x/y）。"""
    return {
        "block_id": block_id,
        "text": text,
        "layout": {
            "unit_h": unit_h,
            "bold": 0.0,
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y0 + unit_h,
            "page_h": 800.0,
        },
    }


def _region(cls: str, x0: float, y0: float, x1: float, y1: float) -> dict:
    return {"cls": cls, "bbox": [x0, y0, x1, y1], "conf": 0.9}


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


# ── 3a：引擎那条路带上版面量之后，真样本上抓出来的三个错 ──────────────


def test_author_initials_line_is_not_heading() -> None:
    """署名行 `A. G. L ohr, …` 不是标题——它靠 `A. ` 命中了**字母编号**那条规则。

    实测（task 36/37，化学 arXiv 182 块）：这份文献**唯一**被判成 heading 的就是它。
    区别在于编号后面跟的是"又一个单字母 + 点"（缩写串）还是完整的词
    （`A. Geometrical measure` 才是真小节标题）。
    """
    assert classify("A. G. L ohr, O. Smirnova, and M. Mirahmadi", "p0_b0") == "body"
    assert classify("A. G. L ohr, O. Smirnova, and M. Mirahmadi", "p3_b7") == "body"
    # 真小节标题不受影响
    assert classify("A. Geometrical measure", "p3_b4") == "heading"
    assert classify("B. Dynamical measure", "p3_b9") == "heading"


def test_title_zone_picks_largest_eligible_not_largest() -> None:
    """题名区里"更大但不合格"的块**不能把题名位置占住**。

    实测（`pdf_EBSCO_04.pdf`，task 31）：首页的**首字下沉碎片** `L` 是 94.2pt，
    而真题名 `Partnering for Progress:` 才 47.4pt。旧写法先取最大的那块（`L`）、
    再判它不合格 → **整篇一个题名都没有**（那份文献现在就是这样）。
    现在先筛掉不合格的，再在合格的里面取最大的。
    """
    blocks = [
        _block("p0_b0", "L", 94.2),
        _block("p0_b1", "aw firms are rapidly integrating AI into workflows.", 10.5),
        _block("p0_b2", "Partnering for Progress:", 47.4),
        _block("p0_b9", "正文足够长，用来把基准字号压到正文这一档上。" * 3, 10.5),
    ]
    classify_blocks(blocks)

    assert [b["type"] for b in blocks] == ["body", "body", "title", "body"]


def test_signature_line_is_neither_heading_nor_title() -> None:
    """**署名行不许是标题，也不许是题名**（老任务没有版面量时走的是"题名兜底"）。

    实测（task 36/37）：这份文献首页第一块就是 `A. G. L ohr, O. Smirnova, and
    M. Mirahmadi`。它短、不像句子，所以"题名区兜底"也想吃它——两条判据都得挡。
    """
    blocks = [
        {"block_id": "p0_b0", "text": "A. G. L ohr, O. Smirnova, and M. Mirahmadi"},
        {"block_id": "p0_b1", "text": "We introduce chiral rotational wavepackets."},
    ]

    classify_blocks(blocks)

    assert [b["type"] for b in blocks] == ["body", "body"]
    # EBSCO 那份的署名行同理（`BY MADELINE COHEN, …`）
    assert classify("BY MADELINE COHEN, AARON PIERCE", "p0_b0") == "body"


def test_figure_reference_in_body_is_not_caption() -> None:
    """**正文里提到图**不是图注：`Fig. 7 shows …`。

    实测（化学 arXiv 182 块）：10 个"图注"里有 2 个是这种句子
    （`Fig. 7 shows both local measures…`、`Fig. 8(a–c) shows the orientation
    trajectories…`）。判据是编号后面那一段：小写拉丁词 = 正文，分隔符 / 汉字 = 图注。
    """
    assert (
        classify("Fig. 7 shows both local measures for the trajectory.", "p7_b88")
        == "body"
    )
    assert (
        classify("Fig. 8(a–c) shows the orientation trajectories of three.", "p8_b94")
        == "body"
    )
    assert classify("Table 2 in the appendix shows the same trend.", "p2_b9") == "body"
    # 真图注一条都不能掉
    real_captions = [
        "FIG. 7. Local (a) geometrical and (b) dynamical measures",
        "FIG. 8(a–c). Orientation trajectories of a symmetric top",
        "图 1 赛程安排",
        "Figure 1 Overview of the proposed pipeline",
    ]
    for caption in real_captions:
        assert classify(caption, "p7_b89") == "caption", caption


# ── 任务 A：按坐标贴「版面类别」（模型框出来的区域）────────────────────


def test_region_title_promotes_only_such_blocks() -> None:
    """模型把某块框成 `title` → 当章节标题；**长块与整句话不认**。

    实测价值：化学那份 21 条标题靠文字形状 + 字号就认得出来，**另有 9 条只有区域
    认得出来**（`II. ORIENTATION TRAJECTORY OF A ROTATIONAL WAVEPACKET`、
    `Appendix A~G` 这些：罗马数字编号 + 全大写超过 4 个词 / 没有编号也没有章节名，
    两条既有判据都够不着）。护栏沿用既有的两条：不比 `_HEADING_MAX` 长
    （防"标题 + 紧随正文"并成一段时整段变标题）、行尾不是句末标点（防整句话变标题）。
    """
    roman_heading = "II. ORIENTATION TRAJECTORY OF A ROTATIONAL WAVEPACKET"
    sentence = "This sentence just happens to sit inside it."
    blocks = [
        _placed("p3_b1", "Appendix C: Fourier figures", 9.0, 54, 299, 100.0),
        _placed("p3_b2", roman_heading, 9.0, 54, 299, 150.0),
        # 只是"落在标题区域里"的一整句话 → 不许变标题
        _placed("p3_b3", sentence, 10.0, 54, 299, 200.0),
        # 太长（"标题 + 正文"并成一段的样子）→ 不许变标题
        _placed("p3_b4", "Header Words " + "body text " * 20, 10.0, 54, 299, 250.0),
    ]
    regions = {
        "3": [
            _region("title", 54, 98, 299, 120),
            _region("title", 54, 148, 299, 170),
            _region("title", 54, 198, 299, 220),
            _region("title", 54, 248, 299, 300),
        ]
    }

    classify_blocks(blocks, regions)

    assert [b["type"] for b in blocks] == ["heading", "heading", "body", "body"]
    assert [b.get("region") for b in blocks] == ["title"] * 4


def test_region_caption_beats_nothing_but_keeps_body_safe() -> None:
    """模型框成图注/表注 → `caption`（救回**罗马数字表注**：文字规则漏的那种）。"""
    roman_table = "TABLE I. Effect of transformations of the coefficients"
    blocks = [
        _placed("p6_b1", roman_table, 9.0, 54, 299, 100.0),
        _placed("p6_b2", "FIG. 9. Caught by the text rule.", 9.0, 54, 299, 150.0),
        _placed("p6_b3", "An ordinary paragraph, not a caption.", 10.0, 54, 299, 200.0),
    ]
    regions = {
        "6": [
            _region("table_caption", 54, 98, 299, 120),
            _region("figure_caption", 54, 148, 299, 170),
            _region("plain text", 54, 198, 299, 260),
        ]
    }

    classify_blocks(blocks, regions)

    assert [b["type"] for b in blocks] == ["caption", "caption", "body"]


def test_region_needs_column_not_just_row() -> None:
    """**双栏页光靠 y 分不开左右栏**：同一个 y 上左右两栏各有一条，各贴各的区域。

    实测依据：化学那份第 0 页 `I. INTRODUCTION` 在右栏 y≈297.9，左栏正文 y≈297.1——
    只比 y 会把右栏的标题贴到左栏的区域上，所以 `layout` 必须带 x0/x1。
    """
    blocks = [
        _placed("p0_b1", "Left column paragraph.", 10.0, 54, 299, 295.0),
        _placed("p0_b2", "II. RIGHT COLUMN HEADING", 9.0, 317, 562, 295.0),
    ]
    regions = {
        "0": [
            _region("plain text", 54, 290, 299, 340),
            _region("title", 317, 290, 562, 320),
        ]
    }

    classify_blocks(blocks, regions)

    assert [b["type"] for b in blocks] == ["body", "heading"]
    assert [b["region"] for b in blocks] == ["plain text", "title"]


def test_region_absent_or_broken_never_changes_anything() -> None:
    """老产物（`layout` 里没有 x0/x1）、区域表缺失或被写坏时：**一块都不受影响**。"""
    blocks = [
        _block("p0_b1", "II. ORIENTATION TRAJECTORY OF A ROTATIONAL WAVEPACKET", 9.0),
        _block("p0_b2", "An ordinary paragraph.", 10.0),
    ]

    # 没有 x0/x1 → 贴不上（注意这两块的文字形状本来就会判成 body）
    classify_blocks(blocks, {"0": [_region("title", 0, 0, 999, 999)]})
    assert [b["type"] for b in blocks] == ["body", "body"]
    assert [b.get("region") for b in blocks] == [None, None]

    broken = [
        _placed("p1_b1", "Region test line with mixed Case", 9.0, 54, 299, 100.0),
        _placed("p1_b2", "Another paragraph here.", 10.0, 54, 299, 150.0),
    ]
    classify_blocks(
        broken,
        {
            "1": [
                {"cls": "title"},  # 没有 bbox
                {"cls": "title", "bbox": "不是列表"},
                {"cls": "title", "bbox": [1, 2, 3]},  # 少一个数
                {"bbox": [0, 0, 999, 999]},  # 没有 cls
                "不是字典",
            ]
        },
    )
    assert [b["type"] for b in broken] == ["body", "body"]


# ── 任务 A2：把量出来的几类错例收掉（2026-10-01）─────────────────────
# 这些都不是"调参调出来的"，是**在 5 篇真文献上逐块核对**抓到的（数学 arXiv 3 条、
# sample_01 1 条）。改完做了全库对账：40 个已完成任务只变 6 块、全是纠正——
# 化学那份 30 条标题、中文 257 块、扫描件、杂志任务**一块没动**。


def test_numbered_heading_needs_a_word_start() -> None:
    """编号标题：编号后面那个词得**像词的开头**（大写拉丁 / 汉字 / 数字）。

    收掉的两条例：算法块的 `5 end`（`end` 小写）与公式碎片 `0 𝜖 1 𝑃 4𝑛 𝜖`
    （𝜖 是数学小写斜体）——它们原来只满足"数字 + 空格 + 任意字符"。
    """
    for bad in ["5 end", "0 𝜖 1 𝑃 4𝑛 𝜖", "12 print(x)"]:
        assert classify(bad, "p8_b105") == "body", bad
    # 真编号标题一条都不能掉（含中文编号、以及"编号后面跟数字"的写法）
    for good in [
        "1 Introduction",
        "1.1 Main Result",
        "2.3 Faster Reconstruction",
        "1 引言",
        "2.1 3D reconstruction",
        "A. Geometrical measure",
    ]:
        assert classify(good, "p0_b5") == "heading", good


def test_algorithm_caption_is_a_caption_not_a_heading() -> None:
    """`Algorithm 1: …` 是浮动体题注，不是章节标题。

    实测：数学 arXiv 那份的算法框**被版面模型整块框成了 `title`**，于是框里的
    `Algorithm 1: SolvePerturbed 𝐴, 𝑏, 𝑅` 靠"区域判据"变成了标题。图注判据排在标题判据
    前面，把 `algorithm` / `listing` 加进**带编号**的图注前缀就能压过模型的区域判定；
    `Algorithm Design` 这种章节标题不许被吃掉。
    """
    regions = {"8": [_region("title", 0, 0, 999, 999)]}
    blocks = [
        _block("p8_b103", "Algorithm 1: SolvePerturbed 𝐴, 𝑏, 𝑅", 10.9),
        _block("p8_b105", "Algorithm Design", 10.9),
        _block("p8_b106", "Listing 2: The parser", 10.9),
    ]
    classify_blocks(blocks, regions)
    assert [b["type"] for b in blocks] == ["caption", "body", "caption"]


def test_name_list_in_title_zone_is_neither_heading_nor_title() -> None:
    """首页题名区的**人名列表**既不是标题也不是题名。

    实测（sample_01）：作者行 `Robin Hunicke, Marc LeBlanc, Robert Zubek` 12pt、
    正文 10pt = 恰好 1.2 倍，正踩在"明显大于正文"的下限上 → 被判成标题。
    判据不用"有没有 and"猜语义：**逗号分开的每一段都以大写字母开头**才算人名列表，
    所以真标题 `Methods, Results, and Discussion`（`and Discussion` 小写开头）保住。
    """
    layout = {"unit_h": 12.0, "y0": 90.0, "page_h": 792.0}
    names = "Robin Hunicke, Marc LeBlanc, Robert Zubek"
    assert classify(names, "p0_b1", layout, 10.0) == "body"
    # 这条护栏**只在题名区**生效：同样一行挪到正文页里，照旧按版面判（免得误伤正文列表）
    assert classify(names, "p5_b40", layout, 10.0) == "heading"
    sections = "Methods, Results, and Discussion"
    assert classify(sections, "p0_b1", layout, 10.0) == "heading"


def test_region_heading_needs_a_word() -> None:
    """模型把整块框成 `title` 时，框里也得**像个词组**才给标题。

    实测：数学 arXiv 那份整个算法框被框成 `title`，框里的 `5 end` 就成了标题候选；
    真标题（`Appendix C: Fourier figures`、中文标题）都至少有一个大写 / 汉字开头的词。
    """
    assert _looks_like_heading_by_region("5 end", "title") is False
    assert _looks_like_heading_by_region("Appendix C: Fourier figures", "title") is True
    assert _looks_like_heading_by_region("七、结论与展望", "title") is True
    # 署名行即便落在 `title` 区域里也不算标题
    assert _looks_like_heading_by_region("BY MADELINE COHEN", "title") is False



