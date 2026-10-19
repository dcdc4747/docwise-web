"""「读懂」的收尾校验：剔除不合格出处，报告可定位率。

`runtime.py` 在模型答完后调用这里。它只做**质量指标 + 明显不合格的引用**：
块号是否真实存在由 runtime 另行核对（它只保留工具真返回过的块号）。
本模块**不查库**，纯函数，方便单测。
"""

from __future__ import annotations

import re

# 合法块号：p<页>_b<块>（例如 p0_b4 / p12_b3）
_BLOCK_ID_RE = re.compile(r"^p\d+_b\d+$")
# 正文里的裸块号：只提醒，不改答案文本
_BARE_ID_RE = re.compile(
    r"(?<![A-Za-z0-9_])p\d+_b\d+(?![A-Za-z0-9_])"
)

_MAX_SOURCES = 20
_LONG_ANSWER = 80


def locatable_rate(raw_count: int, kept_count: int) -> float | None:
    """保留数 / 原始给出数；原始为 0 时返回 None（不写 1.0）。"""
    if raw_count <= 0:
        return None
    return kept_count / raw_count


def _short(text: str, limit: int = 24) -> str:
    """把过长/空的编号缩成能放进 note 的样子。"""
    text = text.strip() or "空编号"
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def verify_sources(ctx, output) -> tuple[object, list[str]]:
    """校验回答里的出处编号，返回 (新输出, 说明列表)。

    规则：
    1. 编号格式必须形如 `p0_b4`，不合的剔掉并点名；
    2. 去重（保序），最多保留 20 个；
    3. 原始出处为 0 时，可定位率是 None，不写 100%；
    4. 正文提到块号却没登记为出处时只提醒，不改文本；
    5. 空出处但答案很长（> 80 字）时提醒"没有给出处"；
    6. **不改原对象**，用 `model_copy` 返回新对象。
    """
    answer = str(getattr(output, "answer", "") or "")
    raw = [
        str(item)
        for item in (getattr(output, "source_block_ids", []) or [])
    ]
    notes: list[str] = []

    kept: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for block_id in raw:
        if not _BLOCK_ID_RE.fullmatch(block_id):
            invalid.append(block_id)
            continue
        if block_id in seen:
            continue
        seen.add(block_id)
        kept.append(block_id)

    if invalid:
        shown = "、".join(_short(item) for item in invalid[:3])
        notes.append(
            f"有 {len(invalid)} 个出处编号格式不对，已剔除：{shown}"
        )

    if len(kept) > _MAX_SOURCES:
        cut = len(kept) - _MAX_SOURCES
        kept = kept[:_MAX_SOURCES]
        notes.append(
            f"出处太多，只保留前 {_MAX_SOURCES} 个（截断 {cut} 个）"
        )

    if not raw and len(answer) > _LONG_ANSWER:
        notes.append("这条回答没有给出处，建议核对是否漏标原文段落")

    mentioned = list(dict.fromkeys(_BARE_ID_RE.findall(answer)))
    unregistered = [block_id for block_id in mentioned if block_id not in seen]
    if unregistered:
        shown = "、".join(_short(item) for item in unregistered[:3])
        notes.append(f"正文里提到了块号但没登记为出处：{shown}")

    # 原始为 0 时没有"率"可算，不追加 note（None 不写成 100%）
    if raw:
        pct = round(len(kept) / len(raw) * 100)
        notes.append(
            f"出处可定位率 {pct}%（{len(kept)}/{len(raw)}）"
        )

    updated = output.model_copy(update={"source_block_ids": kept})
    return updated, notes
