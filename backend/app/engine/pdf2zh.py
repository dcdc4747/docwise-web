from __future__ import annotations

from .base import TranslateRequest, TranslationEngine, TranslationResult


class Pdf2ZhEngine(TranslationEngine):
    """pdf2zh（PDFMathTranslate）引擎适配器，对应快档。

    依赖说明：pdf2zh 是外部重型依赖（含 babeldoc / OCR 资产，AGPL-3.0），
    接入阶段（任务 B3）需把它装进 backend 环境并在此实现：
        - 调用 pdf2zh 生成双语 PDF；
        - 把每个文本块的 success / overflow / failed 状态回填进 result.blocks。
    """

    name = "pdf2zh"

    def translate(self, request: TranslateRequest) -> TranslationResult:
        # TODO(阶段1/B3): 真正调用 pdf2zh 并回填每块状态。
        raise NotImplementedError("pdf2zh 适配器待接入（阶段1 B3）")
