"""把「读段预算」接进两个重读高发工具（`read_blocks` / `read_section`）。

## 为什么需要一个薄封装

`ReadBudget` 是纯对象，但每次工具调用都会新建一个 `ToolContext`
（`scope` 还是拷贝），拿不到同一次对话的内存。所以这里按
拿不到"同一轮对话"的内存。所以这里按 `(用户, 场景, 文献/草稿)` 缓存一个预算对象，
窗口 10 分钟——同一次对话里连续读段共享预算，隔一段时间再问重新开始。

⚠️ 这是**进程内**状态，不进库、不跨进程。它只影响"这一轮还能不能再读"，
不影响任何数据正确性（读不到就如实说"这段读过了"）。
"""

from __future__ import annotations

import time

from ..read_budget import ReadBudget

#: 同一次对话窗口（秒）：超时视为新一轮，预算重置
WINDOW_SECONDS = 600

_CACHE: dict[tuple, tuple[float, ReadBudget]] = {}


def _key_of(ctx, kind: str) -> tuple:
    scope = ctx.scope or {}
    return (
        int(getattr(ctx, "user_id", 0) or 0),
        str(kind),
        str(scope.get("task_id") or ""),
        str(scope.get("draft_id") or ""),
    )


def budget_for(ctx, kind: str) -> ReadBudget:
    """取这次对话的预算对象（没有就新建；超窗就重置）。"""
    key = _key_of(ctx, kind)
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit is not None and now - hit[0] < WINDOW_SECONDS:
        return hit[1]
    fresh = ReadBudget()
    _CACHE[key] = (now, fresh)
    return fresh


def reset_all() -> None:
    """测试用：清掉所有预算（避免用例之间互相影响）。"""
    _CACHE.clear()
