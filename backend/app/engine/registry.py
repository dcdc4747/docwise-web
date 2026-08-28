from __future__ import annotations

from .base import Tier, TranslationEngine
from .medium import MediumEngine
from .open_source import OpenSourceEngine

_ENGINES: dict[str, type[TranslationEngine]] = {
    Tier.FAST.value: OpenSourceEngine,
    Tier.MEDIUM.value: MediumEngine,
    # 精档后续阶段实现，暂用中档引擎兜底
    Tier.PRECISE.value: MediumEngine,
}


def get_engine(tier: Tier | str = Tier.FAST) -> TranslationEngine:
    """按档位取引擎实例。"""
    key = tier.value if isinstance(tier, Tier) else str(tier)
    try:
        engine_cls = _ENGINES[key]
    except KeyError as exc:
        raise ValueError(f"未知档位: {key}") from exc
    return engine_cls()
