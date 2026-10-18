"""章节纲要工具包（outline）：先看结构，再只读一节。

长文精读时，把整篇塞进上下文很贵。这里两步走：

1. `list_sections` 只回**题名与章节标题**（按块顺序，通常几十条），先看结构；
2. `read_section` 只读**某一节**——从该标题起到下一个标题前的全部块（带译文）。

合起来比整篇塞进上下文省得多。两个工具**全确定性、不调模型**：块类型只由
`blocktypes.classify` 判，这里不另立判据，也不猜"没认出来的标题"。

口径：

- 只查**当前用户**的文献（非本人当"找不到"）；
- 块顺序＝写库顺序（`task_blocks.id` 升序，引擎按阅读顺序写）；
- 一节超过 6000 字就截断并标 `truncated: true`，**不假装读完了**。

⚠️ 这个文件**不许 import pydantic_ai**（结构用例钉着）。
"""

from __future__ import annotations

from sqlalchemy import select

from ...blocktypes import classify
from ...db import SessionLocal
from ...models import Task, TaskBlock
from ..contracts import Pack, ToolContext, ToolResult, ToolSpec

# 可以作为"一节开头"的类型：章节标题与文献题名（题名后面通常是摘要）
_SECTION_KINDS = ("heading", "title")
_READ_MAX_CHARS = 6000
_EMPTY_NOTE = "这篇没有识别到章节标题（可能是扫描件或结构不在块流里）"
_MISSING_TASK = "找不到这篇文献（可能已删除，或不是你的）"


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


def _owned_task(db, user_id: int, task_id: int | None) -> Task | None:
    """按 `ctx.user_id` 取归属；不存在或不是本人的一律返回 None。"""
    if task_id is None:
        return None
    task = db.get(Task, task_id)
    if task is None or task.user_id != user_id:
        return None
    return task


def _load_blocks(db, task_id: int) -> list[TaskBlock]:
    """按写库顺序取全部块（引擎按阅读顺序写，id 升序就是块顺序）。"""
    stmt = (
        select(TaskBlock)
        .where(TaskBlock.task_id == task_id)
        .order_by(TaskBlock.id)
    )
    return list(db.scalars(stmt).all())


def _scan(blocks: list[TaskBlock]) -> list[tuple[int, dict]]:
    """扫描块流，返回 `[(块位置, 章节条目)]`。

    条目形状就是 `list_sections` 的一项：`{index, kind, text, block_id}`；
    `text` 优先用译文（`translated or text`），`index` 是它在结果里的序号。
    类型用原文判（译文可能改变文字形状，判据只对原文成立）。
    """
    rows: list[tuple[int, dict]] = []
    for pos, block in enumerate(blocks):
        kind = classify(block.text or "", block.block_id, block.layout)
        if kind not in _SECTION_KINDS:
            continue
        rows.append(
            (
                pos,
                {
                    "index": len(rows),
                    "kind": kind,
                    "text": (block.translated or block.text or "").strip(),
                    "block_id": block.block_id,
                },
            )
        )
    return rows


def _read_range(
    blocks: list[TaskBlock], start: int, end: int
) -> tuple[list[dict], int, bool]:
    """读 `[start, end)` 的块，逐块 `{block_id, text}`；超预算就截断。"""
    out: list[dict] = []
    used = 0
    truncated = False
    for block in blocks[start:end]:
        text = block.translated or block.text or ""
        if not text:
            continue
        room = _READ_MAX_CHARS - used
        if room <= 0:
            truncated = True
            break
        if len(text) > room:
            out.append({"block_id": block.block_id, "text": text[:room]})
            used += room
            truncated = True
            break
        out.append({"block_id": block.block_id, "text": text})
        used += len(text)
    return out, used, truncated


def list_sections(ctx: ToolContext, args: dict | None = None) -> ToolResult:
    """列出该文献的题名与章节标题，按块顺序返回 `{index, kind, text, block_id}`。"""
    payload = _payload(args)
    task_id = _as_int(payload.get("task_id"))
    if task_id is None:
        return ToolResult(data=[], note="需要 task_id（先用 list_tasks 找到文献）")

    with SessionLocal() as db:
        task = _owned_task(db, ctx.user_id, task_id)
        if task is None:
            return ToolResult(data=[], note=_MISSING_TASK)
        blocks = _load_blocks(db, task.id)

    rows = _scan(blocks)
    sections = [item for _, item in rows]
    if not sections:
        if not blocks:
            return ToolResult(data=[], note="这篇还没有可读的块（可能还在处理中）")
        return ToolResult(data=[], note=_EMPTY_NOTE)
    return ToolResult(
        data=sections,
        note=f"{len(sections)} 节；读其中一节用 read_section(task_id, index)",
    )


def read_section(ctx: ToolContext, args: dict | None = None) -> ToolResult:
    """读第 `index` 节：从该标题起到下一个标题前的全部块（逐块 `{block_id, text}`）。"""
    payload = _payload(args)
    task_id = _as_int(payload.get("task_id"))
    index = _as_int(payload.get("index"))
    if task_id is None:
        return ToolResult(data={"error": "没有指定 task_id"}, note="需要 task_id")
    if index is None:
        return ToolResult(
            data={"error": "没有指定 index"},
            note="需要 index（先用 list_sections 看结构）",
        )

    with SessionLocal() as db:
        task = _owned_task(db, ctx.user_id, task_id)
        if task is None:
            return ToolResult(data={"error": _MISSING_TASK}, note=_MISSING_TASK)
        blocks = _load_blocks(db, task.id)

    rows = _scan(blocks)
    if not rows:
        if not blocks:
            note = "这篇还没有可读的块（可能还在处理中）"
        else:
            note = _EMPTY_NOTE
        return ToolResult(data={"error": note}, note=note)

    if index < 0 or index >= len(rows):
        error = (
            f"index 越界：这篇只有 {len(rows)} 个章节"
            f"（index 0–{len(rows) - 1}），你给的是 {index}"
        )
        return ToolResult(
            data={"error": error},
            note="先用 list_sections 看有哪些章节，再按它返回的 index 读",
        )

    start, section = rows[index]
    end = rows[index + 1][0] if index + 1 < len(rows) else len(blocks)
    out, used, truncated = _read_range(blocks, start, end)

    data = {
        "task_id": task.id,
        "index": index,
        "kind": section["kind"],
        "title": section["text"],
        "blocks": out,
        "truncated": truncated,
    }
    note = f"第 {index} 节：{len(out)} 块 / {used} 字"
    if truncated:
        note += f"；超过 {_READ_MAX_CHARS} 字，只给了前 {used} 字"
    return ToolResult(data=data, note=note)


PACK = Pack(
    name="outline",
    tools=(
        ToolSpec(
            name="list_sections",
            description=(
                "列出某篇文献的题名与章节标题（按块顺序，"
                "返回 index / kind / text / block_id）。"
                "长文精读先看结构，再用 read_section 只读一节。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "文献 id"},
                },
                "required": ["task_id"],
                "additionalProperties": False,
            },
            handler=list_sections,
            max_result_chars=3000,
        ),
        ToolSpec(
            name="read_section",
            description=(
                "读某一节的全文（标题到下一个标题之前），"
                "逐块返回 block_id 与译文/原文。"
                "index 用 list_sections 返回的序号；"
                "超过 6000 字会截断并标 truncated。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "文献 id"},
                    "index": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "list_sections 返回的序号（0 起）",
                    },
                },
                "required": ["task_id", "index"],
                "additionalProperties": False,
            },
            handler=read_section,
            max_result_chars=8000,
        ),
    ),
)
