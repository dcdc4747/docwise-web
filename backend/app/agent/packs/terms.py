"""术语工具包：查术语表（导读/术语表是已有能力，只是以前只有界面能看）。

用途：写作时统一译名、读文献时问"这个词这篇怎么译的"。
⚠️ 不许 import pydantic_ai（结构用例钉着）。
"""

from __future__ import annotations

import json

from sqlalchemy import select

from ...db import SessionLocal
from ...models import Task, TaskUnderstanding
from ..contracts import Pack, ToolResult, ToolSpec


def _terms_of(raw: str | None) -> list[dict]:
    """`terms_json` 是引擎/LLM 写进去的 JSON；读坏了就当没有，不抛异常。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(data, dict):
        data = data.get("terms") or []
    return [item for item in data if isinstance(item, dict)]


def search_terms(ctx, args: dict | None = None) -> ToolResult:
    """在术语表里按关键词找（默认查我所有文献的术语）。"""
    payload = args or {}
    query = str(payload.get("query") or "").strip()
    task_id = payload.get("task_id")
    limit = max(1, min(int(payload.get("limit") or 20), 50))

    db = SessionLocal()
    try:
        stmt = (
            select(TaskUnderstanding, Task.filename)
            .join(Task, Task.id == TaskUnderstanding.task_id)
            .where(Task.user_id == ctx.user_id)
            .limit(50)
        )
        if task_id:
            stmt = stmt.where(TaskUnderstanding.task_id == int(task_id))
        rows = db.execute(stmt).all()
    finally:
        db.close()

    hits: list[dict] = []
    for understanding, filename in rows:
        for term in _terms_of(understanding.terms_json):
            source = str(
                term.get("source") or term.get("term") or term.get("en") or ""
            )
            target = str(term.get("target") or term.get("zh") or "")
            if query and query.lower() not in (source + target).lower():
                continue
            hits.append(
                {
                    "task_id": understanding.task_id,
                    "file": filename,
                    "term": source,
                    "translation": target,
                    "note": str(term.get("note") or ""),
                }
            )
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break

    if not hits:
        return ToolResult(
            data=[],
            note=(
                "没有术语表（文献还没生成导读，或这篇没有术语）"
                if not query
                else "没有匹配的术语"
            ),
        )
    return ToolResult(data=hits, note=f"{len(hits)} 条")


PACK = Pack(
    name="terms",
    tools=(
        ToolSpec(
            name="search_terms",
            description=(
                "查术语表：给我的文献里出现过的术语与它的中文译法。"
                "写作时统一译名、读文献时问「这个词这篇怎么译的」都用它。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "关键词（中英都行）"},
                    "task_id": {
                        "type": "integer",
                        "description": "只看某一篇（可省略）",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
            },
            handler=search_terms,
            max_result_chars=3000,
        ),
    ),
)
