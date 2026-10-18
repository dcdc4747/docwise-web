"""记忆工具包：读偏好/查记忆（只读），按用户确认写术语与引用偏好。

规则：
- **只碰当前用户的数据**（非本人当"没有"）；
- 只读工具（`get_preferences` / `search_memories`）：不改 `hits`、不写偏好
  （`app/memory.py::resolve_active` 会累加命中数，所以这里不调它，直接查
  `memory_items`）；
- 写工具（`save_memory` / `save_term_preference`）：必须 `confirm is True` 才落库，
  字符串 `"true"` 不算；按 `(user_id, kind, source)` 幂等更新 `target` / `enabled`，
  **绝不写 `hits`**（那是命中统计，写了就污染）；
- 没有就如实说没有，`note` 里写清原因，**不编**。

⚠️ 这个文件**不许 import pydantic_ai**（结构用例钉着）。
"""

from __future__ import annotations

import json

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...db import SessionLocal
from ...models import MemoryItem, UserPrefs
from ...timeutil import iso_utc
from ..contracts import Pack, ToolContext, ToolResult, ToolSpec

_DEFAULT_LIMIT = 10
_MAX_LIMIT = 50

# 与 `routers/memory.py` 同一口径：kind 只有两种、cite 的 source 固定、source 截断。
_TEXT_MAX = 500
_CITE_SOURCE = "default"
_KINDS = ("term", "cite")


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


def _args_of(args: object) -> dict:
    """`args` 容错：None / 非 dict 都当空参数（写工具也照此办理）。"""
    return args if isinstance(args, dict) else {}


def _as_text(value: object) -> str:
    """收成去空白字符串；None / bool 当空（别把 `True` 存成 `"True"`）。"""
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _enabled_of(value: object) -> bool:
    """`enabled` 容错：布尔照用；`"false"` / `"0"` / `"no"` / `"off"` 算停用。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in (
        "false",
        "0",
        "no",
        "off",
    ):
        return False
    return True


def _rejected(message: str) -> ToolResult:
    """参数不合法：**一行都不写**，把原因说清楚（不假装成功）。"""
    return ToolResult(
        data={"status": "rejected", "reason": message},
        note=f"没有保存：{message}",
    )


def _saved(row: MemoryItem, created: bool) -> dict:
    """写成功后的对外视图（`hits` 不在里面：它不是这次写操作的结果）。"""
    return {
        "status": "saved",
        "id": row.id,
        "kind": row.kind,
        "source": row.source,
        "target": row.target,
        "enabled": bool(row.enabled),
        "created": created,
    }


def _pending(kind: str, source: str, target: str, enabled: bool) -> ToolResult:
    """没确认：只回"要确认"，**连库都不碰**（不会多出一行）。"""
    return ToolResult(
        data={
            "status": "needs_confirmation",
            "id": None,
            "kind": kind,
            "source": source,
            "target": target,
            "enabled": enabled,
            "message": "保存记忆会写入一条偏好，需要用户确认。",
        },
        note="要用户确认：这次没有写库；用户点头后带 confirm=true 再调用。",
    )


def _find(
    session: Session, user_id: int, kind: str, source: str
) -> MemoryItem | None:
    """按幂等键 `(user_id, kind, source)` 找既有条目（与路由同一口径）。"""
    return session.scalar(
        select(MemoryItem).where(
            MemoryItem.user_id == user_id,
            MemoryItem.kind == kind,
            MemoryItem.source == source,
        )
    )


def _upsert(
    user_id: int, kind: str, source: str, target: str, enabled: bool
) -> dict:
    """按 `(user_id, kind, source)` 幂等写入，返回 `_saved()` 视图。

    ⚠️ **只改 `target` / `enabled`，从不给 `hits` 赋值**：那是
    `app/memory.py::resolve_active` 的账（"真被用过几次"），写偏好既不加一、
    也不清零。新建时同样不传 `hits`，由列默认值给 0。

    并发双写撞唯一键时回滚，再按"已存在"覆盖一次（与 `routers/memory.py`
    的 `IntegrityError` 分支同一处理）。
    """
    with SessionLocal() as session:
        existing = _find(session, user_id, kind, source)
        if existing is not None:
            existing.target = target
            existing.enabled = enabled
            session.commit()
            session.refresh(existing)
            return _saved(existing, created=False)

        row = MemoryItem(
            user_id=user_id,
            kind=kind,
            source=source,
            target=target,
            enabled=enabled,
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            again = _find(session, user_id, kind, source)
            if again is None:
                raise
            again.target = target
            again.enabled = enabled
            session.commit()
            session.refresh(again)
            return _saved(again, created=False)
        session.refresh(row)
        return _saved(row, created=True)


def _save(
    ctx: ToolContext,
    *,
    kind_raw: object,
    source_raw: object,
    target_raw: object,
    enabled_raw: object,
    confirmed: bool,
) -> ToolResult:
    """两个写工具的**共同路径**：校验 → 确认 → 同一段 upsert。

    `save_term_preference` 只是把 `kind="term"` 填好再调这里，**不复制逻辑**。
    """
    kind = _as_text(kind_raw).lower()
    source = _as_text(source_raw)
    target = _as_text(target_raw)
    enabled = _enabled_of(enabled_raw)

    if kind not in _KINDS:
        return _rejected(f"kind 只能是 {' 或 '.join(_KINDS)}")
    if not source:
        return _rejected("source 不能为空")
    if not target:
        return _rejected("target 不能为空")

    if kind == "cite":
        # 引用习惯是"一条默认格式"，source 固定成 default（与路由一致）
        source = _CITE_SOURCE
    source = source[:_TEXT_MAX]

    if not confirmed:
        return _pending(kind, source, target, enabled)

    data = _upsert(ctx.user_id, kind, source, target, enabled)
    label = "引用习惯" if kind == "cite" else "术语偏好"
    return ToolResult(data=data, note=f"已保存{label}：{source} → {target}")


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


def save_memory(ctx: ToolContext, args: dict | None = None) -> ToolResult:
    """保存一条术语/引用偏好；`confirm is True` 才落库。"""
    payload = _args_of(args)
    return _save(
        ctx,
        kind_raw=payload.get("kind"),
        source_raw=payload.get("source"),
        target_raw=payload.get("target"),
        enabled_raw=payload.get("enabled", True),
        confirmed=payload.get("confirm") is True,
    )


def save_term_preference(ctx: ToolContext, args: dict | None = None) -> ToolResult:
    """存术语译名偏好（`term` → `cn`）；与 `save_memory` 走**同一段 upsert**。"""
    payload = _args_of(args)
    return _save(
        ctx,
        kind_raw="term",
        source_raw=payload.get("term"),
        target_raw=payload.get("cn"),
        enabled_raw=True,
        confirmed=payload.get("confirm") is True,
    )


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
