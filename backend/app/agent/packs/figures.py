"""图注工具包（figures）：这篇有几张图、图 3 说了什么。

用户问「这篇有几张图」「图 3 说了什么」时用这里：

1. `list_figures` 列出该文献的全部**图注 / 表注**（`blocktypes.classify` 判出的
   `caption`），按块顺序给 `block_id`、文字与人读页码；
2. `read_figure` 读**某一条**图注，并把**前后各 1 个块**一起带上——图注常与正文
   互相引用（正文写 `Fig. 7 shows…`，图注本身只写画的是什么），只看一行往往不够。

口径（与 `outline` 同一套，别各写一套）：

- 类型只由 `blocktypes.classify` 判，**这里不另立判据**，也不猜"没认出来的图注"；
- 只查**当前用户**的文献（非本人当"找不到"）；
- 文字优先用译文（`translated or text`）；
- 页码只从块编号推（`p{页序从 0 起}_b{块序号}` → 人读 +1），推不出就是 `None`，
  **不编页码**。

⚠️ 已知缺口（如实说，不硬补）：`TABLE II.` 这类**罗马数字**表注靠文字形状认不出来
（`classify` 的图注判据只认阿拉伯数字编号），要等版面区域（`task.regions`）那条
信号才救得回来；这里只走文字形状，所以它会留在正文里、不进清单。

⚠️ 这个文件**不许 import pydantic_ai**（结构用例钉着）。
"""

from __future__ import annotations

import re

from sqlalchemy import select

from ...blocktypes import classify, classify_blocks
from ...db import SessionLocal
from ...models import Task, TaskBlock
from ..contracts import Pack, ToolContext, ToolResult, ToolSpec

_CAPTION = "caption"
# 块编号约定：`p{页序从 0 起}_b{块序号}`（与 routers/materials.py 同一口径）
_PAGE_RE = re.compile(r"^p(\d+)_b\d+$")
_EMPTY_NOTE = "这篇没有识别到图注（可能是扫描件或没有图表）"
_MISSING_TASK = "找不到这篇文献（可能已删除，或不是你的）"
_NO_BLOCKS = "这篇还没有可读的块（可能还在处理中）"


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


def _text_of(block: TaskBlock) -> str:
    """块文字：优先译文（中文用户看的就是它）。"""
    return (block.translated or block.text or "").strip()


def _page_hint(block_id: str) -> int | None:
    """块号 `pN_bM` → 人读第 N+1 页；不合约定返回 None（**不编页码**）。"""
    match = _PAGE_RE.match(block_id or "")
    return int(match.group(1)) + 1 if match else None


def _caption_row(block: TaskBlock) -> dict:
    """`list_figures` 的一项：`{block_id, kind, text, page_hint}`。"""
    return {
        "block_id": block.block_id,
        "kind": _CAPTION,
        "text": _text_of(block),
        "page_hint": _page_hint(block.block_id),
    }


def _kinds_of(blocks: list[TaskBlock], regions: object = None) -> dict[str, str]:
    """一次性判出全篇块类型（与任务详情接口同一套：`classify_blocks` + regions）。

    `regions` 传不进来（老任务/扫描件）时，判据自动退回文字形状 + 字号，
    与界面一致——**这里不另立判据**。
    """
    payload = [
        {
            "block_id": block.block_id,
            "text": block.text or "",
            "layout": block.layout,
        }
        for block in blocks
    ]
    try:
        typed = classify_blocks(payload, regions=regions)
    except Exception:  # noqa: BLE001 —— 判级失败不该把工具弄崩
        return {
            block.block_id: classify(block.text or "", block.block_id, block.layout)
            for block in blocks
        }
    return {item["block_id"]: item.get("type", "body") for item in typed}


def _scan_captions(
    blocks: list[TaskBlock], regions: object = None
) -> list[dict]:
    """扫描块流，返回图注行（形状见 `_caption_row`）。

    类型用**原文**判（译文会改变文字形状，判据只对原文成立）——与 `outline` 一致。
    """
    kinds = _kinds_of(blocks)
    rows: list[dict] = []
    for block in blocks:
        if kinds.get(block.block_id) != _CAPTION:
            continue
        rows.append(_caption_row(block))
    return rows


def _neighbor(blocks: list[TaskBlock], index: int) -> dict | None:
    """取相邻块 `{block_id, text}`；越界（图注在首/尾）返回 None。"""
    if 0 <= index < len(blocks):
        block = blocks[index]
        return {"block_id": block.block_id, "text": _text_of(block)}
    return None


def list_figures(ctx: ToolContext, args: dict | None = None) -> ToolResult:
    """列出该文献的图注 / 表注，返回 `[{block_id, kind, text, page_hint}]`。"""
    payload = _payload(args)
    task_id = _as_int(payload.get("task_id"))
    if task_id is None:
        return ToolResult(data=[], note="需要 task_id（先用 list_tasks 找到文献）")

    with SessionLocal() as db:
        task = _owned_task(db, ctx.user_id, task_id)
        if task is None:
            return ToolResult(data=[], note=_MISSING_TASK)
        blocks = _load_blocks(db, task.id)

    figures = _scan_captions(blocks, getattr(task, "regions", None))
    if not figures:
        if not blocks:
            return ToolResult(data=[], note=_NO_BLOCKS)
        return ToolResult(data=[], note=_EMPTY_NOTE)
    return ToolResult(
        data=figures,
        note=f"{len(figures)} 条图注；读其中一条用 read_figure(task_id, block_id)",
    )


def read_figure(ctx: ToolContext, args: dict | None = None) -> ToolResult:
    """读一条图注**及其前后各 1 个块**：`{caption, before, after, page_hint}`。"""
    payload = _payload(args)
    task_id = _as_int(payload.get("task_id"))
    block_id = payload.get("block_id")
    if task_id is None:
        return ToolResult(data={"error": "没有指定 task_id"}, note="需要 task_id")
    if not isinstance(block_id, str) or not block_id.strip():
        return ToolResult(
            data={"error": "没有指定 block_id"},
            note="需要 block_id（先用 list_figures 看有哪些图注）",
        )
    block_id = block_id.strip()

    with SessionLocal() as db:
        task = _owned_task(db, ctx.user_id, task_id)
        if task is None:
            return ToolResult(data={"error": _MISSING_TASK}, note=_MISSING_TASK)
        blocks = _load_blocks(db, task.id)

    index = None
    for pos, block in enumerate(blocks):
        if block.block_id == block_id:
            index = pos
            break
    if index is None:
        error = (
            f"这篇文献里没有块 {block_id}"
            "（可能不属于这篇，或已删除；先用 list_figures 看有哪些图注）"
        )
        return ToolResult(data={"error": error}, note=error)

    block = blocks[index]
    kind = classify(block.text or "", block.block_id, block.layout)
    data = {
        "caption": {"block_id": block.block_id, "text": _text_of(block)},
        "before": _neighbor(blocks, index - 1),
        "after": _neighbor(blocks, index + 1),
        "page_hint": _page_hint(block.block_id),
    }
    note = f"图注 {block.block_id}"
    if data["page_hint"] is not None:
        note += f"（第 {data['page_hint']} 页）"
    else:
        note += "（块号不合约定，页码推不出来）"
    if kind != _CAPTION:
        note += f"；注意：这块的类型是 {kind}，不是图注"
    return ToolResult(data=data, note=note)


PACK = Pack(
    name="figures",
    tools=(
        ToolSpec(
            name="list_figures",
            description=(
                "列出某篇文献的图注 / 表注（按块顺序，返回 "
                "block_id / kind / text / page_hint）。"
                "用户问「这篇有几张图」时先用它；"
                "再按 block_id 用 read_figure 读其中一条。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "文献 id"},
                },
                "required": ["task_id"],
                "additionalProperties": False,
            },
            handler=list_figures,
            max_result_chars=3000,
        ),
        ToolSpec(
            name="read_figure",
            description=(
                "读某一条图注及其前后各 1 个块（图注常与正文互相引用），"
                "返回 caption / before / after / page_hint。"
                "block_id 用 list_figures 返回的编号。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "文献 id"},
                    "block_id": {
                        "type": "string",
                        "description": "list_figures 返回的 block_id",
                    },
                },
                "required": ["task_id", "block_id"],
                "additionalProperties": False,
            },
            handler=read_figure,
            max_result_chars=4000,
        ),
    ),
)
