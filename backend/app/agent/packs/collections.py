"""知识库「集合」工具包（2026-10-19）：让读懂侧 agent 能真的管知识库。

背景（用户实测反馈）：他说「帮我归类到数学这个集合，没有就创建」，
agent 只能回「我没有创建集合的能力」——而**后端 N1–N5 与集合页早就有**，
缺的只是"给 agent 的工具"。这次补上。

三个工具（故意只给三个，工具预算上限 15 很紧）：

- `list_collections`：我有哪些集合、各自几篇（**直接成员数**，与 N1 同口径）；
- `create_collection(name, parent_id=None)`：建集合。同父重名 / 父不存在 →
  如实说明，不重试乱建；
- `assign_task(task_id, collection, mode)`：把一篇文献放进/移出集合。
  `mode` 只能是 add / remove / set；`collection` 可以是**名字**或 id。
  ⚠️ N5 接口是**全量替换**，所以 add/remove 在这里先读懂现状再写回——
  调用方（模型）不用自己读一遍。

⚠️ 不许 import pydantic_ai（结构用例钉着）。
"""

from __future__ import annotations

from sqlalchemy import select

from ...db import SessionLocal
from ...models import Collection, Task, TaskCollection
from ..contracts import Pack, ToolResult, ToolSpec

_MODE = {"add", "remove", "set"}


def _view(row: Collection, count: int) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "parent_id": row.parent_id,
        "doc_count": count,
    }


def _counts(db, user_id: int) -> dict[int, int]:
    """每个集合的**直接成员数**（子集合的不算，与 N1 同一条语义）。"""
    rows = db.execute(
        select(TaskCollection.collection_id, TaskCollection.task_id)
        .join(Task, Task.id == TaskCollection.task_id)
        .where(Task.user_id == user_id)
    ).all()
    counts: dict[int, int] = {}
    for collection_id, _task_id in rows:
        counts[collection_id] = counts.get(collection_id, 0) + 1
    return counts


def list_collections(ctx, args: dict | None = None) -> ToolResult:
    """我有哪些集合（附直接成员数）。"""
    with SessionLocal() as db:
        rows = db.scalars(
            select(Collection)
            .where(Collection.user_id == ctx.user_id)
            .order_by(Collection.sort, Collection.id)
        ).all()
        counts = _counts(db, ctx.user_id)
        items = [_view(row, counts.get(row.id, 0)) for row in rows]
    if not items:
        return ToolResult(data=[], note="还没有集合——可以用 create_collection 建一个")
    return ToolResult(data=items, note=f"{len(items)} 个集合")


def create_collection(ctx, args: dict | None = None) -> ToolResult:
    """建一个集合（可指定父集合做成子集合）。"""
    payload = args or {}
    name = str(payload.get("name") or "").strip()
    parent_id = payload.get("parent_id")
    if not name:
        return ToolResult(data={}, note="要给集合名字")
    if len(name) > 64:
        return ToolResult(data={}, note="名字太长（最多 64 字）")

    with SessionLocal() as db:
        if parent_id is not None:
            parent = db.scalar(
                select(Collection).where(
                    Collection.id == int(parent_id),
                    Collection.user_id == ctx.user_id,
                )
            )
            if parent is None:
                return ToolResult(data={}, note="父集合不存在（或不是你的）")

        same_level = (
            Collection.parent_id.is_(None)
            if parent_id is None
            else Collection.parent_id == int(parent_id)
        )
        clash = db.scalar(
            select(Collection.id).where(
                Collection.user_id == ctx.user_id,
                Collection.name == name,
                same_level,
            )
        )
        if clash is not None:
            return ToolResult(
                data={"existing_id": clash},
                note=f"同一层已经有叫「{name}」的集合了（id={clash}），直接用它就行",
            )

        row = Collection(
            user_id=ctx.user_id,
            name=name,
            parent_id=None if parent_id is None else int(parent_id),
            sort=0,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        created = _view(row, 0)

    return ToolResult(data=created, note=f"已建集合「{name}」（id={created['id']}）")


def _resolve_collection(db, user_id: int, target) -> Collection | None:
    """按 id 或名字找集合（名字允许大小写与空白差异，找不到就 None）。"""
    is_id = isinstance(target, int) or (
        isinstance(target, str) and target.strip().isdigit()
    )
    if is_id:
        return db.scalar(
            select(Collection).where(
                Collection.id == int(target), Collection.user_id == user_id
            )
        )
    name = str(target or "").strip()
    if not name:
        return None
    rows = db.scalars(select(Collection).where(Collection.user_id == user_id)).all()
    for row in rows:
        if row.name.strip().lower() == name.lower():
            return row
    return None


def assign_task(ctx, args: dict | None = None) -> ToolResult:
    """把一篇文献放进 / 移出某个集合（N5 是全量替换，这里替调用方算好）。"""
    payload = args or {}
    task_id = payload.get("task_id")
    mode = str(payload.get("mode") or "add").strip().lower()
    if not isinstance(task_id, int):
        return ToolResult(data={}, note="需要 task_id（先用 list_tasks 找到那篇）")
    if mode not in _MODE:
        return ToolResult(data={}, note="mode 只能是 add / remove / set")

    with SessionLocal() as db:
        task = db.scalar(
            select(Task).where(Task.id == task_id, Task.user_id == ctx.user_id)
        )
        if task is None:
            return ToolResult(data={}, note="这篇文献不在你的库里（或已删除）")

        current = {
            row.collection_id
            for row in db.scalars(
                select(TaskCollection).where(TaskCollection.task_id == task.id)
            ).all()
        }

        if mode == "set":
            targets = payload.get("collections") or []
            resolved: list[Collection] = []
            for item in targets:
                hit = _resolve_collection(db, ctx.user_id, item)
                if hit is None:
                    return ToolResult(data={}, note=f"没有这个集合：{item}")
                resolved.append(hit)
            wanted = {row.id for row in resolved}
        else:
            hit = _resolve_collection(db, ctx.user_id, payload.get("collection"))
            if hit is None:
                return ToolResult(
                    data={},
                    note="没有这个集合（先用 list_collections 看看有哪些）",
                )
            wanted = set(current)
            if mode == "add":
                wanted.add(hit.id)
            else:
                wanted.discard(hit.id)

        db.execute(
            TaskCollection.__table__.delete().where(
                TaskCollection.task_id == task.id
            )
        )
        for collection_id in sorted(wanted):
            db.add(TaskCollection(task_id=task.id, collection_id=collection_id))
        db.commit()
        # ⚠️ 会话关了之后 ORM 对象不能再读属性（DetachedInstanceError），先取出来
        task_name = task.filename

        names: list[str] = []
        if wanted:
            rows = db.scalars(select(Collection).where(Collection.id.in_(wanted))).all()
            names = [row.name for row in rows]

    return ToolResult(
        data={"task_id": task_id, "collection_ids": sorted(wanted)},
        note=(
            f"已把「{task_name}」放到：{'、'.join(names)}"
            if names
            else f"已把「{task_name}」移出所有集合（回到未归类）"
        ),
    )


PACK = Pack(
    name="collections",
    tools=(
        ToolSpec(
            name="list_collections",
            description=(
                "列出我的知识库集合（id / 名字 / 父集合 / 直接成员数）。"
                "要归类文献前，先用它看看有没有合适的集合。"
            ),
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=list_collections,
            max_result_chars=3000,
        ),
        ToolSpec(
            name="create_collection",
            description=(
                "新建一个集合（可指定 parent_id 做子集合）。"
                "同层重名会返回已有那个的 id，不会重复建。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "集合名字，如「数学」"},
                    "parent_id": {
                        "type": "integer",
                        "description": "可选：父集合 id（省略 = 顶层）",
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
            handler=create_collection,
            max_result_chars=1000,
        ),
        ToolSpec(
            name="assign_task",
            description=(
                "把一篇文献放进 / 移出集合。mode=add 加入、remove 移出、set 全量替换。"
                "collection 可以是集合名或 id；一篇文献可以属于多个集合。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "文献 id"},
                    "mode": {
                        "type": "string",
                        "enum": ["add", "remove", "set"],
                        "description": "add / remove / set（默认 add）",
                    },
                    "collection": {
                        "type": "string",
                        "description": "集合名或 id（set 时可省略）",
                    },
                    "collections": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "mode=set 时的完整集合列表（名字或 id）",
                    },
                },
                "required": ["task_id"],
                "additionalProperties": False,
            },
            handler=assign_task,
            max_result_chars=1000,
        ),
    ),
)
