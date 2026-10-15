"""素材卡（M2 / 契约 §2.4 的 N12–N14，共 3 个端点）。

设计口径（照契约，别自己发明）：

- ⭐⭐ `Material` 是**快照，不是活引用**：`text_quote` / `translated_quote` / `page` /
  `source_name` **在创建时深拷贝**。判据的根就在这儿——"**删掉源任务后素材卡仍显示
  出处**"。所以这里**不许 JOIN `tasks` 去取 `source_name` / `page`**，那就退回活引用了。
- `task_id` 只用于"回跳原文"：源文献被删时**置 null 且不级联删卡**（脱开动作写在
  `routers/tasks.py` 的删除流程里），界面此时如实说"源文献已删除，仅存快照"。
- 软删：`DELETE` 只写 `deleted_at`（设计规范 §7.7 的撤销窗口），列表不返回软的；
  重复删**幂等**（第二次仍回 200）。
- 归属：一律只认当前账号，非本人 404（不暴露"存在但无权限"）。
- 接口形状与前端契约 mock 的 `materialView` **逐字段对齐**（对账用例在
  `frontend/tests/contract-mock.test.js`）。
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db
from ..models import Material, Tag, Task, TaskBlock, TaskCollection, TaskTag, User
from ..timeutil import iso_utc, utc_now

router = APIRouter(prefix="/api/materials", tags=["materials"])

# `block_id` 的约定是 `p{页序从 0 起}_b{块序号}`（见 scripts/extract_blocks.py）。
# 人读的页码要 +1——**与前端出处芯片同一口径**，别各算一套。
_BLOCK_RE = re.compile(r"^p(\d+)_b\d+$")
_NOTE_MAX = 500


def _page_of(block_id: str) -> int | None:
    """从块编号推人读页码；推不出返回 None（**不编页码**）。"""
    match = _BLOCK_RE.match(block_id or "")
    return int(match.group(1)) + 1 if match else None


def _serialize(row: Material) -> dict:
    """`Material` 对象（字段与前端 mock 的 `materialView` 对齐）。"""
    return {
        "id": row.id,
        "text_quote": row.text_quote,
        "translated_quote": row.translated_quote,
        "page": row.page,
        "source_name": row.source_name,
        "note": row.note,
        "task_id": row.task_id,
        "block_id": row.block_id,
        "deleted_at": iso_utc(row.deleted_at) if row.deleted_at else None,
        "created_at": iso_utc(row.created_at),
    }


class MaterialIn(BaseModel):
    task_id: int
    block_id: str = Field(min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=_NOTE_MAX)


@router.post("", status_code=201)
def create_material(
    payload: MaterialIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N12 存为素材卡（**快照**）。契约 §2.4：块不存在 → 404。

    ⚠️ 他人的任务、以及**编号里推不出页码的块**，同样 404 / 400 —— 后者是因为
    `page` 是必填列，而"编一个页码"比拒绝更糟（它会印在出处芯片上）。
    """
    task = db.get(Task, payload.task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="块不存在")

    block = db.scalar(
        select(TaskBlock).where(
            TaskBlock.task_id == task.id, TaskBlock.block_id == payload.block_id
        )
    )
    if block is None:
        raise HTTPException(status_code=404, detail="块不存在")

    page = _page_of(block.block_id)
    if page is None:
        raise HTTPException(
            status_code=400,
            detail="这个块的编号推不出页码，暂不支持存为素材（不编页码）",
        )

    row = Material(
        user_id=user.id,
        task_id=task.id,
        block_id=block.block_id,
        # ⭐ 四个快照字段：**创建时深拷贝**（见模块文档）
        text_quote=block.text,
        translated_quote=block.translated,
        page=page,
        source_name=task.filename,
        note=payload.note or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.get("")
def list_materials(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    task_id: Annotated[int | None, Query()] = None,
    collection_id: Annotated[int | None, Query()] = None,
    tag: Annotated[str | None, Query()] = None,
):
    """N13 素材列表。软删的不返回；`?collection_id?` `&tag?` 按**源文献**所属筛。

    集合与标签都挂在**文献**上（`task_collections` / `task_tags`），所以筛出来的
    是"源文献在这些集合里"的素材卡。⚠️ `task_id` 为 null 的卡（源文献已删）
    不会出现在这两种筛选里——它们已经不属于任何集合了。
    """
    stmt = select(Material).where(
        Material.user_id == user.id, Material.deleted_at.is_(None)
    )
    if task_id is not None:
        stmt = stmt.where(Material.task_id == task_id)
    if collection_id is not None:
        stmt = stmt.join(
            TaskCollection, TaskCollection.task_id == Material.task_id
        ).where(TaskCollection.collection_id == collection_id)
    if tag:
        stmt = (
            stmt.join(TaskTag, TaskTag.task_id == Material.task_id)
            .join(Tag, Tag.id == TaskTag.tag_id)
            .where(Tag.user_id == user.id, Tag.name == tag)
        )
    rows = db.scalars(stmt.order_by(Material.id.desc())).all()
    return {"items": [_serialize(row) for row in rows]}


@router.delete("/{material_id}")
def delete_material(
    material_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N14 软删（设计规范 §7.7 的撤销窗口）。**幂等**：再删一次仍回 200。"""
    row = db.scalar(
        select(Material).where(Material.id == material_id, Material.user_id == user.id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    if row.deleted_at is None:
        row.deleted_at = utc_now()
        db.commit()
        db.refresh(row)
    return {"deleted": True, "id": row.id, "deleted_at": iso_utc(row.deleted_at)}
