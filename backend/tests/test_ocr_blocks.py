"""扫描件取字（本地 OCR）的单元测试。

真 OCR 跑在**引擎 Python** 里（需要 PyMuPDF + OCR 运行时），pytest 这套环境没有，
所以这里锁两件能锁住的事：

1. **段落合并的纯函数**——OCR 给的是"一行一行"的框，产品要的是"一段一段"的块。
   阈值错一点，整篇就会并成一段（中文期刊段间不空行），或者把双栏串起来。
   测试数据取自真实扫描件的实测几何（行高约 12pt、段内基线距 14.7、段间 25.3）。
2. **接线**：取字脚本能在没有 OCR 能力的环境里**优雅失败**（返回原因，不抛异常），
   并且模块导入不依赖任何第三方库（否则后端 venv 里连导入都做不到）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader, f"加载不了脚本：{name}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _line(text: str, x0: float, y0: float, x1: float, y1: float, score: float = 1.0):
    return {"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "score": score}


def test_ocr_module_imports_without_third_party() -> None:
    """模块顶部不许 import 第三方库：后端 venv（没有 PyMuPDF / OCR）也要能加载它。"""
    module = _load("ocr_blocks")
    assert callable(module.group_paragraphs)
    assert callable(module.ocr_blocks)


def test_adjacent_lines_merge_into_one_paragraph() -> None:
    """段内：基线间距 14.7pt ≈ 1.2 倍行高（12pt）→ 同一段。"""
    module = _load("ocr_blocks")
    lines = [
        _line("第一行文字内容", 100, 100, 400, 112),
        _line("第二行接着写", 100, 114.7, 400, 126.7),
        _line("第三行还在同一段", 100, 129.4, 400, 141.4),
    ]

    paragraphs = module.group_paragraphs(lines)

    assert len(paragraphs) == 1
    assert len(paragraphs[0]) == 3


def test_bigger_line_gap_starts_new_paragraph() -> None:
    """段间：基线间距 25.3pt > 1.8 倍行高 → 另起一段（中文期刊段间不空行）。"""
    module = _load("ocr_blocks")
    lines = [
        _line("上一段的最后一行", 100, 100, 400, 112),
        _line("下一段的第一行", 100, 125.3, 400, 137.3),
    ]

    paragraphs = module.group_paragraphs(lines)

    assert len(paragraphs) == 2


def test_first_line_indent_starts_new_paragraph() -> None:
    """首行缩进：相对本段左边界缩进 ≥ 0.8 倍行高 → 另起一段。"""
    module = _load("ocr_blocks")
    lines = [
        _line("上一段第一行", 100, 100, 400, 112),
        _line("上一段第二行", 100, 114.7, 400, 126.7),
        # 缩进 24pt（约两个汉字）> 0.8 × 12
        _line("缩进的新段落", 124, 129.4, 400, 141.4),
    ]

    paragraphs = module.group_paragraphs(lines)

    assert len(paragraphs) == 2
    assert paragraphs[1][0]["text"] == "缩进的新段落"


def test_two_columns_do_not_merge() -> None:
    """双栏：左右栏横向不重叠 → 不能并成一段（并了就是串行）。"""
    module = _load("ocr_blocks")
    lines = [
        _line("左栏第一行", 60, 100, 300, 112),
        _line("右栏第一行", 340, 100, 580, 112),
        _line("左栏第二行", 60, 114.7, 300, 126.7),
    ]

    paragraphs = module.group_paragraphs(lines)

    assert len(paragraphs) == 2
    assert [p[0]["text"] for p in paragraphs] == ["左栏第一行", "右栏第一行"]


def test_join_lines_handles_cjk_and_english() -> None:
    """块内拼接：中文直接接、英文补空格、英文连字符断行接回。"""
    module = _load("ocr_blocks")

    assert module._join_lines(["这是一段中文", "被折行了"]) == "这是一段中文被折行了"
    assert module._join_lines(["hello world", "again"]) == "hello world again"
    assert module._join_lines(["trans-", "lation"]) == "translation"


def test_ocr_fallback_reports_cleanly_without_engine_deps() -> None:
    """没有 OCR / PyMuPDF 的环境里：返回原因，不能抛异常（父进程要据此如实落库）。"""
    module = _load("extract_blocks")

    blocks, reason = module._ocr_fallback(Path("nowhere-scan.pdf"))

    assert blocks == []
    assert reason


def test_extractor_prefers_text_layer_before_ocr() -> None:
    """纪律：先读文字层，只有读不出东西才走 OCR（别把有文字层的文献也丢给 OCR）。"""
    source = (SCRIPTS / "extract_blocks.py").read_text(encoding="utf-8")

    assert "if not blocks:" in source
    assert "_ocr_fallback" in source
    # 取字方式要写进 result.json，别让 OCR 的字和文字层混为一谈
    assert '"mode": mode' in source
