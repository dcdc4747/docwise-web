"""排版翻译 + 抽取源文文字块 + 输出结果 JSON 的 CLI（供 docwise 后端子进程调用）。

用法（与快档 run_translation.py 同构，后端已按此参数调用）：
    python run_translation.py --input <pdf> --output <dir> [--lang-in en] [--lang-out zh]
                              [--service deepseek] [--thread 2]

翻译服务走 OpenAI 兼容接口（DeepSeek）。依赖环境变量：
    DEEPSEEK_API_KEY / DEEPSEEK_MODEL / DEEPSEEK_BASE_URL
    （读不到时回退到 OpenAITranslator 默认，实际请照后端 .env 配好）

产物：<原名>.<lang_out>.mono.pdf / <原名>.<lang_out>.dual.pdf（在 --output 目录），
并写 result.json（mono/dual 路径 + 每块文字块 + status/error），供 docwise 读取。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, Path(__file__).resolve().parent.as_posix())

import pymupdf  # noqa: E402


def extract_blocks(pdf_path: str) -> list[dict]:
    """按页抽取文字层文本块（段落级），用于"每块状态"展示。"""
    doc = pymupdf.open(pdf_path)
    blocks: list[dict] = []
    bid = 0
    for pno, page in enumerate(doc):
        for b in page.get_text("blocks") or []:
            text = (b[4] or "").strip()
            if text:
                blocks.append({"block_id": f"p{pno}_b{bid}", "text": text})
                bid += 1
    doc.close()
    return blocks


def _find_output(out_dir: Path, lang_out: str, stem: str) -> tuple[str | None, str | None]:
    """在输出目录里找引擎产出的 mono/dual PDF。"""
    mono, dual = None, None
    for candidate in ("", ".decompressed"):
        m = out_dir / f"{stem}{candidate}.{lang_out}.mono.pdf"
        d = out_dir / f"{stem}{candidate}.{lang_out}.dual.pdf"
        if m.exists() and mono is None:
            mono = str(m)
        if d.exists() and dual is None:
            dual = str(d)
    return mono, dual


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--lang-in", default="en")
    ap.add_argument("--lang-out", default="zh")
    ap.add_argument("--service", default="deepseek")
    ap.add_argument("--thread", type=int, default=2)
    args = ap.parse_args()

    input_pdf = Path(args.input)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = input_pdf.stem

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    doclayout_engine_cmd = [
        sys.executable,
        "-m",
        "doclayout_engine",
        "--files",
        str(input_pdf),
        "--output",
        str(out_dir),
        "--lang-in",
        args.lang_in,
        "--lang-out",
        args.lang_out,
        "--openai",
        "--openai-model",
        model,
        "--openai-base-url",
        base_url,
        "--openai-api-key",
        api_key,
        "--watermark-output-mode",
        "no_watermark",
        "--pool-max-workers",
        str(args.thread),
    ]

    try:
        subprocess.run(doclayout_engine_cmd, check=True, env=os.environ.copy(), timeout=3600)
        mono, dual = _find_output(out_dir, args.lang_out, stem)
        blocks = extract_blocks(str(input_pdf))
        result = {
            "mono": mono,
            "dual": dual,
            "blocks": blocks,
            "status": "completed" if mono or dual else "failed",
            "error": None if (mono or dual) else "未找到引擎输出 PDF",
        }
        code = 0
    except Exception as exc:  # noqa: BLE001 - 把失败如实回传
        mono, dual = _find_output(out_dir, args.lang_out, stem)
        blocks = extract_blocks(str(input_pdf))
        result = {
            "mono": mono,
            "dual": dual,
            "blocks": blocks,
            "status": "failed",
            "error": str(exc),
        }
        code = 1

    out_json = out_dir / "result.json"
    out_json.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(out_json)
    return code


if __name__ == "__main__":
    sys.exit(main())
