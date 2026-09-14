from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from .base import CancelToken, TranslateRequest, TranslationResult
from .open_source import OpenSourceEngine

logger = logging.getLogger(__name__)

# 仓库自带的取字脚本（不翻译，只抽 PDF 文字层）。
# 与"外部翻译引擎"刻意分开：中文文献不需要翻译引擎，只需要一个能读 PDF 文字层的
# Python 环境（PyMuPDF），所以脚本是我们自己的，随仓库走。
BUNDLED_EXTRACTOR = (
    Path(__file__).resolve().parents[2] / "scripts" / "extract_blocks.py"
)


class NativeEngine(OpenSourceEngine):
    """不翻译的引擎：源语言与目标语言同为中文（等"不需要翻译"）时使用。

    它只做两件事：
    ① 抽 PDF 文字块（供导读/术语/问答，以及"点结论回原文那一句"）；
    ② 把原稿复制成产物（用户下载到的就是原文件，不改写、不重排）。

    译文一律为空（`translated=null`），这是**如实**而不是缺陷：中文文献没有译文；
    理解层取的是 `translated or text`，所以导读/问答/出处照样成立。

    复用 `OpenSourceEngine` 的子进程纪律（Popen + 轮询取消 + 超时 + 引擎日志），
    只是在缺少文字层（扫描件）时如实失败，不假装成功。
    """

    name = "native-engine"
    # 取字专属变量：DOCWISE_ENGINE_NATIVE_PYTHON，未配则回退 DOCWISE_ENGINE_PYTHON
    env_prefix = "DOCWISE_ENGINE_NATIVE"
    # 取字比翻译快得多，超时给短一些，出问题能更快暴露
    TIMEOUT_SECONDS = 600

    def translate(
        self, request: TranslateRequest, cancel: CancelToken | None = None
    ) -> TranslationResult:
        python = self._env("PYTHON")
        if not python:
            return self._failed(
                request,
                "未配置 DOCWISE_ENGINE_NATIVE_PYTHON / DOCWISE_ENGINE_PYTHON"
                "（中文文献取字需要它来读 PDF 文字层）",
            )
        # 刻意**不**回退到 DOCWISE_ENGINE_SCRIPT：那是**翻译**引擎的脚本，不是取字脚本
        script = (os.environ.get("DOCWISE_ENGINE_NATIVE_SCRIPT") or "").strip()
        script_path = Path(script) if script else BUNDLED_EXTRACTOR
        if not script_path.exists():
            return self._failed(request, f"取字脚本不存在：{script_path}")

        out_dir = request.output_dir or self._temp_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        result_file = out_dir / "result.json"
        result_file.unlink(missing_ok=True)

        cmd = [
            python,
            str(script_path),
            "--input", str(request.source_path),
            "--output", str(out_dir),
        ]
        outcome, proc, log_file = self._run_engine_command(cmd, out_dir, cancel)

        if outcome == "cancelled":
            logger.info("取字子进程已终止（用户取消）：%s", request.source_path)
            return self._cancelled(request)
        if outcome == "timeout":
            return self._failed(
                request,
                f"取字超过 {self.TIMEOUT_SECONDS} 秒未结束，已强制终止；"
                f"日志尾部：{self._log_tail(log_file)}",
            )

        return self._collect_result(request, result_file, log_file, proc)

    def _collect_result(  # noqa: D102 - 与父类同义，仅补一条中文文献的失败提示
        self,
        request: TranslateRequest,
        result_file: Path,
        log_file: Path,
        proc: subprocess.Popen,
    ) -> TranslationResult:
        result = super()._collect_result(request, result_file, log_file, proc)
        if result.status.value == "failed" and not result.blocks:
            # 取字最常见的失败是"没有文字层"，把话说清楚，别让用户以为是网络问题
            hint = result.error or "取字失败"
            if "文字层" not in hint:
                hint = f"{hint}（若这份 PDF 是扫描件或纯图片版，当前版本不支持）"
            result.error = hint
        return result
