"""记忆（M7）：跨文献的**用法偏好** —— 术语 / 译名偏好与引用习惯。

**它为什么存在**：现在每篇论文各翻各的——同一个词这篇叫「手性」、下篇叫「手征」，
学生读三篇看到三种说法，会怀疑是不是一个东西。这条链让"这个人习惯怎么说"
**变成可查、可改、可删的条目**，并能在请求前注入（`resolve`）。

⚠️ 三条口径（**别自己发明**）：

1. **这不是台账**：台账是 `memory_events`（L0 流水"几点几分做了什么"），
   记忆是**结论**（"他习惯把手性叫手征"）。两者不是一回事，别混、也别互相替代。
2. **这不是素材卡**：素材是"从文献里取出的证据"（有出处、有页码），
   记忆是"这个人的说法与偏好"（没有出处，是习惯）。数据模型 §4 已写明别把素材当记忆存。
3. ⭐ **系统不许背着人改**：只有用户自己（或他明确点头的动作）能写这张表。
   所以这里是**完整 CRUD**——能改、能删、能停用（`enabled=false`）。
   形态 §六的原话是"可看可删可下钻"，**自动学习不在这条链的范围里**。

⚠️ **句级纠错记忆（D8 的第三类）本轮不做**：它唯一的来源是 `block_edits`，
而那张表**现在 0 行**（没人点过"改译文"）。形态 §5 写死了前提——
`观测期 ≥14 天 且 曝光块数 ≥500` 之前一律"继续观测"，**现在建就是空壳**。
这里如实不建，等数据到了再说。
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db
from ..models import MemoryItem, User
from ..timeutil import iso_utc

logger = logging.getLogger(__name__)

router = APIRouter(tags=["memory"])

# 一条记忆最多存多少字（**截断而不是报错**：用户真写了长词条，不该因此丢偏好）
_TEXT_MAX = 500
# `cite` 这一类只认一个固定 source（引用习惯是"一条默认格式"，不是词表）
_CITE_SOURCE = "default"
_KINDS = ("term", "cite")
# 读取上限（别让一次读把库拖住）
_LIMIT_DEFAULT = 500
_LIMIT_MAX = 2000


def _unavailable(detail: str) -> HTTPException:
    """写不进去 → **503 + 人话**（不许返回编出来的 id，那是假象）。"""
    return HTTPException(status_code=503, detail=detail)


class MemoryItemIn(BaseModel):
    """新增 / 覆盖一条记忆：`{kind, source, target, enabled?}`。

    ⚠️ **按 `(user_id, kind, source)` 幂等**：同一个人同一个词再存一次就是**改**
    （覆盖 `target`），不堆第二行——否则"同一句话两个说法"会立刻自相矛盾。
    """

    kind: str = Field(default="term")
    source: str = Field(min_length=1, max_length=255)
    target: str = Field(min_length=1, max_length=20000)
    enabled: bool = True


class MemoryItemPatch(BaseModel):
    """改一条记忆：`{target?, enabled?}`（都不给 → 400，别做无意义的写）。"""

    target: str | None = Field(default=None, max_length=20000)
    enabled: bool | None = None


def _serialize(item: MemoryItem) -> dict:
    """一条记忆对外的样子（`hits` 要给出去：让用户看得出哪条真在起作用）。"""
    return {
        "id": item.id,
        "kind": item.kind,
        "source": item.source,
        "target": item.target,
        "hits": item.hits,
        "enabled": bool(item.enabled),
        "created_at": iso_utc(item.created_at),
        "updated_at": iso_utc(item.updated_at),
    }


def _normalize(kind: str, source: str) -> tuple[str, str]:
    """把 `kind` / `source` 归一化，并且**挡住没意义的组合**。

    - `kind` 只认 `term` / `cite`（别让随便一个字符串塞进来，那样界面没法渲染）；
    - `cite` 的 `source` 固定成 `default`（引用习惯是"一条默认格式"）。
    """
    kind = (kind or "").strip().lower()
    if kind not in _KINDS:
        raise HTTPException(
            status_code=400, detail=f"kind 只能是 {' 或 '.join(_KINDS)}"
        )
    source = (source or "").strip()
    if kind == "cite":
        source = _CITE_SOURCE
    if not source:
        raise HTTPException(status_code=400, detail="source 不能为空")
    return kind, source[:_TEXT_MAX]


@router.get("/api/memories")
def list_memories(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    kind: Annotated[str | None, Query()] = None,
    enabled: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=_LIMIT_MAX)] = _LIMIT_DEFAULT,
):
    """看这个人的记忆：`?kind? &enabled? &limit?` → `{items, counts}`。

    ⭐ **一条都没有时如实返回空列表**（界面显示"还没有记忆"，**不许编**）。
    `counts` 按 kind 分好组，界面上的"术语习惯 12 条"用的就是它。
    """
    stmt = select(MemoryItem).where(MemoryItem.user_id == user.id)
    if kind:
        if kind not in _KINDS:
            raise HTTPException(
                status_code=400, detail=f"kind 只能是 {' 或 '.join(_KINDS)}"
            )
        stmt = stmt.where(MemoryItem.kind == kind)
    if enabled is not None:
        stmt = stmt.where(MemoryItem.enabled.is_(bool(enabled)))
    rows = db.scalars(
        stmt.order_by(MemoryItem.kind.asc(), MemoryItem.id.desc()).limit(limit)
    ).all()

    # counts 用**全量**（不受 kind / enabled 过滤影响），否则界面上的数字会互相矛盾
    all_rows = db.scalars(select(MemoryItem).where(MemoryItem.user_id == user.id)).all()
    counts = {k: 0 for k in _KINDS}
    enabled_counts = {k: 0 for k in _KINDS}
    for row in all_rows:
        counts[row.kind] = counts.get(row.kind, 0) + 1
        if row.enabled:
            enabled_counts[row.kind] = enabled_counts.get(row.kind, 0) + 1
    return {
        "items": [_serialize(row) for row in rows],
        "counts": counts,
        "enabled_counts": enabled_counts,
    }


@router.post("/api/memories", status_code=201)
def upsert_memory(
    payload: MemoryItemIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """新增或覆盖一条记忆（**按 `(user_id, kind, source)` 幂等**）。

    响应 `201 {item, created}`。

    `created=false` 表示"这个词原来就记过，这次是改了它的说法"——
    ⚠️ **改的时候不许把 `hits` 清零**（它是"这条真被用过几次"的账，不是这条记录的年龄）。
    """
    kind, source = _normalize(payload.kind, payload.source)
    target = payload.target.strip()
    if not target:
        raise HTTPException(status_code=400, detail="target 不能为空")

    existing = db.scalars(
        select(MemoryItem).where(
            MemoryItem.user_id == user.id,
            MemoryItem.kind == kind,
            MemoryItem.source == source,
        )
    ).first()

    if existing is not None:
        existing.target = target
        existing.enabled = bool(payload.enabled)
        try:
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("记忆更新失败：user=%s kind=%s", user.id, kind)
            raise _unavailable("记忆没存上（服务端写入失败）") from None
        db.refresh(existing)
        return {"item": _serialize(existing), "created": False}

    row = MemoryItem(
        user_id=user.id,
        kind=kind,
        source=source,
        target=target,
        enabled=bool(payload.enabled),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # 并发双写撞唯一键：回滚后按"已存在"再走一次覆盖（不是错误，是同一件事晚了一步）
        db.rollback()
        again = db.scalars(
            select(MemoryItem).where(
                MemoryItem.user_id == user.id,
                MemoryItem.kind == kind,
                MemoryItem.source == source,
            )
        ).first()
        if again is None:
            raise _unavailable("记忆没存上（服务端写入失败）") from None
        again.target = target
        again.enabled = bool(payload.enabled)
        db.commit()
        db.refresh(again)
        return {"item": _serialize(again), "created": False}
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("记忆写入失败：user=%s kind=%s", user.id, kind)
        raise _unavailable("记忆没存上（服务端写入失败）") from None
    db.refresh(row)
    return {"item": _serialize(row), "created": True}


@router.patch("/api/memories/{item_id}")
def update_memory(
    item_id: int,
    payload: MemoryItemPatch,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """改一条（`target` 换说法 / `enabled` 停用）→ 200 `{item}`。

    ⚠️ **别人的记忆一律 404**（不暴露"存在但无权限"，与全站口径一致）。
    ⚠️ 两个字段都不给 → **400**（别做无意义的写，也别假装成功）。
    """
    row = db.scalars(
        select(MemoryItem).where(
            MemoryItem.id == item_id, MemoryItem.user_id == user.id
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="记忆不存在")

    if payload.target is None and payload.enabled is None:
        raise HTTPException(status_code=400, detail="没有要改的字段")

    if payload.target is not None:
        target = payload.target.strip()
        if not target:
            raise HTTPException(status_code=400, detail="target 不能为空")
        row.target = target
    if payload.enabled is not None:
        row.enabled = bool(payload.enabled)

    try:
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("记忆更新失败：id=%s", item_id)
        raise _unavailable("记忆没改上（服务端写入失败）") from None
    db.refresh(row)
    return {"item": _serialize(row)}


@router.delete("/api/memories/{item_id}")
def delete_memory(
    item_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """删一条 → `{deleted: true, id}`（**真删**，不是软删）。

    ⚠️ 记忆不是留痕：留痕（`block_edits` / `memory_events`）不许删，
    而记忆是用户自己的偏好——他说删就该**真的删掉**，留着才是错的。
    """
    row = db.scalars(
        select(MemoryItem).where(
            MemoryItem.id == item_id, MemoryItem.user_id == user.id
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    db.delete(row)
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("记忆删除失败：id=%s", item_id)
        raise _unavailable("记忆没删掉（服务端写入失败）") from None
    return {"deleted": True, "id": item_id}


@router.get("/api/memories/resolve")
def resolve_memories(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """**请求前注入用**：把启用的记忆取成按 kind 分好的字典 → `{terms, cite, counts}`。

    - `terms`：`{"chiral": "手性", ...}`（原文 → 这个人习惯的译法）；
    - `cite`：`"author-year"` / `"numeric"` 这类格式标识（没有就 `null`）；
    - ⚠️ **只回启用的**（`enabled=false` 的不注入）；
    - ⭐ 取过的条目 `hits += 1`（"这条真被用上过几次"的账）。
      `resolve` 的语义就是"要拿去用了"，所以这里计数是对的；
      调用方**别把它当普通列表接口反复调**。
    """
    rows = db.scalars(
        select(MemoryItem).where(
            MemoryItem.user_id == user.id, MemoryItem.enabled.is_(True)
        )
    ).all()

    terms: dict[str, str] = {}
    cite: str | None = None
    for row in rows:
        if row.kind == "term":
            terms[row.source] = row.target
        elif row.kind == "cite":
            cite = row.target
        row.hits = (row.hits or 0) + 1

    counts = {"term": len(terms), "cite": 1 if cite else 0}
    if rows:
        try:
            db.commit()
        except Exception:  # noqa: BLE001
            # 计数写失败**不影响本次注入**（不能因为记不上账就把记忆丢了）
            db.rollback()
            logger.exception("记忆命中计数失败：user=%s", user.id)
    return {"terms": terms, "cite": cite, "counts": counts}
