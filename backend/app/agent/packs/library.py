"""库 · 工具包（v1 只读）。

规则：
- **只查当前用户**（非本人当"没有"）；
- 结果**结构化 + 截断要说清楚**（`note` 里写"还有 N 条没显示"）；
- 失败抛异常由 runtime 转成 `ModelRetry`（让模型换招，而不是炸掉整轮）。

⚠️ 这个文件**不许 import pydantic_ai**（测试会断言）。
"""

from __future__ import annotations

from ...services import search as search_service
from ..contracts import Pack, ToolContext, ToolResult, ToolSpec

_MAX_ROWS = 10


def _search_library(ctx: ToolContext, args: dict) -> ToolResult:
    query = str(args.get("query") or "").strip()
    if not query:
        return ToolResult(data=[], note="检索词是空的，什么都没查")
    limit = int(args.get("limit") or 6)
    task_id = args.get("task_id")
    hits = search_service.search_blocks(
        ctx.db, ctx.user_id, query, limit=limit, task_id=task_id
    )
    if not hits:
        return ToolResult(data=[], note=f"库里没有匹配「{query}」的段落")
    note = ""
    if len(hits) >= limit:
        note = f"只显示前 {limit} 条，可能还有更多"
    return ToolResult(data=hits, note=note)


def _read_blocks(ctx: ToolContext, args: dict) -> ToolResult:
    task_id = args.get("task_id")
    if not isinstance(task_id, int):
        return ToolResult(data=[], note="需要 task_id（先用 search_library 拿到）")
    block_ids = args.get("block_ids") or None
    if block_ids is not None and not isinstance(block_ids, list):
        return ToolResult(data=[], note="block_ids 必须是数组")
    rows = search_service.blocks_of(ctx.db, ctx.user_id, task_id, block_ids)
    if not rows:
        return ToolResult(data=[], note="这篇里没有这些段落（或不是你的文献）")
    budget = 4000
    out = []
    for row in rows:
        text = row["text"]
        if budget - len(text) <= 0:
            break
        out.append({"block_id": row["block_id"], "text": text[:budget]})
        budget -= len(text)
    note = ""
    if len(out) != len(rows):
        note = f"只返回了 {len(out)}/{len(rows)} 段（长度限制）"
    return ToolResult(data=out, note=note)


PACK = Pack(
    name="library",
    tools=(
        ToolSpec(
            name="search_library",
            description=(
                "在用户自己的知识库里按关键词检索段落（跨所有文献）。"
                "返回 task_id / filename / block_id / 片段。回答里引用时用 block_id。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索词，中英文都行"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_ROWS},
                    "task_id": {
                        "type": "integer",
                        "description": "可选：只在这一篇里查",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=_search_library,
        ),
        ToolSpec(
            name="read_blocks",
            description=(
                "读某篇文献的指定段落原文（先用 search_library 拿到 block_id）。"
                "不给 block_ids 就读整篇前若干段。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "block_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要读的块编号，最多 8 个",
                    },
                },
                "required": ["task_id"],
                "additionalProperties": False,
            },
            handler=_read_blocks,
        ),
    ),
)
