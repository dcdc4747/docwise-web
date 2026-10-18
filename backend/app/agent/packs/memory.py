"""记忆工具包（v1 只读）：读界面偏好、查跨文献记忆。

规则：
- **只查当前用户**（非本人当"没有"）；
- **只读**：不改 `hits`、不写偏好（`app/memory.py::resolve_active` 会累加命中数，
  所以这里不调它，直接查 `memory_items`）；
- 没有就如实说没有，`note` 里写清原因，**不编**。

⚠️ 这个文件**不许 import pydantic_ai**（结构用例钉着）。
"""

from __future__ import annotations

import json

from sqlalchemy import or_, select

from ...db import SessionLocal
from ...models import MemoryItem, UserPrefs
from ...timeutil import iso_utc
from ..contracts import Pack, ToolContext, ToolResult, ToolSpec

_DEFAULT_LIMIT = 10
_MAX_LIMIT = 50


def _prefs_of(payload: str | None) -> dict:
    """`user_prefs.payload` 是 JSON 文本；读坏了当没有（与 me.py 同一口径）。"""
    if not payload:
        return {}
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _limit_of(raw: object) -> int:
    """`limit` 容错：不是数就用默认值，超界就夹到区间里。"""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_LIMIT
    return max(1, min(value, _MAX_LIMIT))


def _like(query: str) -> str:
    """转成 LIKE 模式并转义 `%` / `_`（否则用户输入会被当成通配符）。"""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _view(row: MemoryItem) -> dict:
    """一条记忆对外的样子：`kind` / `text` / `created_at` + 定位用的原字段。"""
    if row.kind == "cite":
        text = row.target
    else:
        text = f"{row.source} → {row.target}"
    return {
        "kind": row.kind,
        "text": text,
        "source": row.source,
        "target": row.target,
        "enabled": bool(row.enabled),
        "created_at": iso_utc(row.created_at),
    }


def get_preferences(ctx: ToolContext, args: dict | None = None) -> ToolResult:
    """读当前用户保存的偏好（原样返回库里那份键值，不补默认值）。"""
    with SessionLocal() as session:
        row = session.scalar(select(UserPrefs).where(UserPrefs.user_id == ctx.user_id))
        prefs = _prefs_of(row.payload if row is not None else None)
    if not prefs:
        return ToolResult(data={}, note="还没有设置偏好")
    return ToolResult(data=prefs, note=f"{len(prefs)} 项偏好")


def search_memories(ctx: ToolContext, args: dict | None = None) -> ToolResult:
    """在用户自己的记忆里按关键词找术语/译名偏好与引用习惯。"""
    payload = args if isinstance(args, dict) else {}
    raw_query = payload.get("query")
    query = raw_query.strip() if isinstance(raw_query, str) else ""
    limit = _limit_of(payload.get("limit"))

    with SessionLocal() as session:
        stmt = select(MemoryItem).where(MemoryItem.user_id == ctx.user_id)
        if query:
            pattern = _like(query)
            stmt = stmt.where(
                or_(
                    MemoryItem.source.ilike(pattern, escape="\\"),
                    MemoryItem.target.ilike(pattern, escape="\\"),
                )
            )
        rows = session.scalars(
            stmt.order_by(MemoryItem.updated_at.desc(), MemoryItem.id.desc()).limit(
                limit
            )
        ).all()
        items = [_view(row) for row in rows]

    if not items:
        note = "还没有记忆" if not query else f"没有匹配「{query}」的记忆"
        return ToolResult(data=[], note=note)
    note = f"{len(items)} 条记忆"
    if len(items) >= limit:
        note = f"只显示前 {limit} 条，可能还有更多"
    disabled = sum(1 for item in items if not item["enabled"])
    if disabled:
        note += f"（其中 {disabled} 条已停用）"
    return ToolResult(data=items, note=note)


PACK = Pack(
    name="memory",
    tools=(
        ToolSpec(
            name="get_preferences",
            description=(
                "读当前用户保存的界面/阅读偏好（如 defaultView / tier / "
                "readingSize / reducedMotion 等键值）。没有设置时返回空对象。"
            ),
            parameters={"type": "object", "properties": {}},
            handler=get_preferences,
            max_result_chars=2000,
        ),
        ToolSpec(
            name="search_memories",
            description=(
                "在当前用户自己的跨文献记忆里按关键词检索术语/译名偏好"
                "与引用习惯。返回 kind / text / created_at；没有匹配就如实"
                "返回空列表。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "关键词，中英文都行；不传则列出最近记忆",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_LIMIT,
                        "description": "最多返回几条（默认 10）",
                    },
                },
                "additionalProperties": False,
            },
            handler=search_memories,
            max_result_chars=4000,
        ),
    ),
)
