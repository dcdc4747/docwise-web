from __future__ import annotations

from .base import TranslationEngine
from .open_source import OpenSourceEngine

_ENGINES: dict[str, type[TranslationEngine]] = {
    "open-source": OpenSourceEngine,
}


def get_engine(name: str = "open-source") -> TranslationEngine:
    """按名称取引擎实例。

    档位（fast/medium/precise）由调度器决定；底层引擎当前统一走 open-source，
    后续按档位可换。
    """
    try:
        engine_cls = _ENGINES[name]
    except KeyError as exc:
        raise ValueError(f"未知引擎: {name}") from exc
    return engine_cls()
