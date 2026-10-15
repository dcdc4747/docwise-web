"""知识库 · 集合（契约 §2.1 的 N1–N5，共 5 个端点）。

三条钉子（照契约与数据模型，**别发明第三种语义**）：

- ⭐ **子集合的文献不算在父集合里**：`doc_count` 只数**直接成员**；要"含子集合共 N"
  只能用括号辅数 `doc_count_deep`；
- ⭐ **成环由服务端挡**（把集合移进自己的后代 → 400），不许只靠前端；
- **同一父下不许重名**（不同父下可以同名）→ 400。

另外两条是本实现特意补的，写清楚免得以后被"优化"掉：

- ⚠️ **改名 / 移动也要查重**：库上有唯一约束 `(user_id, parent_id, name)`，
  不查就会撞库变成 500。前端 mock 里没有这条检查——它能过是因为它跑在内存里，
  **不是因为我们不需要**；
- ⚠️ **计数只数没归档的文献**（`archived_at is null`）：列表里藏起来的不该算进"N 篇"，
  否则界面说 12 篇、点进去只有 5 篇（"藏 ≠ 删"是另一件事：详情/下载照旧可用）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db, load_owned_task
from ..models import Collection, Task, TaskCollection, User

router = APIRouter(prefix="/api/collections", tags=["collections"])
# N5 的路径挂在 `/api/tasks/{task_id}/collections` 下（契约 §2.2），单独一个 router
task_router = APIRouter(prefix="/api/tasks", tags=["collections"])

_NAME_MAX = 64


# ============================================================ 小工具

def _clean_name(raw: object) -> str:
    """名字 1–64 字（与 mock 同一句话）。空白/超长一律 400，不走 pydantic 的 422。"""
    name = str(raw or "").strip()
    if not name or len(name) > _NAME_MAX:
        raise HTTPException(status_code=400, detail="名字要 1–64 个字")
    return name


def _owned(db: Session, user: User, collection_id: int) -> Collection:
    """只认自己的集合；别人的与不存在的**回同一句 404**（不暴露"存在但无权限"）。"""
    row = db.scalar(
        select(Collection).where(
            Collection.id == collection_id, Collection.user_id == user.id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="集合不存在")
    return row


def _parent_or_400(db: Session, user: User, parent_id: int) -> None:
    """父集合不存在（或不是自己的）→ **400**（契约 §2.1 写的是 400，不是 404）。"""
    exists = db.scalar(
        select(Collection.id).where(
            Collection.id == parent_id, Collection.user_id == user.id
        )
    )
    if exists is None:
        raise HTTPException(status_code=400, detail="父集合不存在")


def _reject_duplicate(
    db: Session,
    user: User,
    parent_id: int | None,
    name: str,
    *,
    exclude_id: int | None = None,
) -> None:
    """同一父下不许重名（`parent_id is null` 是顶层那一组）。"""
    parent_clause = (
        Collection.parent_id.is_(None)
        if parent_id is None
        else Collection.parent_id == parent_id
    )
    stmt = select(Collection.id).where(
        Collection.user_id == user.id,
        parent_clause,
        Collection.name == name,
    )
    if exclude_id is not None:
        stmt = stmt.where(Collection.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(status_code=400, detail="同一个父集合下不许重名")


def _tree(db: Session, user: User) -> tuple[dict[int, list[int]], dict[int, int]]:
    """一次取齐：`children`（父 → 直接子）与 `direct`（集合 → 直接成员数）。"""
    children: dict[int, list[int]] = {}
    for row in db.scalars(
        select(Collection).where(Collection.user_id == user.id)
    ).all():
        if row.parent_id is not None:
            children.setdefault(row.parent_id, []).append(row.id)
    direct = {
        collection_id: count
        for collection_id, count in db.execute(
            select(TaskCollection.collection_id, func.count())
            .join(Task, Task.id == TaskCollection.task_id)
            .where(Task.user_id == user.id, Task.archived_at.is_(None))
            .group_by(TaskCollection.collection_id)
        ).all()
    }
    return children, direct


def _deep(cid: int, direct: dict[int, int], children: dict[int, list[int]]) -> int:
    """含子集合的聚合数（括号辅数）——`doc_count` 永远只用 `direct`。"""
    return direct.get(cid, 0) + sum(
        _deep(child, direct, children) for child in children.get(cid, ())
    )


def _descendants(cid: int, children: dict[int, list[int]]) -> set[int]:
    found: set[int] = set()
    stack = list(children.get(cid, ()))
    while stack:
        current = stack.pop()
        if current in found:
            continue
        found.add(current)
        stack.extend(children.get(current, ()))
    return found


def _view(
    row: Collection, direct: dict[int, int], children: dict[int, list[int]]
) -> dict:
    """集合对象（契约 §2.1）。

    字段：`{id, name, parent_id, sort, doc_count, doc_count_deep}`。
    """
    return {
        "id": row.id,
        "name": row.name,
        "parent_id": row.parent_id,
        "sort": row.sort,
        "doc_count": direct.get(row.id, 0),
        "doc_count_deep": _deep(row.id, direct, children),
    }


# ============================================================ N1–N4

@router.get("")
def list_collections(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N1 集合列表。**两个计数都给**：主的 `doc_count` 是直接成员数。"""
    rows = db.scalars(
        select(Collection)
        .where(Collection.user_id == user.id)
        .order_by(Collection.sort, Collection.id)
    ).all()
    children, direct = _tree(db, user)
    return {"items": [_view(row, direct, children) for row in rows]}


class CollectionIn(BaseModel):
    name: str
    parent_id: int | None = None


@router.post("", status_code=201)
def create_collection(
    payload: CollectionIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N2 新建集合。400：同父重名 / 父不存在 / 名字不合法。"""
    name = _clean_name(payload.name)
    if payload.parent_id is not None:
        _parent_or_400(db, user, payload.parent_id)
    _reject_duplicate(db, user, payload.parent_id, name)
    row = Collection(user_id=user.id, name=name, parent_id=payload.parent_id, sort=0)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _view(row, {}, {})


class CollectionPatch(BaseModel):
    name: str | None = None
    parent_id: int | None = None
    sort: int | None = None


@router.patch("/{collection_id}")
def patch_collection(
    collection_id: int,
    payload: CollectionPatch,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N3 改名 / 移动 / 排序。**400 成环**（不许把自己移进自己的后代）。

    ⚠️ `parent_id` 用 `model_fields_set` 区分"没传"与"传了 null"——传 null 是
    **移到顶层**这个有意义的动作，不能和"没传"混为一谈（与 `PATCH /api/me` 同一套）。
    """
    row = _owned(db, user, collection_id)
    fields = payload.model_fields_set
    children, direct = _tree(db, user)

    name = row.name if "name" not in fields else _clean_name(payload.name)
    parent_id = row.parent_id
    if "parent_id" in fields:
        parent_id = payload.parent_id
        if parent_id is not None:
            _parent_or_400(db, user, parent_id)
            if parent_id == row.id or parent_id in _descendants(row.id, children):
                raise HTTPException(status_code=400, detail="不许把集合移进自己的后代")
    if name != row.name or parent_id != row.parent_id:
        _reject_duplicate(db, user, parent_id, name, exclude_id=row.id)

    row.name = name
    row.parent_id = parent_id
    if "sort" in fields and payload.sort is not None:
        row.sort = payload.sort
    db.commit()
    db.refresh(row)
    children, direct = _tree(db, user)
    return _view(row, direct, children)


@router.delete("/{collection_id}")
def delete_collection(
    collection_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N4 **只删集合，不动文献**：子集合回到被删集合的父级，挂在它身上的文献也一并脱离。

    ⚠️ `moved_to_parent` **必须在删关联之前算**（先算再删）——清空关联之后再数永远是 0
    （前端 mock 里就为这一条留了注释，别把顺序写反）。
    """
    row = _owned(db, user, collection_id)
    children = db.scalars(
        select(Collection).where(
            Collection.user_id == user.id, Collection.parent_id == row.id
        )
    ).all()
    moved_docs = db.scalar(
        select(func.count())
        .select_from(TaskCollection)
        .join(Task, Task.id == TaskCollection.task_id)
        .where(
            TaskCollection.collection_id == row.id,
            Task.user_id == user.id,
            Task.archived_at.is_(None),
        )
    )
    moved = len(children) + int(moved_docs or 0)

    for child in children:
        child.parent_id = row.parent_id
    db.execute(delete(TaskCollection).where(TaskCollection.collection_id == row.id))
    db.delete(row)
    db.commit()
    return {"deleted": True, "moved_to_parent": moved}


# ============================================================ N5

class TaskCollectionsIn(BaseModel):
    collection_ids: list[int]


@task_router.put("/{task_id}/collections")
def set_task_collections(
    task_id: int,
    payload: TaskCollectionsIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N5 文献归集，**全量替换**（天然支持"一篇挂多个"）。

    别人的文献 404；别人的集合 id 与不存在的 id **回同一句 400**（不暴露存在性）。
    """
    task = load_owned_task(db, user, task_id)
    ids = list(dict.fromkeys(payload.collection_ids))
    mine = set(
        db.scalars(
            select(Collection.id).where(
                Collection.user_id == user.id, Collection.id.in_(ids)
            )
        ).all()
    ) if ids else set()
    for cid in ids:
        if cid not in mine:
            raise HTTPException(status_code=400, detail=f"集合不存在：{cid}")

    db.execute(delete(TaskCollection).where(TaskCollection.task_id == task.id))
    for cid in ids:
        db.add(TaskCollection(task_id=task.id, collection_id=cid))
    db.commit()
    return {"collection_ids": ids}
