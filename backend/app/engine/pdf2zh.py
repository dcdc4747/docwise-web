from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from .base import (
    BlockState,
    BlockStatus,
    TaskState,
    TranslateRequest,
    TranslationEngine,
    TranslationResult,
)

# pdf2zh 包装脚本（在开源方案实测克隆内，含独立 venv）。可用环境变量覆盖。
_DEFAULT_PY = (
    r"D:\新建文件夹\docwise-web项目\开源方案实测\PDFMathTranslate\.venv\Scripts\python.exe"
)
_DEFAULT_SCRIPT = (
    r"D:\新建文件夹\docwise-web项目\开源方案实测\PDFMathTranslate\run_translation.py"
)


class Pdf2ZhEngine(TranslationEngine):
    """pdf2zh（PDFMathTranslate）引擎适配器，对应快档。

    通过子进程调用 pdf2zh 包装脚本，产出 mono(单语即中文)/dual(双语) PDF，
    并抽取源文文字块作为"每块状态"。

    说明（阶段 1 粗粒度）：pdf2zh 本身不暴露"每块成败"，这里以
    "整体翻译完成→块标记成功、失败→块标记失败"作为粗粒度状态，
    后续再细化到"某块截断/溢出"级别。
    """

    name = "pdf2zh"

    def translate(self, request: TranslateRequest) -> TranslationResult:
        python = os.environ.get("PDF2ZH_PYTHON", _DEFAULT_PY)
        script = os.environ.get("PDF2ZH_SCRIPT", _DEFAULT_SCRIPT)
        out_dir = Path(tempfile.mkdtemp(prefix="docwise_p2z_"))
        result_file = out_dir / "result.json"

        cmd = [
            python,
            script,
            "--input", str(request.source_path),
            "--output", str(out_dir),
            "--lang-in", request.source_lang,
            "--lang-out", request.target_lang,
            "--service", "deepseek",
            "--thread", "2",
        ]
        subprocess.run(cmd, env=os.environ.copy(), timeout=1800)

        if not result_file.exists():
            return TranslationResult(
                task_id=str(request.source_path),
                translated_path=None,
                blocks=[],
                status=TaskState.FAILED,
                error="pdf2zh 未返回 result.json",
            )

        payload = json.loads(result_file.read_text(encoding="utf-8"))
        completed = payload.get("status") == "completed"
        blocks = [
            BlockStatus(
                block_id=item["block_id"],
                text=item["text"],
                status=BlockState.SUCCESS if completed else BlockState.FAILED,
            )
            for item in payload.get("blocks", [])
        ]

        translated = Path(payload["mono"]) if payload.get("mono") else None
        if translated is None and payload.get("dual"):
            translated = Path(payload["dual"])

        return TranslationResult(
            task_id=str(request.source_path),
            translated_path=translated,
            blocks=blocks,
            status=TaskState.COMPLETED if completed else TaskState.FAILED,
            progress=1.0 if completed else 0.0,
            error=payload.get("error"),
        )
