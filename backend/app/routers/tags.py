"""知识库 · 标签（契约 §2.2 的 N6–N7，共 2 个端点）。

口径（照契约与数据模型，**别联错东西**）：

- 三类 `kind ∈ {topic, method, status}`；
- ⭐ **`kind='status'` 的标签与 `tasks.reading_status` 不互为镜像、不做同步**：
  前者是**用户自己额外打的**状态标签，后者是驱动「待读 / 在读 / 已读」
  三个入口的那一份数据
  （落在 `tasks` 列上）。改一个，另一个**必须不动**；
- **按名字 upsert**（N7）：`(user_id, kind, name)` 唯一，同一名字同一类复用同一行；
- ⚠️ **本期不做**标签重命名 / 合并（契约明写）——所以这里没有 PATCH。

计数口径与集合那边一致：**只数没归档的文献**（列表里藏起来的不算进"N 篇"）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db, load_owned_task
from ..models import Tag, Task, TaskTag, User

router = APIRouter(prefix="/api/tags", tags=["tags"])
task_router = APIRouter(prefix="/api/tasks", tags=["tags"])

KINDS = ("topic", "method", "status")
_BAD_TAGS = "tags 要形如 [{name, kind}]，kind ∈ {topic, method, status}"


@router.get("")
def list_tags(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    kind: Annotated[str | None, Query()] = None,
):
    """N6 标签列表（`?kind?`）。

    **认不出的 kind 回空表**——与前端 mock 一致，不是错误。
    """
    stmt = select(Tag).where(Tag.user_id == user.id)
    if kind:
        stmt = stmt.where(Tag.kind == kind)
    rows = db.scalars(stmt.order_by(Tag.kind, Tag.name)).all()
    counts = {
        tag_id: count
        for tag_id, count in db.execute(
            select(TaskTag.tag_id, func.count())
            .join(Task, Task.id == TaskTag.task_id)
            .where(Task.user_id == user.id, Task.archived_at.is_(None))
            .group_by(TaskTag.tag_id)
        ).all()
    }
    return {
        "items": [
            {
                "id": row.id,
                "name": row.name,
                "kind": row.kind,
                # ⚠️ 按 `tag_id` 数（前端 mock 是按**名字**数的）：
                # 同名不同类是两个标签，按名字数会把它们的文献算到一起。
                "doc_count": counts.get(row.id, 0),
            }
            for row in rows
        ]
    }


class TagIn(BaseModel):
    name: str
    kind: str


class TaskTagsIn(BaseModel):
    tags: list[TagIn]


@task_router.put("/{task_id}/tags")
def set_task_tags(
    task_id: int,
    payload: TaskTagsIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N7 按名字 upsert 标签，并**全量替换这篇文献的标签集**（PUT 语义）。

    - 没见过的 `(name, kind)` → 建一行；见过的 → 复用（`upsert`）；
    - 非法 `kind` / 空名字 → 400（同一句话，与 mock 逐字一致）；
    - 别人的文献 → 404。
    """
    task = load_owned_task(db, user, task_id)
    saved: list[Tag] = []
    seen: set[tuple[str, str]] = set()
    for item in payload.tags:
        name = str(item.name or "").strip()
        if not name or item.kind not in KINDS:
            raise HTTPException(status_code=400, detail=_BAD_TAGS)
        if (name, item.kind) in seen:  # 同一个请求里重复，只算一次（否则撞唯一约束）
            continue
        seen.add((name, item.kind))
        row = db.scalar(
            select(Tag).where(
                Tag.user_id == user.id, Tag.kind == item.kind, Tag.name == name
            )
        )
        if row is None:
            row = Tag(user_id=user.id, name=name, kind=item.kind)
            db.add(row)
            db.flush()
        saved.append(row)

    db.execute(delete(TaskTag).where(TaskTag.task_id == task.id))
    for row in saved:
        db.add(TaskTag(task_id=task.id, tag_id=row.id))
    db.commit()
    return {
        "tags": [{"id": row.id, "name": row.name, "kind": row.kind} for row in saved]
    }
