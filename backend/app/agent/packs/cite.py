"""引文工具包：看草稿里已经插了哪些引文、以及**建议**往哪儿插（不代插）。

为什么「只建议不代插」：插引文会改稿子、还会影响 `[n]` 编号；
这一步必须用户点确认（和改写建议同一套原则）。
"""

from __future__ import annotations

import json

from sqlalchemy import select

from ...db import SessionLocal
from ...models import Citation, Draft, Material
from ..contracts import Pack, ToolResult, ToolSpec


def list_citations(ctx, args: dict | None = None) -> ToolResult:
    """列出某篇草稿已有的引文（顺序、来源、页码、可回跳的块号）。"""
    payload = args or {}
    draft_id = payload.get("draft_id") or (ctx.scope or {}).get("draft_id")
    if not draft_id:
        return ToolResult(data="没有指定草稿", note="需要 draft_id")

    db = SessionLocal()
    try:
        draft = db.get(Draft, int(draft_id))
        if draft is None or draft.user_id != ctx.user_id:
            return ToolResult(data="找不到这篇草稿", note="可能已删除")
        rows = db.execute(
            select(Citation, Material)
            .outerjoin(Material, Material.id == Citation.material_id)
            .where(Citation.draft_id == draft.id)
            .order_by(Citation.order)
        ).all()
    finally:
        db.close()

    items = []
    for citation, material in rows:
        title = ""
        if citation.csl_json:
            try:
                title = str(json.loads(citation.csl_json).get("title") or "")
            except (TypeError, ValueError):
                title = ""
        items.append(
            {
                "order": citation.order,
                "title": title,
                "source": material.source_name if material else "",
                "page": material.page if material else None,
                "block_id": material.block_id if material else None,
                "source_deleted": material is not None and material.task_id is None,
            }
        )
    if not items:
        return ToolResult(data=[], note="这篇草稿还没有插引文")
    return ToolResult(data=items, note=f"{len(items)} 条")


def suggest_citation(ctx, args: dict | None = None) -> ToolResult:
    """给一句话找可插的引文：查库 → 返回**可引用的块**（不写进稿子）。"""
    payload = args or {}
    query = str(payload.get("query") or "").strip()
    limit = max(1, min(int(payload.get("limit") or 3), 10))
    if not query:
        return ToolResult(data="没有关键词", note="需要 query")

    # 复用检索服务（不重复造轮子）
    from ...db import SessionLocal as SL
    from ...services.search import search_blocks

    db = SL()
    try:
        hits = search_blocks(db, ctx.user_id, query, limit=limit)
    finally:
        db.close()

    items = []
    for hit in hits:
        items.append(
            {
                "task_id": hit.get("task_id"),
                "file": hit.get("filename"),
                "block_id": hit.get("block_id"),
                "snippet": str(hit.get("snippet") or "")[:200],
            }
        )
    if not items:
        return ToolResult(data=[], note="库里没有可引用的段落")
    return ToolResult(
        data=items,
        note=f"{len(items)} 处可引用（要插进稿子请让用户在素材卡上点「插入引文」）",
    )


PACK = Pack(
    name="cite",
    tools=(
        ToolSpec(
            name="list_citations",
            description="列草稿已有引文（顺序/来源/页码/块号），用于查编号与出处一致性。",
            parameters={
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "integer",
                        "description": "草稿 id（默认当前草稿）",
                    },
                },
            },
            handler=list_citations,
            max_result_chars=4000,
        ),
        ToolSpec(
            name="suggest_citation",
            description=(
                "给一句话找可引用的原文位置（返回块号与出处）。"
                "只给建议，不代插——插引文要用户在界面上确认。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要找依据的句子或关键词",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
            handler=suggest_citation,
            max_result_chars=3000,
        ),
    ),
)
