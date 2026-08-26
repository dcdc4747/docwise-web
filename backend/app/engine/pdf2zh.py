from __future__ import annotations

from .base import TranslateRequest, TranslationEngine, TranslationResult


class Pdf2ZhEngine(TranslationEngine):
    """pdf2zh（PDFMathTranslate）引擎适配器，对应快档。

    依赖 pdf2zh（重型、AGPL-3.0），接入详见后端"引擎接入"任务。
    """

    name = "pdf2zh"

    def translate(self, request: TranslateRequest) -> TranslationResult:
        # TODO: 调用 pdf2zh 生成双语 PDF，并回填每块状态。
        raise NotImplementedError("pdf2zh 适配器待接入")
