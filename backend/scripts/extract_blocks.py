"""取字脚本：给"不需要翻译"的文献（如中文文献）抽文字块并出原稿。

由 `NativeEngine` 以子进程调用（运行环境是**引擎 Python**，需要 PyMuPDF）。
产出与外部翻译引擎**同形**的 result.json，于是 worker、块级溯源、导读、
问答、FTS 检索这几条链路可以完全复用，不需要任何特判：

    {"status": "completed",
     "mono": "<原稿 PDF 的副本>",
     "dual": null,
     "blocks": [{"block_id": "p1_b0", "text": "……", "translated": null,
                 "layout": {"unit_h": 10.0, "bold": 0.0,
                             "y0": 142.6, "page_h": 808.0}}, ...]}

**`layout` 是版面信号契约（2026-09-30 起）**：三条取字路（文字层 / 扫描件 OCR /
外部翻译引擎）各自把"手里本来就有的版面量"按**同一套键**带出来，判定仍然只在
`backend/app/blocktypes.py` 一处做（三条路各判一遍口径必然漂移）：

    - `unit_h`：一行有多高。文字层＝**字号**（pt）；
      OCR＝**行高中位数**（px）；引擎＝段落字号。
  **不同路的量纲不同，只比"同篇内的相对大小"，绝不跨路比绝对值。**
- `bold`：加粗字符占比 0–1（**只有文字层与引擎给得出**；OCR 没有这个概念，留空）。
- `y0` / `page_h`：段落顶端到页面顶端的距离 / 页高（都用同一坐标系，只用来算相对位置）。

**摸不到这些量时一律留空**（老任务、认不出的页），分级器自动退回"只看文字形状"——
与今天的表现完全一致，不会因为缺字段而变差。

三条纪律：
1. **不翻译**：`translated` 一律为 null。中文文献就是没有译文，前端据此只显示原文；
   理解层（导读/术语/问答）取的是 `translated or text`，所以照样能用。
2. **原稿即产物**：把上传的 PDF 复制成 mono，用户"下载"拿到的就是原文件，不做任何改写。
3. **抽不到就说抽不到**：先读文字层；**扫描件（没有文字层）自动改走本地 OCR**
   （`ocr_blocks.py`，离线、零成本）；连 OCR 都认不出内容时 status=failed 并写明原因，
   **绝不假装成功**。`result.json` 里多一个 `mode` 字段（`text-layer` / `ocr`）
   说明这批字是怎么来的，并打进引擎日志——扫描件的字是 OCR 认的、可能有个别错字，
   不能和文字层混为一谈。

用法：
    python extract_blocks.py --input <源 PDF> --output <结果目录>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

# 与兄弟模块（ocr_blocks.py）同目录，按脚本位置找，别依赖调用方的 cwd
sys.path.insert(0, Path(__file__).resolve().parent.as_posix())


def _join_lines(lines: list[str]) -> str:
    """把块内多行拼成一段：中文行直接接上，英文行之间补空格，英文连字符断行接回。"""
    out = ""
    for line in lines:
        if not out:
            out = line
            continue
        prev = out[-1]
        # 英文单词被断行（末尾是连字符）→ 去掉连字符直接接上
        if prev == "-" and len(out) >= 2 and out[-2].isascii() and out[-2].isalpha():
            out = out[:-1] + line
        elif (
            prev.isascii()
            and prev.isalnum()
            and line[0].isascii()
            and line[0].isalnum()
        ):
            out = f"{out} {line}"
        else:
            out = out + line
    return out


def _block_text(raw: str) -> str:
    return _join_lines([ln.strip() for ln in raw.splitlines() if ln.strip()])


def _page_blocks(page, page_no: int) -> list[dict]:
    """一页 → 文字块（带版面信号）。

    **切段与块号必须与旧实现逐字一致**（2026-09-30 换读法时实测对照过：中文样本
    257 块 → 257 块、逐块文本 257 相同 / 0 不同）。`block_id` 是译文、出处、FTS 检索的
    共同锚点，换读法若让切段变了，老任务与新任务就对不上——所以这里刻意保持：
    块顺序、块边界、跨行拼接方式都与 `page.get_text("blocks")` 那条路一致，
    只是**多读了字号 / 加粗 / 位置**（旧路把这三样当场丢掉了）。

    为什么要换：`blocks` 模式只给 7 元组（没有字体信息），`dict` 模式才给 span 的
    `size`/`flags`/`font`。实测这一条让中文文献的章节标题**全部**被挑出来
    （正文 10.0pt，标题 12.0pt：`1. 引言`/`2. 理论基础`/…/`参考文献` 一个不漏）。
    """
    import statistics

    out: list[dict] = []
    index = 0
    page_h = float(page.rect.height) or 1.0
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:  # 1 是图片块，跳过（与旧实现一致）
            continue
        lines = []
        spans = []
        for line in block["lines"]:
            line_text = "".join(span["text"] for span in line["spans"])
            if line_text.strip():
                lines.append(line_text)
            spans.extend(span for span in line["spans"] if span["text"].strip())
        if not lines or not spans:
            continue
        text = _join_lines([line.strip() for line in lines if line.strip()])
        if not text:
            continue

        sizes = [float(span["size"]) for span in spans]
        bold_chars = sum(
            len(span["text"]) for span in spans if span.get("flags", 0) & 16
        )
        total_chars = sum(len(span["text"]) for span in spans) or 1
        out.append(
            {
                "block_id": f"p{page_no}_b{index}",
                "text": text,
                "translated": None,
                "layout": {
                        # 行高（这里＝字号）；bold 是加粗字符占比；
                        # y0/page_h 只用来算相对位置
                    "unit_h": round(statistics.median(sizes), 1),
                    "bold": round(bold_chars / total_chars, 2),
                    "y0": round(float(block["bbox"][1]), 1),
                    "page_h": round(page_h, 1),
                },
            }
        )
        index += 1
    return out


def _make_bar(total: int):
    """进度条：有 tqdm 就用（父进程的 progress.py 能解析它），没有就不报进度。

    绝不自己编百分比——解析不到时前端会显示"引擎还没报进度"。
    """
    try:
        from tqdm import tqdm  # type: ignore
    except ImportError:
        return None
    return tqdm(total=total, desc="extract", file=sys.stderr)


def extract(pdf_path: Path, out_dir: Path) -> dict:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return {
            "status": "failed",
            "error": "引擎环境缺少 PyMuPDF，无法抽取 PDF 文字层（中文文献取字需要它）",
            "blocks": [],
        }

    blocks: list[dict] = []
    with fitz.open(str(pdf_path)) as doc:
        total = doc.page_count
        bar = _make_bar(total)
        for page_no in range(total):
            page = doc.load_page(page_no)
            for block in _page_blocks(page, page_no):
                blocks.append(block)
            if bar is not None:
                bar.update(1)
        if bar is not None:
            bar.close()

    mode = "text-layer"
    if not blocks:
        # 文字层是空的（扫描件 / 纯图片版）→ 本地 OCR 兜底。
        # 实测一份 8 页中文扫描件：约 9 秒/页、置信度 0.99–1.00、离线零成本。
        print(f"[extract] {pdf_path.name} 没有文字层，改用本地 OCR", flush=True)
        blocks, reason = _ocr_fallback(pdf_path)
        if not blocks:
            return {
                "status": "failed",
                "error": (
                    "这份 PDF 没有可抽取的文字层（扫描件或纯图片版），"
                    f"本地 OCR 也没能识别出文字：{reason}"
                ),
                "blocks": [],
            }
        mode = "ocr"

    # 原稿即产物：复制成 mono，用户下载到的就是原文件
    mono = out_dir / f"{pdf_path.stem}_mono.pdf"
    shutil.copyfile(pdf_path, mono)

    return {
        "status": "completed",
        "mono": str(mono),
        "dual": None,
        "blocks": blocks,
        "mode": mode,
        "error": None,
    }


def _ocr_fallback(pdf_path: Path) -> tuple[list[dict], str]:
    """扫描件兜底：本地 OCR 取字。返回 `(blocks, 失败原因)`。"""
    try:
        import ocr_blocks  # 同目录（sys.path 已插入脚本目录）
    except ImportError as exc:
        return [], f"取字环境缺少 OCR 模块：{exc}"

    bar = _make_bar(_page_count(pdf_path))
    try:
        return ocr_blocks.ocr_blocks(pdf_path, on_page=lambda _pno: _tick(bar))
    except Exception as exc:  # noqa: BLE001 - 失败要如实回传，不能让父进程拿到半截结果
        return [], str(exc)
    finally:
        if bar is not None:
            bar.close()


def _page_count(pdf_path: Path) -> int:
    try:
        import fitz

        with fitz.open(str(pdf_path)) as doc:
            return doc.page_count
    except Exception:  # noqa: BLE001 - 只是为了画进度条，数不出来就不画
        return 0


def _tick(bar) -> None:
    if bar is not None:
        bar.update(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="中文（不翻译）文献取字：抽文字块 + 出原稿"
    )
    parser.add_argument("--input", required=True, help="源 PDF 路径")
    parser.add_argument("--output", required=True, help="结果目录")
    # 允许父进程多传参数（与外部翻译引擎的调用形式保持一致），不认识的忽略
    args, _unknown = parser.parse_known_args(argv)

    pdf_path = Path(args.input)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    result_file = out_dir / "result.json"

    if not pdf_path.exists():
        payload = {
            "status": "failed",
            "error": f"源文件不存在：{pdf_path}",
            "blocks": [],
        }
    else:
        try:
            payload = extract(pdf_path, out_dir)
        except Exception as exc:  # noqa: BLE001 - 失败必须写进 result.json，让父进程能如实落库
            payload = {"status": "failed", "error": f"取字失败：{exc}", "blocks": []}

    result_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    mode = payload.get("mode")
    print(
        f"[extract] {pdf_path.name}: {payload['status']}，"
        f"{len(payload.get('blocks') or [])} 块"
        + (f"（取字方式：{mode}）" if mode else ""),
        flush=True,
    )
    return 0 if payload["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
