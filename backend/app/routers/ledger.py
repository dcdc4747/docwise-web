"""台账接口（契约 §2.5 的 N15–N17，共 4 条路由）。

- `POST /api/ask-logs`（N15）/ `GET /api/ask-logs`（N16）：问答落库与回看。
  ⚠️ 服务端在回答问题时就**已经**写了一条（`routers/ask.py` →
  `ledger.record_ask`），所以 N15 这个 POST 是给**外部补齐/重放**用的；
  **前端不该手工拼**（契约原话）。
- `GET /api/memory-events`（N17）：台账读取（前端只调这个）。
- `POST /api/memory-events`（N17）：**只给服务端内部用**——写入方是服务端各环节
  （取字 / 翻译 / OCR / 导读 / 问答），契约明写前端不该手工埋点。

口径（照契约，别自己发明）：

- **归属**：一律只认当前账号；带了 `task_id` 就先校验那篇是自己的，**非本人 404**。
- **"写了"不许有假象**：写入失败（台账表写不进去）→ **503 + 人话**，
  不返回一个编出来的 id。
  ⚠️ 这只针对"目的就是写"的这两个 POST；业务链路里的台账写入是**容错**的
  （见 `app/ledger.py` 的口径 1），失败也不影响用户的操作。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db, load_owned_task
from ..ledger import ask_logs, event_view, record_ask, record_event
from ..models import MemoryEvent, User

router = APIRouter(tags=["ledger"])

# 台账读取的默认与上限（契约只写了 `?limit?`，没写默认值——
# 这里定死，并在文档串里说明，别让调用方猜）
_LIMIT_DEFAULT = 200
_LIMIT_MAX = 1000
# 问答台账一次最多回多少条（没有分页参数，先给一个诚实的上限，别让一次读把库拖住）
_ASK_LOGS_MAX = 500


class AskLogIn(BaseModel):
    """N15 请求体（契约 §2.5：
    `{task_id, question, answer, source_block_ids: string[]}`）。"""

    task_id: int | None = None
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(default="", max_length=20000)
    source_block_ids: list[str] = Field(default_factory=list)


class MemoryEventIn(BaseModel):
    """N17 写入体（`stage`/`actor`/`summary` 必填，其余可省）。"""

    stage: str = Field(min_length=1, max_length=32)
    actor: str = Field(min_length=1, max_length=16)
    summary: str = Field(min_length=1, max_length=500)
    task_id: int | None = None
    layer: str = Field(default="L0", max_length=8)
    tool: str | None = Field(default=None, max_length=64)
    payload: dict | None = None


def _clamp_limit(limit: int | None) -> int:
    """`?limit?` 越界就夹到 [1, 上限]（契约没规定越界怎么办：
    **不报错、也不静默变 0**）。"""
    if limit is None:
        return _LIMIT_DEFAULT
    return max(1, min(int(limit), _LIMIT_MAX))


def _rows(
    db: Session,
    user: User,
    *,
    task_id: int | None,
    layer: str | None,
    limit: int,
    stage: str | None = None,
) -> list[MemoryEvent]:
    """当前账号的台账行（新的在前；`id` 兜同秒顺序，保证稳定）。"""
    stmt = select(MemoryEvent).where(MemoryEvent.user_id == user.id)
    if task_id is not None:
        stmt = stmt.where(MemoryEvent.task_id == task_id)
    if layer:
        stmt = stmt.where(MemoryEvent.layer == layer)
    if stage:
        stmt = stmt.where(MemoryEvent.stage == stage)
    stmt = stmt.order_by(MemoryEvent.created_at.desc(), MemoryEvent.id.desc())
    return list(db.scalars(stmt.limit(limit)).all())


def _guard_task(db: Session, user: User, task_id: int | None) -> None:
    """带了 `task_id` 就必须是自己的那篇（非本人 404，不暴露"存在但无权限"）。"""
    if task_id is not None:
        load_owned_task(db, user, task_id)


def _unavailable(detail: str) -> HTTPException:
    """503 + 人话：写不进去就如实说，**不假装成功**。"""
    return HTTPException(status_code=503, detail=detail)


@router.post("/api/ask-logs", status_code=201)
def create_ask_log(
    payload: AskLogIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N15 问答落库 → `201 {id}`（契约就是这个形状）。"""
    _guard_task(db, user, payload.task_id)
    row_id = record_ask(
        user_id=user.id,
        task_id=payload.task_id,
        question=payload.question,
        answer=payload.answer,
        source_block_ids=payload.source_block_ids,
    )
    if row_id is None:
        raise _unavailable("台账没写进去（服务端写入失败），这条问答没有被记录")
    return {"id": row_id}


@router.get("/api/ask-logs")
def list_ask_logs(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    task_id: Annotated[int | None, Query()] = None,
):
    """N16 问答台账 → `200 {items}`（`?task_id?` 只看某一篇）。"""
    _guard_task(db, user, task_id)
    rows = _rows(
        db, user, task_id=task_id, layer=None, limit=_ASK_LOGS_MAX, stage="ask"
    )
    return {"items": ask_logs(rows)}


@router.get("/api/memory-events")
def list_memory_events(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    task_id: Annotated[int | None, Query()] = None,
    layer: Annotated[str | None, Query()] = None,
    limit: Annotated[int | None, Query()] = None,
):
    """N17 台账读取 → `200 {items}`（默认 200 条、上限 1000 条）。"""
    _guard_task(db, user, task_id)
    rows = _rows(db, user, task_id=task_id, layer=layer, limit=_clamp_limit(limit))
    return {"items": [event_view(row) for row in rows]}


@router.post("/api/memory-events", status_code=201)
def create_memory_event(
    payload: MemoryEventIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N17 服务端内部埋点 → `201 {id}`。

    ⚠️ 前端**不该**调它（契约 §2.5 原话："POST 由服务端在关键环节写"）。
    """
    _guard_task(db, user, payload.task_id)
    row_id = record_event(
        user_id=user.id,
        task_id=payload.task_id,
        layer=payload.layer,
        stage=payload.stage,
        actor=payload.actor,
        tool=payload.tool,
        summary=payload.summary,
        payload=payload.payload,
    )
    if row_id is None:
        raise _unavailable("台账没写进去（服务端写入失败），这条事件没有被记录")
    return {"id": row_id}
