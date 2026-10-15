"""M4 验收样例（三篇）的用例 —— **这是分母，不许改样例去迁就实现**。

出处：`docs/m4-验收样例与说明_20261015.md`（下面是它的汇总表，原文照抄）。
报告口径一律「报出 N 处、人工判定 M 处成立」，**不写百分比**。

| 样例 | 预期报出 N | 人工成立 M | 真该报 | 明知会误报 |
|---|---|---|---|---|
| 1 中文 · 顺序编码制 | 2 | 1 | 句 3 | 句 6 |
| 2 英文 · 顺序编码制 | 2 | 1 | 句 3 | 句 6 |
| 3 著者-出版年制 | 0（有 E2；无 E2 是 4） | 0 | — | — |

⚠️ 两处「明知会误报」是**判据本身的已知缺口**（8 字豁免窗太窄），文档要求它们在样例
阶段就暴露出来 —— 所以这里**断言它们仍然被报出来**，别为了让数字好看把它们消掉。

⚠️ 样例里的 `[1]`/`[2]` 要配一份**对得上的文献表**：不然 R2（正文引了但文献表没有）
会跟着报，N 就不是「该引未引」那个 N 了（第一次跑就踩了这条）。
"""

from __future__ import annotations

from app.check.engine import detect_citation_style, detect_language, run_check

# ---------------------------------------------------------- 样例一 · 中文 · 顺序编码制

SAMPLE_1 = (
    "图像分割是计算机视觉中的基础任务之一。\n"
    "多项研究表明，Transformer 架构在长程依赖建模上优于卷积网络[1]。\n"
    "另有调查显示，超过六成的医疗影像团队已把自监督预训练纳入标准流程。\n"
    "不过，也有观点认为，数据增强策略对最终性能的影响可能被高估。\n"
    "我们的实验结果显示，该数据集上的平均分割精度有 4.7% 的提升。\n"
    "本研究提出的混合监督策略在不增加标注成本的前提下，"
    "把边界误差降低了 1.2 个百分点。\n"
    "有学者指出，现有方法在少样本场景下泛化能力不足[2]。"
)

# ---------------------------------------------------------- 样例二 · 英文 · 顺序编码制

SAMPLE_2 = (
    "Image segmentation is a fundamental task in computer vision.\n"
    "Several studies have shown that transformer-based models outperform "
    "convolutional networks on long-range dependencies [1].\n"
    "A recent survey reported that over sixty percent of clinical teams now "
    "include self-supervised pretraining in their standard pipeline.\n"
    "Some researchers have argued that the effect of data "
    "augmentation may be overestimated.\n"
    "We found an average improvement of 4.7% on this public dataset.\n"
    "The proposed hybrid supervision strategy reduced the boundary error by "
    "1.2 percentage points without increasing annotation cost.\n"
    "Some authors noted that existing methods lack generalization "
    "in few-shot scenarios [2]."
)

# ---------------------------------------------------------- 样例三 · 著者-出版年制

SAMPLE_3 = (
    "图像分割是计算机视觉中的基础任务之一。\n"
    "多项研究表明，Transformer 架构在长程依赖建模上优于卷积网络（张三，2024）。\n"
    "一项覆盖三十二家机构的调查显示，超过六成的医疗影像团队已把自监督预训练"
    "纳入标准流程（李四，2023）。\n"
    "Wang 等（2022）发现，现有方法在少样本场景下泛化能力不足。\n"
    "我们的实验结果显示，平均分割精度有 4.7% 的提升（张三，2024）。\n"
    "本文提出的混合监督策略在不增加标注成本的前提下，把边界误差降低了 1.2 个百分点"
    "（陈五，2025）。"
)

# 样例一/二的文献表（[1] [2] 两条，字段齐全 → 不触发 R2–R5）
CITATIONS = [
    {
        "order": 1,
        "csl_json": {
            "type": "article-journal",
            "title": "Transformer for long-range dependencies",
            "author": [{"literal": "A"}],
        },
    },
    {
        "order": 2,
        "csl_json": {
            "type": "article-journal",
            "title": "Few-shot generalization",
            "author": [{"literal": "B"}],
        },
    },
]


def _reported(report: dict) -> list[dict]:
    return [item for item in report["findings"] if item["severity"] == "report"]


def _sentences(report: dict) -> str:
    return " ｜ ".join(item["sentence"] for item in _reported(report))


# ---------------------------------------------------------------- 样例一


def test_sample1_main_path():
    """中文 · 顺序编码制：该报的报（句 3）、有标注/有豁免的不报。"""
    report = run_check(SAMPLE_1, citations=CITATIONS)
    assert report["step"]["lang"] == "zh"
    assert report["step"]["citation_style"] == "numeric"
    assert report["summary"]["reported"] == 2
    assert report["summary"]["unknown"] == 0
    # 报出的两句：句 3（真该报）与句 6（文档点名的已知误报）
    assert "超过六成的医疗影像团队" in _sentences(report)
    assert "把边界误差降低了" in _sentences(report)


def test_sample1_exemptions_hold():
    """三条豁免逐个钉住：有 `[n]`、模糊限定词、8 字窗内的自指词。"""
    report = run_check(SAMPLE_1, citations=CITATIONS)
    hits = _sentences(report)
    assert "Transformer 架构在长程依赖建模上优于卷积网络" not in hits  # 有 [1]
    assert "数据增强策略对最终性能的影响" not in hits  # 含「可能」
    assert "我们的实验结果显示" not in hits  # 自指词在 8 字窗内
    assert "有学者指出" not in hits  # 有 [2]


# ---------------------------------------------------------------- 样例二


def test_sample2_language_routing():
    """英文 · 顺序编码制：**不静默失效**，且报出的句给英文原文（E1）。"""
    lang, _ = detect_language(SAMPLE_2)
    assert lang == "en"
    report = run_check(SAMPLE_2, citations=CITATIONS)
    assert report["step"]["lang"] == "en"
    assert report["step"]["citation_style"] == "numeric"
    assert report["summary"]["reported"] == 2
    hits = _sentences(report)
    assert "A recent survey reported" in hits  # 真该报
    assert "reduced the boundary error" in hits  # 文档点名的已知误报
    # E1 的口径：报出来的是**英文原句**，不是拿中文顶替
    assert "调查显示" not in hits


def test_sample2_exemptions_hold():
    report = run_check(SAMPLE_2, citations=CITATIONS)
    hits = _sentences(report)
    assert "studies have shown" not in hits  # 有 [1]
    assert "have argued" not in hits  # 含 may
    assert "We found" not in hits  # 自指词 we 在 8 字符窗内
    assert "noted that existing methods" not in hits  # 有 [2]


# ---------------------------------------------------------------- 样例三（E2）


def test_sample3_author_year_does_not_explode():
    """⭐ 关键一篇：著者-出版年制**全文没有 `[n]`**，不许被全部误报。"""
    style, _ = detect_citation_style(SAMPLE_3)
    assert style == "author-year"
    report = run_check(SAMPLE_3)
    assert report["step"]["citation_style"] == "author-year"
    assert report["summary"]["reported"] == 0
    assert report["summary"]["unknown"] == 0


def test_sample3_year_only_parenthetical_counts_as_a_mark():
    """句 4 是「Wang 等（2022）」——**括号里只有年份**的那种著者-出版年写法。

    第一版的正则要求括号里有逗号，于是这句被判成"该引未引"（E2 的洞没堵严）。
    """
    report = run_check(SAMPLE_3)
    assert "Wang" not in _sentences(report)
    assert "泛化能力不足" not in _sentences(report)


# ---------------------------------------------------------------- 三篇合计


def test_three_samples_total():
    """三篇合计（有 E2 口径）：**报出 4 处、人工判定成立 2 处**。

    ⚠️ 人工判定那 2 处（样例一/二的句 3）与 2 处已知误报（句 6）在文档里逐句写着；
    这里只钉"报出 N"，M 是人工核对的结论（写在验收结论文档里）。
    """
    total = 0
    for sample in (SAMPLE_1, SAMPLE_2):
        total += run_check(sample, citations=CITATIONS)["summary"]["reported"]
    total += run_check(SAMPLE_3)["summary"]["reported"]
    assert total == 4
