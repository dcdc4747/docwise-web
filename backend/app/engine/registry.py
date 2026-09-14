from __future__ import annotations

from .base import Tier, TranslationEngine
from .medium import MediumEngine
from .native import NativeEngine
from .open_source import OpenSourceEngine

_ENGINES: dict[str, type[TranslationEngine]] = {
    Tier.FAST.value: OpenSourceEngine,
    Tier.MEDIUM.value: MediumEngine,
    # 精档后续阶段实现，暂用中档引擎兜底
    Tier.PRECISE.value: MediumEngine,
}

# 算作"中文"的语言标记（"不需要翻译"的判据）
_NATIVE_LANGS = ("zh", "cn", "chinese")


def is_native_language(lang: str | None) -> bool:
    """这个语言标记算不算中文。"""
    if not lang:
        return False
    return lang.strip().lower().startswith(_NATIVE_LANGS)


def is_native_pair(source_lang: str | None, target_lang: str | None = None) -> bool:
    """源语言与目标语言都是中文 → 不需要翻译，走取字引擎。

    **两个都要判**：只判源语言会把"中文 → 英文"这种**翻译**任务误判成取字。
    """
    if not is_native_language(source_lang):
        return False
    return target_lang is None or is_native_language(target_lang)


def get_engine(
    tier: Tier | str = Tier.FAST,
    source_lang: str | None = None,
    target_lang: str | None = None,
) -> TranslationEngine:
    """按"语言对 + 档位"取引擎实例。

    中文文献（源=目标=中文）不需要翻译，直接走 NativeEngine 抽字；
    其余情况按档位取翻译引擎（快档 / 中档）。
    """
    if is_native_pair(source_lang, target_lang):
        return NativeEngine()
    key = tier.value if isinstance(tier, Tier) else str(tier)
    try:
        engine_cls = _ENGINES[key]
    except KeyError as exc:
        raise ValueError(f"未知档位: {key}") from exc
    return engine_cls()
