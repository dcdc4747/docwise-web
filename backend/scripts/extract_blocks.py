"""取字脚本：给"不需要翻译"的文献（如中文文献）抽文字块并出原稿。

由 `NativeEngine` 以子进程调用（运行环境是**引擎 Python**，需要 PyMuPDF）。
产出与外部翻译引擎**同形**的 result.json，于是 worker、块级溯源、导读、
问答、FTS 检索这几条链路可以完全复用，不需要任何特判：

    {"status": "completed",
     "mono": "<原稿 PDF 的副本>",
     "dual": null,
     "blocks": [{"block_id": "p1_b0", "text": "……", "translated": null}, ...]}

三条纪律：
1. **不翻译**：`translated` 一律为 null。中文文献就是没有译文，前端据此只显示原文；
   理解层（导读/术语/问答）取的是 `translated or text`，所以照样能用。
2. **原稿即产物**：把上传的 PDF 复制成 mono，用户"下载"拿到的就是原文件，不做任何改写。
3. **抽不到就说抽不到**：没有文字层（扫描件）时 status=failed 并写明原因，绝不假装成功。

用法：
    python extract_blocks.py --input <源 PDF> --output <结果目录>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


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
            index = 0
            for item in page.get_text("blocks"):
                # item = (x0, y0, x1, y1, text, block_no, block_type)；
                # block_type=0 才是文字块（1 是图片块，跳过）
                if len(item) < 7 or item[6] != 0:
                    continue
                text = _block_text(item[4] or "")
                if not text:
                    continue
                blocks.append(
                    {
                        # 页号**从 0 起**：外部翻译引擎的包装脚本也是这么写的
                        # （`run_translation.py` 里 `enumerate` 出来的 pno），前端 `blockLabel` 统一 +1。
                        # 这里曾经写成 `page_no + 1`，导致中文文献的「第 X 页」整体多一页
                        # （实测：一份 8 页的文献，最后一块显示成"第 9 页"）。
                        "block_id": f"p{page_no}_b{index}",
                        "text": text,
                        "translated": None,
                    }
                )
                index += 1
            if bar is not None:
                bar.update(1)
        if bar is not None:
            bar.close()

    if not blocks:
        return {
            "status": "failed",
            "error": "这份 PDF 没有可抽取的文字层（可能是扫描件或纯图片版）",
            "blocks": [],
        }

    # 原稿即产物：复制成 mono，用户下载到的就是原文件
    mono = out_dir / f"{pdf_path.stem}_mono.pdf"
    shutil.copyfile(pdf_path, mono)

    return {
        "status": "completed",
        "mono": str(mono),
        "dual": None,
        "blocks": blocks,
        "error": None,
    }


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
    print(
        f"[extract] {pdf_path.name}: {payload['status']}，"
        f"{len(payload.get('blocks') or [])} 块",
        flush=True,
    )
    return 0 if payload["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
