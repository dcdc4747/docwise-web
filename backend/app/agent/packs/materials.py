"""素材工具包：列素材卡、读一张素材、把某一段存成素材（**要用户确认**）。

「素材」是写作用的证据卡：`Material` 存的是**创建时的快照**
（`text_quote` / `translated_quote` / `page` / `source_name`）。源文献删了卡还在、
出处还看得见（`task_id` 变 null，界面据此说"源文献已删除，仅存快照"）。

三条口径（与 `routers/materials.py` 同一套，别各写一套）：

- 只读写**当前用户**的素材与文献（非本人当"没有"）；
- 列表不返回软删（`deleted_at` 非空）的卡；
- `page` 只从块编号推（`p{页序从 0 起}_b{块序号}` → 人读 +1），推不出**不编**。

⚠️ 写工具 `create_material` **必须 `confirm is True` 才落库**：建卡是用户的动作，
模型不能替用户点头。第一次调用只回"要确认"，用户点头后由模型带 `confirm=true`
再调一次。
⚠️ 这个文件**不许 import pydantic_ai**（结构用例钉着）。
"""

from __future__ import annotations

import re

from sqlalchemy import or_, select

from ...db import SessionLocal
from ...models import Material, Task, TaskBlock
from ...timeutil import iso_utc
from ..contracts import Pack, ToolResult, ToolSpec

# 块编号约定：`p{页序从 0 起}_b{块序号}`（与 routers/materials.py 同一口径）。
_BLOCK_RE = re.compile(r"^p(\d+)_b\d+$")
_LIST_DEFAULT = 10
_LIST_MAX = 30
_QUOTE_CHARS = 200


def _payload(args: dict | None) -> dict:
    """`args` 容错：None / 非 dict（模型传了奇怪形状）都当空参数。"""
    return args if isinstance(args, dict) else {}


def _as_int(value) -> int | None:
    """宽松转 int；转不了返回 None（不抛异常，交给调用方说人话）。"""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _page_of(block_id: str) -> int | None:
    """从块编号推人读页码；不合约定返回 None（**不编页码**）。"""
    match = _BLOCK_RE.match(block_id or "")
    return int(match.group(1)) + 1 if match else None


def _like_pattern(query: str) -> str:
    """把关键词包成 LIKE 模式，转义 `%` / `_` / 反斜杠（关键词按字面匹配）。"""
    escaped = (
        query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped}%"


def _is_confirmed(value) -> bool:
    """只认布尔 `true`：字符串 "true"、数字 1 都不算，防止模型自己点头。"""
    return value is True


def list_materials(ctx, args: dict | None = None) -> ToolResult:
    """列出我的素材卡（片段、来源、页码）；源文献已删的标 `source_deleted`。"""
    payload = _payload(args)
    query = str(payload.get("query") or "").strip()
    limit = _as_int(payload.get("limit")) or _LIST_DEFAULT
    limit = max(1, min(limit, _LIST_MAX))

    stmt = select(Material).where(
        Material.user_id == ctx.user_id, Material.deleted_at.is_(None)
    )
    if query:
        like = _like_pattern(query)
        stmt = stmt.where(
            or_(
                Material.text_quote.ilike(like, escape="\\"),
                Material.translated_quote.ilike(like, escape="\\"),
                Material.source_name.ilike(like, escape="\\"),
            )
        )
    stmt = stmt.order_by(Material.id.desc()).limit(limit)
    with SessionLocal() as db:
        rows = db.scalars(stmt).all()

    items = [
        {
            "material_id": row.id,
            "quote": (row.text_quote or "")[:_QUOTE_CHARS],
            "source": row.source_name or "",
            "page": row.page,
            # 快照字段还在，但"回跳原文"的链接断了：界面据此说"仅存快照"。
            "source_deleted": row.task_id is None,
        }
        for row in rows
    ]
    if not items:
        if query:
            return ToolResult(data=[], note=f"没有匹配「{query}」的素材")
        return ToolResult(data=[], note="还没有素材卡")

    notes = [f"{len(items)} 条"]
    deleted = sum(1 for item in items if item["source_deleted"])
    if deleted:
        notes.append(f"其中 {deleted} 条的源文献已删除，只剩快照")
    if len(items) >= limit:
        notes.append(f"只显示前 {limit} 条，可能还有更多")
    return ToolResult(data=items, note="；".join(notes))


def get_material(ctx, args: dict | None = None) -> ToolResult:
    """读一条素材的完整快照（含 `translated_quote`）。"""
    payload = _payload(args)
    material_id = _as_int(payload.get("material_id"))
    if material_id is None:
        return ToolResult(data="没有指定素材 id", note="需要 material_id")

    with SessionLocal() as db:
        row = db.scalar(
            select(Material).where(
                Material.id == material_id,
                Material.user_id == ctx.user_id,
            )
        )
        if row is None or row.deleted_at is not None:
            return ToolResult(data="找不到这条素材", note="可能已删除，或不是你存的")
        data = {
            "material_id": row.id,
            "text_quote": row.text_quote,
            "translated_quote": row.translated_quote,
            "page": row.page,
            "source_name": row.source_name,
            "note": row.note,
            "task_id": row.task_id,
            "block_id": row.block_id,
            "source_deleted": row.task_id is None,
            "created_at": iso_utc(row.created_at),
        }
    if data["source_deleted"]:
        return ToolResult(data=data, note="源文献已删除，只剩快照")
    return ToolResult(data=data, note=f"第 {data['page']} 页")


def create_material(ctx, args: dict | None = None) -> ToolResult:
    """把一段存成素材卡；`confirm is True` 才写，否则只说明"要用户确认"。"""
    payload = _payload(args)
    task_id = _as_int(payload.get("task_id"))
    block_id = str(payload.get("block_id") or "").strip()
    if task_id is None or not block_id:
        return ToolResult(data="参数不全", note="需要 task_id 与 block_id")

    if not _is_confirmed(payload.get("confirm")):
        return ToolResult(
            data={
                "status": "needs_confirmation",
                "task_id": task_id,
                "block_id": block_id,
                "message": "建素材卡会写入一条快照，需要用户确认。",
            },
            note="要用户确认：这次没有建卡；用户点头后带 confirm=true 再调用。",
        )

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is None or task.user_id != ctx.user_id:
            return ToolResult(data="找不到这篇文献", note="可能已删除，或不是你的")
        block = db.scalar(
            select(TaskBlock).where(
                TaskBlock.task_id == task.id,
                TaskBlock.block_id == block_id,
            )
        )
        if block is None:
            return ToolResult(data="找不到这个块", note="块编号不对，或不属于这篇文献")
        page = _page_of(block.block_id)
        if page is None:
            # `materials.page` 是必填列；编一个页码会印到出处芯片上，比拒绝更糟。
            return ToolResult(
                data="这个块推不出页码",
                note=(
                    "块号不符合 p{页从 0 起}_b{n}，素材卡的 page 是必填、"
                    "项目规矩不编页码，所以没有建卡"
                ),
            )
        row = Material(
            user_id=ctx.user_id,
            task_id=task.id,
            block_id=block.block_id,
            # ⭐ 四个快照字段：创建时深拷贝（删了源文献卡还在）
            text_quote=block.text,
            translated_quote=block.translated,
            page=page,
            source_name=task.filename,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        data = {
            "material_id": row.id,
            "text_quote": row.text_quote,
            "translated_quote": row.translated_quote,
            "page": row.page,
            "source_name": row.source_name,
            "task_id": row.task_id,
            "block_id": row.block_id,
        }
    return ToolResult(
        data=data, note=f"已建素材卡 #{data['material_id']}（第 {page} 页）"
    )


PACK = Pack(
    name="materials",
    tools=(
        ToolSpec(
            name="list_materials",
            description=(
                "列出我的素材卡（原文片段、来源、页码）。"
                "源文献已删除的卡会标 source_deleted=true（只剩快照）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "关键词，可省略"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _LIST_MAX,
                    },
                },
                "additionalProperties": False,
            },
            handler=list_materials,
            max_result_chars=4000,
        ),
        ToolSpec(
            name="get_material",
            description=(
                "读一条素材卡的完整快照（原文、译文、来源、页码、块号）。"
                "需要先有 material_id（list_materials 里拿）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "material_id": {"type": "integer", "description": "素材 id"},
                },
                "required": ["material_id"],
                "additionalProperties": False,
            },
            handler=get_material,
            max_result_chars=8000,
        ),
        ToolSpec(
            name="create_material",
            description=(
                "把某篇文献的某一段存成素材卡（快照）。这是**写操作**："
                "先不带 confirm 调用，向用户说明并等用户点头；"
                "用户确认后再带 confirm=true 调用。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "文献 id"},
                    "block_id": {"type": "string", "description": "块编号"},
                    "confirm": {
                        "type": "boolean",
                        "description": "用户已确认才可传 true",
                    },
                },
                "required": ["task_id", "block_id"],
                "additionalProperties": False,
            },
            handler=create_material,
            max_result_chars=2000,
        ),
    ),
)
