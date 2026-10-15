"""译文改动与块曝光（埋点 1，契约 §2.9 / §2.10 → N33 / N34）。

**为什么要有这条链**：官方核验 AI 工具使用时要看两样东西——**人工筛选修改过程**
与**学生团队的实质性贡献**。在这之前，全库**没有任何"人对译文做了什么"的记录**：
模型译完就直接是最终稿，改没改过、谁改的、改成什么，都无从查起。这一卡补上它。

三处用途（都是既有的，别再造）：

1. **台账（N17 / 处理过程一屏）**：改动逐条显示"哪一块、改前是什么、改后是什么"；
2. **个人中心 ④ "哪些被人改过"**：契约 §2.9 写明这一区就是靠它；
3. **M7 句级纠错记忆的唯一来源**（契约 §3 的映射表）。
   ⚠️ 本轮**只布埋点**：观测期 ≥14 天且曝光块数 ≥500 之前不判"建 / 砍"，
   引用"修改率"必须带前提"**是在提供了编辑入口的条件下测的**"（入口会抬高修改率）。

口径（照契约，别自己发明）：

- **归属**：`task_id` 必须是自己那篇（非本人 **404**，不暴露"存在但无权限"）；
  块必须真的在**该任务**里（不在 → 404 "块不存在"）。
- **`text_hash` 由服务端算**（原文的 sha256）：不接受客户端传——
  否则"改的是哪一句"就成了别人说了算，这份留痕也就不可信了。
- **曝光幂等**：唯一键 `(user_id, task_id, block_id, session_id)`（契约 §2.10）。
  重复上报**不长新行**，只把 `left_at` 往后推（"这块看了更久"）。
- **"写了"不许有假象**：写不进去 → **503 + 人话**，不返回编出来的 id。
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db, load_owned_task
from ..ledger import record_event
from ..models import BlockEdit, BlockExposure, TaskBlock, User
from ..timeutil import iso_utc, utc_now

logger = logging.getLogger(__name__)

router = APIRouter(tags=["block-events"])

# 读取上限（契约没写默认值，这里定死并说明：别让一次读把库拖住）
_LIMIT_DEFAULT = 500
_LIMIT_MAX = 2000
# 一条改动记录最多存多少字（**截断而不是报错**：用户真写了长段，不该因此丢留痕）
_TEXT_MAX = 4000


class BlockEditIn(BaseModel):
    """N33 请求体：`{task_id, block_id, before, after}`。

    `before` 是**界面上当时显示的那一份**（第一次改动时就是模型译文），
    `after` 是用户改完的。两者的差别就是"逐条 diff"要显示的东西。
    """

    task_id: int
    block_id: str = Field(min_length=1, max_length=64)
    before: str = Field(default="", max_length=20000)
    after: str = Field(min_length=1, max_length=20000)


class BlockExposureIn(BaseModel):
    """N34 请求体：`{task_id, block_id, session_id, entered_at?, left_at?}`。

    `session_id` 由前端**一次打开阅读页生成一个**（契约 §2.10）；
    两个时间戳可省，省了就按服务端当前时间记。
    """

    task_id: int
    block_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=64)
    entered_at: str | None = None
    left_at: str | None = None


def _unavailable(detail: str) -> HTTPException:
    """503 + 人话：写不进去就如实说，**不假装成功**。"""
    return HTTPException(status_code=503, detail=detail)


def _load_block(db: Session, task_id: int, block_id: str) -> TaskBlock:
    """块必须真的在本任务里（跨任务的块 → 404，不给"存在但不在你这篇"的暗示）。"""
    row = db.scalars(
        select(TaskBlock).where(
            TaskBlock.task_id == task_id, TaskBlock.block_id == block_id
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="块不存在")
    return row


def _parse_time(raw: str | None) -> datetime:
    """容错解析 ISO 时间；解不出来就按"现在"（**不因为时间格式把上报整条丢掉**）。"""
    if not raw:
        return utc_now()
    try:
        text = raw.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed
        return parsed.astimezone().replace(tzinfo=None)
    except Exception:  # noqa: BLE001 - 时间格式不该让上报失败
        logger.warning("曝光时间解析失败，按当前时间记：%r", raw[:40])
        return utc_now()


def _page_of(block_id: str) -> int | None:
    """`p{页}_b{序}` → 页码（**推导不出就是 None，绝不编位置**）。"""
    if not block_id.startswith("p") or "_b" not in block_id:
        return None
    head = block_id[1:].split("_b", 1)[0]
    return int(head) + 1 if head.isdigit() else None


def _edit_view(row: BlockEdit) -> dict:
    """N33 读取一行的形状（前端"逐条 diff"与"已人工修改"标记都用它）。"""
    return {
        "id": row.id,
        "task_id": row.task_id,
        "block_id": row.block_id,
        "before": row.before,
        "after": row.after,
        "text_hash": row.text_hash,
        "created_at": iso_utc(row.created_at),
    }


@router.post("/api/block-edits", status_code=201)
def create_block_edit(
    payload: BlockEditIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N33 记一条译文改动 → `201 {id, block_id, edited}`。

    ⭐ 同时把 `task_blocks.translated` 更新成 `after`：用户改完就该一直是他的版本
    （刷新页面、下次打开阅读页都看到自己改的）。模型那一版**不丢**——
    它就留在这一行的 `before` 里，这正是"人改留痕"要的东西。
    """
    task = load_owned_task(db, user, payload.task_id)
    block = _load_block(db, task.id, payload.block_id)

    after = (payload.after or "").strip()
    before = payload.before or block.translated or ""
    if not after:
        raise HTTPException(status_code=400, detail="译文不能清空；要撤销请重新编辑")
    if after == before.strip():
        # 没改就别留痕：台账里多一条"改了但一模一样"的记录，比没有更糟
        raise HTTPException(status_code=400, detail="译文没有变化，未记录")

    row = BlockEdit(
        user_id=user.id,
        task_id=task.id,
        block_id=block.block_id,
        # 原文哈希由服务端算：让"改的是哪一句"有据可查，而不是客户端说了算
        text_hash=hashlib.sha256((block.text or "").encode("utf-8")).hexdigest(),
        before=before[:_TEXT_MAX],
        after=after[:_TEXT_MAX],
    )
    db.add(row)
    block.translated = after[:_TEXT_MAX]
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("译文改动写入失败：task=%s block=%s", task.id, block.block_id)
        raise _unavailable(
            "改动没写进去（服务端写入失败），这段译文没有被记录"
        ) from None
    db.refresh(row)

    page = _page_of(block.block_id)
    where = f"第 {page} 页" if page else "位置待定"
    record_event(
        user_id=user.id,
        task_id=task.id,
        stage="edit",
        actor="user",
        tool="manual-edit",
        summary=f"人工修改译文（{where} · {block.block_id}）："
        f"{len(before)} 字 → {len(after)} 字",
        payload={
            "block_id": block.block_id,
            "block_edit_id": row.id,
            "before": before[:_TEXT_MAX],
            "after": after[:_TEXT_MAX],
        },
    )
    return {"id": row.id, "block_id": block.block_id, "edited": True}


@router.get("/api/block-edits")
def list_block_edits(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    task_id: Annotated[int | None, Query()] = None,
    block_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int | None, Query()] = None,
):
    """N33 读改动（新的在前）→ `200 {items}`。

    ⚠️ 只读**自己的**：不带 `task_id` 时也只回本账号的记录。
    """
    if task_id is not None:
        load_owned_task(db, user, task_id)
    stmt = select(BlockEdit).where(BlockEdit.user_id == user.id)
    if task_id is not None:
        stmt = stmt.where(BlockEdit.task_id == task_id)
    if block_id:
        stmt = stmt.where(BlockEdit.block_id == block_id)
    stmt = stmt.order_by(BlockEdit.created_at.desc(), BlockEdit.id.desc())
    size = _LIMIT_DEFAULT if limit is None else max(1, min(int(limit), _LIMIT_MAX))
    rows = list(db.scalars(stmt.limit(size)).all())
    return {"items": [_edit_view(row) for row in rows]}


@router.post("/api/block-exposures", status_code=201)
def create_block_exposure(
    payload: BlockExposureIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N34 曝光上报 → `201 {id, created}`（**幂等**：重复上报不长新行）。

    幂等靠契约 §2.10 定死的唯一键 `(user_id, task_id, block_id, session_id)`：
    同一个会话里同一块**只记一次**；再报上来只把 `left_at` 往后推（看了更久）。
    """
    task = load_owned_task(db, user, payload.task_id)
    block = _load_block(db, task.id, payload.block_id)

    entered = _parse_time(payload.entered_at)
    left = _parse_time(payload.left_at)
    if left < entered:
        entered, left = left, entered

    existing = db.scalars(
        select(BlockExposure).where(
            BlockExposure.user_id == user.id,
            BlockExposure.task_id == task.id,
            BlockExposure.block_id == block.block_id,
            BlockExposure.session_id == payload.session_id,
        )
    ).first()

    if existing is not None:
        # 幂等：**不插新行**，只把"看到什么时候"往后推（时间倒退就不动）
        if left > existing.left_at:
            existing.left_at = left
            try:
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
                logger.exception(
                    "曝光时间更新失败：task=%s block=%s", task.id, block.block_id
                )
                raise _unavailable("曝光没记上（服务端写入失败）") from None
        return {"id": existing.id, "created": False}

    row = BlockExposure(
        user_id=user.id,
        task_id=task.id,
        block_id=block.block_id,
        session_id=payload.session_id,
        entered_at=entered,
        left_at=left,
    )
    db.add(row)
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("曝光写入失败：task=%s block=%s", task.id, block.block_id)
        raise _unavailable("曝光没记上（服务端写入失败）") from None
    db.refresh(row)

    # ⭐ 台账**一次会话只写一条**，不是每块一条：一次精读 80 块就会写 80 条事件，
    #    把 N17 台账（默认回 200 条）整个淹掉——那等于让"处理过程一屏"看不见别的事。
    #    第一块曝光时记一条"这次会话开始记曝光"，payload 带会话 id 与当时的块数。
    session_rows = db.scalar(
        select(func.count())
        .select_from(BlockExposure)
        .where(
            BlockExposure.user_id == user.id,
            BlockExposure.session_id == payload.session_id,
        )
    )
    if session_rows == 1:
        record_event(
            user_id=user.id,
            task_id=task.id,
            stage="exposure",
            actor="local",
            tool="exposure",
            summary=f"开始记录本次阅读的块曝光（会话 {payload.session_id[:8]}…）",
            payload={
                "session_id": payload.session_id,
                "first_block_id": block.block_id,
            },
        )
    return {"id": row.id, "created": True}
