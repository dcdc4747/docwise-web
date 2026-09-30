"""扫描件取字：本地 OCR → 按版面关系合并成段落块。

为什么要有它：`extract_blocks.py` 直接读 PDF 文字层，**扫描件（纯图片）读出来是空的**，
而扫描件在真实文献里很常见（期刊影印、老论文、别人发来的截图版 PDF）。

用的是**本地 ONNX OCR**：模型随包自带（约 16 MB）、**完全离线、零成本、
不需要 API key**。实测一份 8 页中文扫描件约 9 秒/页、识别置信度 0.99–1.00。
它跑在**引擎 Python** 里，所以依赖（OCR 运行时 / PyMuPDF）不进后端依赖表。

**段落怎么合并**：OCR 给的是"一行一行"的框，而产品要的是"一段一段"的块。

- 同一栏：两行横向重叠 ≥ 较短行宽的 30%（双栏排版不串行）
- 行距：按**页面自己算出的行距基准**判（相邻行基线间距的中位数），
  间距 ≤ 1.25 × 基准算同一段。**不用"倍数 × 行高"**——OCR 框紧贴字形，
  同页行高能差 25%（实测 51–65px），而基线间距很稳（段内 113–122px）。
  实测：段内 ≈ 1.00 × 基准，段间 ≥ 1.33 × 基准。
- 首行缩进：下一行相对上一行缩进 ≥ 行高的 0.8 倍 → 不是同一段
  （中文期刊段间**不空行**，只靠缩进区分；实测敬语行与正文首行间距与段内一致，
  只能靠这条分）

**用并查集两两合并，不依赖行的先后顺序**：OCR 在双栏排版上给出的行序是混的
（左栏一行、右栏一行交替），只跟"上一行"比会把双栏切成一行一段。

模块顶部故意**不导入**任何第三方库：纯函数要能在后端 venv（没有 PyMuPDF / OCR 运行时）
里被单测；重依赖都在函数里 import。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 段落合并阈值
#
# ⚠️ 别用"倍数 × 行高"：OCR 的框是**紧贴字形**的，同一页不同行的框高能差 25%
# （实测 51–65px，因为带括号/引号的行更高），而**基线间距很稳**（实测段内 113–122px）。
# 用 1.8×行高 会把段内行判成段间——实测就是这样：整页被切成一行一块。
# 所以按页面自己算出的行距基准（pitch）来判：
#   - 段内：间距 ≈ 1.00 × pitch，实测 113–122
#   - 段间：间距 ≥ 1.33 × pitch，实测 155.5 / 227.9 / 261.5
# 取 1.25 落在两簇中间（上下各留约 0.08–0.1 的余量）。
PARAGRAPH_GAP_RATIO = 1.25
# 没有足够行用来估 pitch 时的退路：按行高判（前端 PDF 那套阈值，用于 PDF 坐标）
LINE_GAP_RATIO = 1.8
# 同一栏：横向重叠 ≥ 较短行宽的 30%
OVERLAP_RATIO = 0.3
# 首行缩进：相对上一行缩进 ≥ 行高的 0.8 倍 → 不是同一段
INDENT_RATIO = 0.8
# 行距基准最多认到 5 倍：再大就不是同一页正文的节奏了（插图、跨栏间隔）
PITCH_MAX_RATIO = 5.0
# 至少要有这么多条正间距才敢信"中位数就是行距"：只有两三行的页面里，
# 中位数本身就是段间距，拿它当基准等于把每两段并成一段。样本不够就退回按行高判。
MIN_PITCH_SAMPLES = 4
# OCR 置信度低于这个值就当没认出来：宁可少一块，也不要往理解层塞垃圾
MIN_SCORE = 0.5
# 渲染分辨率：200 DPI 实测够清楚（再高只是更慢）
RENDER_DPI = 200


def _overlap_ratio(a: dict, b: dict) -> float:
    """两行在横向上的重叠占较短那行的比例（判断是否同一栏）。"""
    left = max(a["x0"], b["x0"])
    right = min(a["x1"], b["x1"])
    overlap = right - left
    if overlap <= 0:
        return 0.0
    shorter = max(min(a["x1"] - a["x0"], b["x1"] - b["x0"]), 1e-6)
    return overlap / shorter


def _line_pitch(lines: list[dict]) -> float:
    """页面行距基准：相邻行基线间距的**中位数**；样本太少返回 0（退回按行高判）。

    只取正的间距（同一横排上的左右两块算 0，要排除）；中位数天然抗离群值，
    所以页里夹着插图、跨栏大间隔也不会把基准带歪。
    """
    baselines = sorted(round(line["y1"], 1) for line in lines)
    gaps = [later - earlier for earlier, later in zip(baselines, baselines[1:])]
    positive = [gap for gap in gaps if gap > 0]
    if len(positive) < MIN_PITCH_SAMPLES:
        return 0.0
    return positive[len(positive) // 2]


def _mergeable(
    a: dict,
    b: dict,
    *,
    pitch: float,
    overlap: float,
    indent: float,
    line_gap: float,
) -> bool:
    """两行是否属于同一段：同一栏 + 行距够近 + 没有首行缩进。"""
    if _overlap_ratio(a, b) < overlap:
        return False
    height = max(min(a["y1"] - a["y0"], b["y1"] - b["y0"]), 1.0)
    upper, lower = (a, b) if a["y1"] <= b["y1"] else (b, a)
    # 用**基线**间距（框底 ≈ 基线），不是框底到框顶的空隙：
    # 段间不空行的中文文献只靠缩进 + 行距区分，用空隙判会把整篇并成一段
    gap = lower["y1"] - upper["y1"]
    limit = pitch * PARAGRAPH_GAP_RATIO if pitch > 0 else line_gap * height
    if gap > limit:
        return False
    # 新一段的首行会相对上一行缩进；缩进够多就不是同一段
    # （实测：敬语行与正文首行间距与段内一致，只靠这条区分）
    return (lower["x0"] - upper["x0"]) < indent * height


def group_paragraphs(
    lines: list[dict],
    *,
    line_gap: float = LINE_GAP_RATIO,
    overlap: float = OVERLAP_RATIO,
    indent: float = INDENT_RATIO,
) -> list[list[dict]]:
    """把 OCR 的单行框合并成段落（纯函数，可单测）。

    每行是一个 dict：`{"text", "x0", "y0", "x1", "y1", "score"}`。
    返回按阅读顺序（先上后下、先左后右）排好的段落列表。
    """
    if not lines:
        return []

    pitch = _line_pitch(lines)
    parent = list(range(len(lines)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(i: int, j: int) -> None:
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            parent[root_j] = root_i

    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            if _mergeable(
                lines[i],
                lines[j],
                pitch=pitch,
                overlap=overlap,
                indent=indent,
                line_gap=line_gap,
            ):
                union(i, j)

    grouped: dict[int, list[dict]] = {}
    for index, line in enumerate(lines):
        grouped.setdefault(find(index), []).append(line)

    paragraphs = [
        sorted(group, key=lambda item: (round(item["y0"], 1), item["x0"]))
        for group in grouped.values()
    ]
    paragraphs.sort(key=lambda group: (round(group[0]["y0"], 1), group[0]["x0"]))
    return paragraphs


def _join_lines(texts: list[str]) -> str:
    """块内多行拼成一段：中文直接接上，英文之间补空格，英文连字符断行接回。"""
    out = ""
    for text in texts:
        text = text.strip()
        if not text:
            continue
        if not out:
            out = text
            continue
        prev = out[-1]
        if prev == "-" and len(out) >= 2 and out[-2].isascii() and out[-2].isalpha():
            out = out[:-1] + text
        elif (
            prev.isascii()
            and prev.isalnum()
            and text[0].isascii()
            and text[0].isalnum()
        ):
            out = f"{out} {text}"
        else:
            out = out + text
    return out


def _ocr_lines(image_path: Path, engine) -> list[dict]:
    """一张页面图 → 行框列表。"""
    result, _elapse = engine(str(image_path))
    lines: list[dict] = []
    for box, text, score in result or []:
        text = (text or "").strip()
        if not text or float(score) < MIN_SCORE:
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        lines.append(
            {
                "text": text,
                "x0": min(xs),
                "y0": min(ys),
                "x1": max(xs),
                "y1": max(ys),
                "score": float(score),
            }
        )
    return lines


def ocr_blocks(pdf_path: Path, *, on_page=None) -> tuple[list[dict], str | None]:
    """扫描件 → 文字块。返回 `(blocks, 失败原因)`：成功时原因给 None。

    `block_id` 沿用 `p{页序}_b{页内序}`（页序从 0 起，前端统一 +1 显示）；
    `translated` 一律 None——这里只取字，翻不翻由调用方决定。
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return [], "引擎环境缺少 PyMuPDF，无法把扫描件渲染成图片来做 OCR"

    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return [], "引擎环境没有本地 OCR 运行时，无法识别扫描件"

    engine = RapidOCR()
    blocks: list[dict] = []
    scratch: list[Path] = []

    with fitz.open(str(pdf_path)) as doc:
        for page_no in range(doc.page_count):
            page = doc.load_page(page_no)
            image_path = pdf_path.parent / f".ocr_{pdf_path.stem}_{page_no}.png"
            image_path.write_bytes(page.get_pixmap(dpi=RENDER_DPI).tobytes("png"))
            scratch.append(image_path)
            try:
                lines = _ocr_lines(image_path, engine)
            except Exception as exc:  # noqa: BLE001 - 单页失败不该毁掉整篇
                print(f"[ocr] 第 {page_no + 1} 页识别失败：{exc}", file=sys.stderr)
                lines = []
            for index, paragraph in enumerate(group_paragraphs(lines)):
                text = _join_lines([item["text"] for item in paragraph])
                if not text:
                    continue
                blocks.append(
                    {
                        "block_id": f"p{page_no}_b{index}",
                        "text": text,
                        "translated": None,
                    }
                )
            if on_page is not None:
                on_page(page_no)

    for path in scratch:
        path.unlink(missing_ok=True)

    if not blocks:
        return [], "OCR 也没能识别出文字（可能是空白页、纯图表页，或图片太模糊）"
    return blocks, None
