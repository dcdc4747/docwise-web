"""写作侧工具包：读草稿、列草稿、查素材。

⚠️ 这个文件**不许 import pydantic_ai**（结构用例钉着）：工具只是普通函数，
框架细节全在 `runtime.py`——换引擎时这里一行不用改。
"""

from __future__ import annotations

from sqlalchemy import select

from ...db import SessionLocal
from ...models import Draft, Material
from ..contracts import Pack, ToolResult, ToolSpec


def list_drafts(ctx, args: dict | None = None) -> ToolResult:
    """列出我的草稿（id + 标题 + 字数），用来确定"在给哪一篇提建议"。"""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Draft.id, Draft.title, Draft.body_md)
            .where(Draft.user_id == ctx.user_id)
            .order_by(Draft.updated_at.desc())
            .limit(20)
        ).all()
    finally:
        db.close()
    if not rows:
        return ToolResult(data="（还没有草稿）", note="空")
    items = [
        {"draft_id": rid, "title": title, "chars": len(body or "")}
        for rid, title, body in rows
    ]
    return ToolResult(data=items, note=f"{len(items)} 篇")


def read_draft(ctx, args: dict | None = None) -> ToolResult:
    """读一篇草稿的正文（默认读 scope 里正在编辑的那篇）。"""
    payload = args or {}
    raw_id = payload.get("draft_id")
    target = raw_id or (ctx.scope or {}).get("draft_id")
    if not target:
        return ToolResult(data="没有指定草稿", note="需要 draft_id")
    db = SessionLocal()
    try:
        draft = db.get(Draft, int(target))
        if draft is None or draft.user_id != ctx.user_id:
            return ToolResult(data="找不到这篇草稿", note="可能已删除")
        body = draft.body_md or ""
        return ToolResult(
            data={
                "draft_id": draft.id,
                "title": draft.title,
                "template_id": draft.template_id,
                "chars": len(body),
                # ⚠️ 空稿要明说：否则模型会误以为自己没读到，回一句"我看不到你的稿件"
                "empty": len(body.strip()) == 0,
                # 太长就截断，别把整篇塞进上下文（会烧光预算）
                "body": body[:6000],
                "truncated": len(body) > 6000,
            },
            note=f"{len(body)} 字",
        )
    finally:
        db.close()


def search_materials(ctx, args: dict | None = None) -> ToolResult:
    """在我的素材卡里找（快照文本，删了源文献也还在）。"""
    payload = args or {}
    query = str(payload.get("query") or "")
    limit = max(1, min(int(payload.get("limit") or 5), 10))
    db = SessionLocal()
    try:
        stmt = (
            select(
                Material.id,
                Material.text_quote,
                Material.source_name,
                Material.page,
            )
            .where(Material.user_id == ctx.user_id)
            .order_by(Material.created_at.desc())
            .limit(50)
        )
        rows = db.execute(stmt).all()
    finally:
        db.close()
    keyword = (query or "").strip()
    hits = [
        {
            "material_id": mid,
            "quote": (quote or "")[:300],
            "source": source or "",
            "page": page,
        }
        for mid, quote, source, page in rows
        if not keyword or keyword in (quote or "")
    ][:limit]
    if not hits:
        return ToolResult(data=[], note="没找到相关素材")
    return ToolResult(data=hits, note=f"{len(hits)} 条")


PACK = Pack(
    name="writing",
    tools=(
        ToolSpec(
            name="list_drafts",
            description="列出我的草稿（id、标题、字数）。不确定在写哪一篇时先看这个。",
            parameters={"type": "object", "properties": {}},
            handler=list_drafts,
            max_result_chars=2000,
        ),
        ToolSpec(
            name="read_draft",
            description="读草稿正文与模板标识；不传 draft_id 就读正在编辑的那篇。",
            parameters={
                "type": "object",
                "properties": {
                    "draft_id": {"type": "integer", "description": "草稿 id，可省略"},
                },
            },
            handler=read_draft,
            max_result_chars=6000,
        ),
        ToolSpec(
            name="search_materials",
            description="在我的素材卡里按关键词找句子（快照，带原出处）。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "关键词"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
            },
            handler=search_materials,
            max_result_chars=3000,
        ),
    ),
)
