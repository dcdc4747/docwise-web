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


# ============================================================ 版面量（layout）

def test_paragraph_layout_matches_the_text_layer_contract() -> None:
    """键与口径必须和文字层那条路一致（`extract_blocks.py` 头部就是这份契约）。

    - `unit_h` ＝ 行高中位数（这里单位是**渲染图像素**，文字层那条路是字号 pt）；
    - 块矩形取各行的 min/max（**距页顶**）；
    - ⚠️ **没有 `bold`**：OCR 给不出加粗（引擎那条路也给不出）——
      `blocktypes` 在缺 `bold` 时按 0 处理，所以这里不是漏写。
    """
    module = _load("ocr_blocks")
    paragraph = [
        _line("第一行", 100, 200, 500, 220),  # 高 20
        _line("第二行", 104, 226, 500, 246),  # 高 20
        _line("第三行", 100, 252, 480, 270),  # 高 18
    ]

    layout = module.paragraph_layout(paragraph, page_h=2000)

    assert layout is not None
    assert set(layout) == {"unit_h", "x0", "y0", "x1", "y1", "page_h"}
    assert layout["unit_h"] == 20.0  # median(20, 20, 18) == 20
    assert layout["x0"] == 100.0
    assert layout["y0"] == 200.0
    assert layout["x1"] == 500.0
    assert layout["y1"] == 270.0
    assert layout["page_h"] == 2000.0


def test_paragraph_layout_without_page_height_is_none_not_zero() -> None:
    """⭐ **宁可没有，也不许编**：拿不到页高就整块不写（**不填 0**）。

    块上没有 `layout` 时，判级会自动退回"只看文字形状"——那是设计好的退路；
    填 0 反而会让 `unit_h <= 0` 的假信号进入判据。
    """
    module = _load("ocr_blocks")
    paragraph = [_line("正文一行", 100, 200, 500, 220)]

    assert module.paragraph_layout(paragraph, page_h=None) is None
    assert module.paragraph_layout(paragraph, page_h=0) is None
    assert module.paragraph_layout(paragraph, page_h=-1) is None


def test_paragraph_layout_without_usable_geometry_is_none() -> None:
    """算不出一条可用几何量（行高非正 / 键缺失 / 值不是数）→ None，不是 0。"""
    module = _load("ocr_blocks")

    assert module.paragraph_layout([], page_h=2000) is None
    assert (
        module.paragraph_layout([_line("坏行", 10, 100, 100, 100)], page_h=2000) is None
    )
    assert module.paragraph_layout([{"text": "缺几何量"}], page_h=2000) is None
    assert (
        module.paragraph_layout([_line("非数", 10, "x", 100, 120)], page_h=2000) is None
    )


def test_paragraph_layout_uses_usable_lines_and_ignores_broken_ones() -> None:
    """混着坏行时：**用能用的那几行**算（不做整段丢弃），但绝不替坏行编数。"""
    module = _load("ocr_blocks")
    paragraph = [
        _line("好行一", 100, 200, 500, 220),
        _line("坏行（零高）", 100, 230, 500, 230),
        _line("好行二", 100, 240, 460, 258),
    ]

    layout = module.paragraph_layout(paragraph, page_h=1000)

    assert layout is not None
    assert layout["unit_h"] == 19.0  # median(20, 18) == 19
    assert layout["x0"] == 100.0
    assert layout["x1"] == 500.0
    assert layout["y1"] == 258.0


def test_ocr_blocks_writes_layout_with_the_rendered_pixel_height(monkeypatch) -> None:
    """⭐ **接线**：真跑一遍 `ocr_blocks`（用假的 PyMuPDF / 假 OCR 运行时）。

    真 OCR 跑在引擎 Python 里（后端 venv 没有 PyMuPDF 与 OCR 运行时），所以这里把
    两个重依赖塞成假模块——**接线本身必须被钉住**，否则"补了纯函数却没接上"没人发现。

    钉三件：① 块上**有** `layout`；② `page_h` 取的是**渲染图的像素高**（不是页的点高）；
    ③ `unit_h` 就是行框高中位数。
    """
    import sys
    import types

    from app import storage

    module = _load("ocr_blocks")

    class _FakePixmap:
        width = 1600
        height = 2200

        def tobytes(self, _fmt: str) -> bytes:
            return b"png-bytes"

    class _FakePage:
        def get_pixmap(self, dpi: int = 72) -> _FakePixmap:
            assert dpi == module.RENDER_DPI
            return _FakePixmap()

    class _FakeDoc:
        page_count = 1

        def load_page(self, _page_no: int) -> _FakePage:
            return _FakePage()

        def __enter__(self) -> _FakeDoc:
            return self

        def __exit__(self, *_exc) -> None:
            return None

    def _box(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]

    def _fake_engine(_path: str):
        # 一行一段，两行：段内间距 26（≈1.3 倍行高）→ 按 pitch 判会并成一段
        return (
            [
                (_box(100, 200, 700, 220), "扫描件第一行文字", 0.99),
                (_box(100, 226, 700, 246), "扫描件第二行文字", 0.98),
            ],
            0.5,
        )

    monkeypatch.setitem(
        sys.modules, "fitz", types.SimpleNamespace(open=lambda _p: _FakeDoc())
    )
    monkeypatch.setitem(
        sys.modules,
        "rapidocr_onnxruntime",
        types.SimpleNamespace(RapidOCR=lambda: _fake_engine),
    )

    pdf_path = storage.uploads_dir() / "fake-scan-for-layout-test.pdf"
    blocks, reason = module.ocr_blocks(pdf_path)

    assert reason is None
    assert len(blocks) == 1
    layout = blocks[0]["layout"]
    assert layout is not None
    assert layout["page_h"] == 2200.0  # 渲染图像素高，不是页的点高
    assert layout["unit_h"] == 20.0  # 行框高（220-200、246-226）的中位数
    assert layout["x0"] == 100.0
    assert layout["y0"] == 200.0
    assert layout["x1"] == 700.0
    assert layout["y1"] == 246.0

