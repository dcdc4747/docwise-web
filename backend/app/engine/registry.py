from __future__ import annotations

from .base import TranslationEngine
from .pdf2zh import Pdf2ZhEngine

_ENGINES: dict[str, type[TranslationEngine]] = {
    "pdf2zh": Pdf2ZhEngine,
}


def get_engine(name: str = "pdf2zh") -> TranslationEngine:
    """按名称取引擎实例。

    档位（fast/medium/precise）由调度器决定；底层引擎当前统一走 pdf2zh，
    后续按档位可换成 babeldoc。
    """
    try:
        engine_cls = _ENGINES[name]
    except KeyError as exc:
        raise ValueError(f"未知引擎: {name}") from exc
    return engine_cls()
