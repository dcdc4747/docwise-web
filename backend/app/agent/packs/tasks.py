"""文献管理工具包：列文献、看导读、看某一篇的状态。

为什么需要：用户说「我库里那篇讲手性的」时，agent 得能自己把"哪一篇"找出来，
而不是让用户报文件名。
"""

from __future__ import annotations

import json

from sqlalchemy import select

from ...db import SessionLocal
from ...models import Task, TaskUnderstanding
from ..contracts import Pack, ToolResult, ToolSpec


def list_tasks(ctx, args: dict | None = None) -> ToolResult:
    """列出我的文献（id / 文件名 / 状态 / 语言对 / 档位）。"""
    payload = args or {}
    query = str(payload.get("query") or "").strip().lower()
    limit = max(1, min(int(payload.get("limit") or 10), 30))

    db = SessionLocal()
    try:
        stmt = (
            select(Task)
            .where(Task.user_id == ctx.user_id)
            .order_by(Task.created_at.desc())
            .limit(60)
        )
        tasks = db.scalars(stmt).all()
    finally:
        db.close()

    items = []
    for task in tasks:
        if query and query not in (task.filename or "").lower():
            continue
        items.append(
            {
                "task_id": task.id,
                "filename": task.filename,
                "status": task.status,
                "source_lang": task.source_lang,
                "target_lang": task.target_lang,
                "tier": task.tier,
            }
        )
        if len(items) >= limit:
            break

    if not items:
        return ToolResult(data=[], note="没有匹配的文献")
    return ToolResult(data=items, note=f"{len(items)} 篇")


def get_understanding(ctx, args: dict | None = None) -> ToolResult:
    """读某一篇的导读（研究问题 / 方法 / 结论…）与术语条数。"""
    payload = args or {}
    task_id = payload.get("task_id")
    if not task_id:
        return ToolResult(data="没有指定 task_id", note="需要 task_id")

    db = SessionLocal()
    try:
        task = db.get(Task, int(task_id))
        if task is None or task.user_id != ctx.user_id:
            return ToolResult(data="找不到这篇文献", note="可能已删除")
        understanding = db.scalars(
            select(TaskUnderstanding).where(TaskUnderstanding.task_id == task.id)
        ).first()
        guide_raw = understanding.guide_json if understanding else None
        terms_raw = understanding.terms_json if understanding else None
        status = understanding.status if understanding else "pending"
    finally:
        db.close()

    guide = None
    if guide_raw:
        try:
            guide = json.loads(guide_raw)
        except (TypeError, ValueError):
            guide = None
    terms_count = 0
    if terms_raw:
        try:
            parsed = json.loads(terms_raw)
            terms_count = len(parsed.get("terms", parsed)) if parsed else 0
        except (TypeError, ValueError):
            terms_count = 0

    if not guide:
        return ToolResult(
            data={
                "task_id": task_id,
                "status": status,
                "guide": None,
                "terms_count": terms_count,
            },
            note="导读还没生成（界面点一下「导读」会按需生成）",
        )
    return ToolResult(
        data={
            "task_id": task_id,
            "status": status,
            "guide": guide,
            "terms_count": terms_count,
        },
        note=f"术语 {terms_count} 条",
    )


PACK = Pack(
    name="tasks",
    tools=(
        ToolSpec(
            name="list_tasks",
            description="列出我的文献（id、文件名、状态）。用户说「那篇讲手性的」时先用它定位。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "按文件名筛（可省略）"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 30},
                },
            },
            handler=list_tasks,
            max_result_chars=3000,
        ),
        ToolSpec(
            name="get_understanding",
            description="读某一篇文献的导读（研究问题/方法/结论）与术语条数。",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "文献 id"},
                },
                "required": ["task_id"],
            },
            handler=get_understanding,
            max_result_chars=4000,
        ),
    ),
)
