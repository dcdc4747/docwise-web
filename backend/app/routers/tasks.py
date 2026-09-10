"""任务路由（E 批从 main.py 拆出）。

包含：上传 / 列表 / 详情 / 文件 / 进度推送 / 理解层 / 删除·重试·取消。

约定（见 docs/代码架构图.md「关键观察」）：

- 所有"按任务"的接口都要 `load_owned_task` 校验归属，**非本人 404**；
- 浏览器发起的三种请求（EventSource / iframe 预览 / `<a download>`）带不了请求头，
  鉴权走 `get_user_for_files` / `get_user_for_events`（接受 `?ticket=`）；
- 任务终态有四个：completed / failed / cancelled / pending·in_progress（进行中）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .. import progress, storage
from ..deps import (
    get_current_user,
    get_db,
    get_user_for_events,
    get_user_for_files,
    load_owned_task,
)
from ..engine import TaskState, Tier
from ..llm import extract_understanding
from ..models import AuthTicket, Task, TaskBlock, TaskHistory, TaskUnderstanding, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# 终态：到了这里就没有"取消 / 重试"的余地了（failed/cancelled 可以重试）
TERMINAL_STATES = {
    TaskState.COMPLETED.value,
    TaskState.FAILED.value,
    TaskState.CANCELLED.value,
}
ACTIVE_STATES = {TaskState.PENDING.value, TaskState.IN_PROGRESS.value}
RETRYABLE_STATES = {TaskState.FAILED.value, TaskState.CANCELLED.value}


def _status_value(status) -> str:
    return getattr(status, "value", status)


def _serialize_block(block: TaskBlock) -> dict:
    return {
        "block_id": block.block_id,
        "text": block.text,
        "status": _status_value(block.status),
        "translated": block.translated,
        "error": block.error,
    }


def _task_files(task: Task) -> dict[str, bool]:
    """结果文件是否就绪（供前端一次取全，省掉额外的 HEAD 探测请求）。"""
    return {
        "mono": bool(task.translated_path and Path(task.translated_path).exists()),
        "dual": bool(
            task.dual_translated_path and Path(task.dual_translated_path).exists()
        ),
    }


def _elapsed_seconds(task: Task) -> float | None:
    """已耗时：从真正开跑算起；跑完就停在 finished_at（F 批"诚实进度"）。"""
    if task.started_at is None:
        return None
    end = task.finished_at or datetime.now()
    return max(0.0, (end - task.started_at).total_seconds())


def _queue_position(db: Session, task: Task) -> int | None:
    """排队中：前面还有几篇（正在跑的那篇也算在前面）。非排队返回 None。"""
    if _status_value(task.status) != TaskState.PENDING.value:
        return None
    ahead = db.scalar(
        select(func.count())
        .select_from(Task)
        .where(Task.status == TaskState.PENDING.value, Task.id < task.id)
    )
    running = db.scalar(
        select(func.count())
        .select_from(Task)
        .where(Task.status == TaskState.IN_PROGRESS.value)
    )
    return int(ahead or 0) + int(running or 0)


def _engine_progress(task: Task) -> dict | None:
    """引擎自报的进度（直接读 engine.log 尾部解析）。

    只有"正在跑"的任务才有意义；解析不出返回 None——前端据此显示
    "引擎还没报进度"，而不是编一个百分比。
    """
    if _status_value(task.status) != TaskState.IN_PROGRESS.value:
        return None
    log_path = storage.OUTPUTS_DIR / str(task.id) / "engine.log"
    parsed = progress.progress_from_log(log_path)
    if parsed is None:
        return None
    return {
        "done": parsed.done,
        "total": parsed.total,
        "percent": parsed.percent,
        "eta_seconds": parsed.eta_seconds,
        "rate": parsed.rate,
    }


def _serialize_task(task: Task, blocks: list[TaskBlock] | None = None) -> dict:
    data = {
        "id": task.id,
        "filename": task.filename,
        "status": _status_value(task.status),
        "progress": task.progress,
        "tier": task.tier,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        # 诚实进度：阶段 + 已耗时 + 引擎自报剩余（都不编造，没有就是 null）
        "stage": task.stage,
        "eta_seconds": task.eta_seconds,
        "elapsed_seconds": _elapsed_seconds(task),
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }
    if blocks is not None:
        data["error_message"] = task.error_message
        data["translated_path"] = task.translated_path
        data["dual_translated_path"] = task.dual_translated_path
        data["blocks"] = [_serialize_block(block) for block in blocks]
    return data


def _serialize_understanding(u: TaskUnderstanding | None) -> dict:
    if u is None:
        return {"status": "pending", "guide": None, "terms": [], "error": None}
    return {
        "status": u.status,
        "guide": json.loads(u.guide_json) if u.guide_json else None,
        "terms": json.loads(u.terms_json) if u.terms_json else [],
        "error": u.error,
    }


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _record_history(
    session: Session, task_id: int, action: str, detail: str | None = None
) -> None:
    session.add(TaskHistory(task_id=task_id, action=action, detail=detail))


def _purge_task_children(session: Session, task_id: int) -> None:
    """删任务前先删子表——**数据库外键没开级联**，不手工删会留一堆垃圾行。"""
    session.execute(delete(TaskBlock).where(TaskBlock.task_id == task_id))
    session.execute(delete(TaskHistory).where(TaskHistory.task_id == task_id))
    session.execute(
        delete(TaskUnderstanding).where(TaskUnderstanding.task_id == task_id)
    )
    session.execute(delete(AuthTicket).where(AuthTicket.task_id == task_id))


@router.get("")
def list_tasks(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """当前登录用户自己的任务（最多 50 条，新的在前）。"""
    rows = db.scalars(
        select(Task).where(Task.user_id == user.id).order_by(Task.id.desc()).limit(50)
    ).all()
    return [_serialize_task(task) for task in rows]


@router.get("/{task_id}")
def get_task(
    task_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """任务详情：块 + 结果文件就绪状态 + 导读/术语状态（供工作台一次取全）。"""
    task = load_owned_task(db, user, task_id)

    blocks = db.scalars(
        select(TaskBlock).where(TaskBlock.task_id == task.id).order_by(TaskBlock.id)
    ).all()
    data = _serialize_task(task, blocks)
    understanding = db.scalars(
        select(TaskUnderstanding).where(TaskUnderstanding.task_id == task.id)
    ).first()
    data["files_ready"] = _task_files(task)
    data["understanding_status"] = (
        understanding.status if understanding is not None else "pending"
    )
    # 诚实进度：排队位置 + 引擎自报的分页进度（都可能是 null，前端得认）
    data["queue_position"] = _queue_position(db, task)
    data["engine_progress"] = _engine_progress(task)
    return data


@router.delete("/{task_id}")
def delete_task(
    task_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """删除任务：先叫停正在跑的翻译，再删库（含子表）与磁盘产物。

    先删库后删文件：worker 停下来时发现任务已不存在，会顺手再清一次输出目录
    （子进程被 kill 的瞬间可能刚写了点东西）。
    """
    task = load_owned_task(db, user, task_id)
    worker = getattr(request.app.state, "worker", None)
    was_running = bool(worker is not None and worker.request_cancel(task_id))

    paths = {
        "original_path": task.original_path,
        "translated_path": task.translated_path,
        "dual_path": task.dual_translated_path,
    }
    filename = task.filename
    _purge_task_children(db, task_id)
    db.delete(task)
    db.commit()

    storage.remove_task_files(task_id, **paths)
    logger.info(
        "删除任务：task_id=%s filename=%s（运行中=%s）", task_id, filename, was_running
    )
    return {"deleted": task_id, "was_running": was_running}


@router.post("/{task_id}/retry")
def retry_task(
    task_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """重试失败/已取消的任务：清掉旧块与旧产物，重新排进队列（历史记录保留）。"""
    task = load_owned_task(db, user, task_id)
    status = _status_value(task.status)
    if status not in RETRYABLE_STATES:
        raise HTTPException(
            status_code=409,
            detail=f"任务当前状态是 {status}，只有失败或已取消的任务可以重试",
        )

    db.execute(delete(TaskBlock).where(TaskBlock.task_id == task_id))
    db.execute(delete(TaskUnderstanding).where(TaskUnderstanding.task_id == task_id))
    task.status = TaskState.PENDING.value
    task.progress = 0.0
    task.error_message = None
    task.translated_path = None
    task.dual_translated_path = None
    # 诚实进度：重排队等于回到"还没开跑"，计时与进度一起清干净
    task.stage = None
    task.eta_seconds = None
    task.started_at = None
    task.finished_at = None
    _record_history(db, task_id, "retry", "用户重试")
    db.commit()
    db.refresh(task)

    # 清掉上一轮的产物（要赶在 worker 重新落盘之前）
    storage.remove_dir(storage.OUTPUTS_DIR / str(task_id))
    logger.info("重试任务：task_id=%s", task_id)
    request.app.state.worker.enqueue(task.id)
    return _serialize_task(task)


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """取消任务：跑着的叫停子进程（worker 收尾落库），排队中的直接置为已取消。"""
    task = load_owned_task(db, user, task_id)
    status = _status_value(task.status)
    if status not in ACTIVE_STATES:
        raise HTTPException(
            status_code=409, detail=f"任务当前状态是 {status}，无法取消"
        )

    worker = getattr(request.app.state, "worker", None)
    if worker is not None and worker.request_cancel(task_id):
        # 正在跑：交给 worker 收尾（它会 terminate 子进程并发 cancelled 事件）
        return {"id": task_id, "status": "cancelling"}

    # 排队中：条件更新（只有还是 pending 才改），避免和 worker 认领打架
    result = db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == TaskState.PENDING.value)
        .values(
            status=TaskState.CANCELLED.value,
            progress=0.0,
            error_message="已取消",
            stage=None,
            eta_seconds=None,
            finished_at=datetime.now(),
        )
    )
    if result.rowcount == 0:
        # 刚好被 worker 认领了：再试一次叫停
        if worker is not None and worker.request_cancel(task_id):
            return {"id": task_id, "status": "cancelling"}
        raise HTTPException(status_code=409, detail="任务状态已变化，请刷新后重试")

    _record_history(db, task_id, TaskState.CANCELLED.value, "用户取消（排队中）")
    db.commit()
    if worker is not None:
        await worker.bus.publish(
            task_id,
            {
                "type": TaskState.CANCELLED.value,
                "status": TaskState.CANCELLED.value,
                "progress": 0.0,
                "error": "已取消",
            },
        )
    logger.info("取消排队中的任务：task_id=%s", task_id)
    return {"id": task_id, "status": TaskState.CANCELLED.value}


@router.api_route("/{task_id}/files/{kind}", methods=["GET", "HEAD"])
def get_task_file(
    task_id: int,
    kind: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_user_for_files)],
    download: bool = False,
):
    """返回结果文件（mono 纯中文 / dual 双语 PDF）供预览与下载。

    鉴权：Bearer，或 `?ticket=`（浏览器发起的 iframe/下载带不了请求头）。
    """
    task = load_owned_task(db, user, task_id)
    if kind not in ("mono", "dual"):
        raise HTTPException(status_code=400, detail="未知文件类型")

    raw = task.translated_path if kind == "mono" else task.dual_translated_path
    path = Path(raw) if raw else None
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="结果文件不存在")

    if download:
        stem = Path(task.filename).stem or "result"
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=f"{stem}_{kind}.pdf",
        )
    return FileResponse(path, media_type="application/pdf")


@router.get("/{task_id}/events")
async def task_events(
    task_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_user_for_events)],
):
    """SSE 推送：实时进度；前端也可轮询 GET /api/tasks/{id} 兜底。

    鉴权：Bearer，或 `?ticket=`（EventSource 带不了请求头）。
    """
    task = load_owned_task(db, user, task_id)

    initial_status = _status_value(task.status)
    initial_progress = task.progress or 0.0
    initial_error = task.error_message
    bus = request.app.state.event_bus
    queue = bus.subscribe(task_id)

    async def stream():
        try:
            yield _sse_event(
                {
                    "type": initial_status,
                    "status": initial_status,
                    "progress": initial_progress,
                    "error": initial_error,
                }
            )
            if initial_status in TERMINAL_STATES:
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield _sse_event(event)
                if event.get("type") in TERMINAL_STATES:
                    return
        except asyncio.CancelledError:
            pass
        finally:
            bus.unsubscribe(task_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/upload", status_code=202)
async def create_task_upload(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    file: UploadFile = File(...),
    tier: str = Form("fast"),
    source_lang: str = Form("en"),
    target_lang: str = Form("zh"),
):
    """前端上传 PDF：保存文件后创建异步翻译任务（归属当前登录用户），返回任务卡。"""
    filename = Path(file.filename or "upload.pdf").name
    if file.content_type != "application/pdf" and not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")
    try:
        tier_value = Tier(tier).value
    except ValueError:
        raise HTTPException(status_code=400, detail=f"未知档位：{tier}") from None

    upload_dir = storage.uploads_dir()
    dest = upload_dir / f"{uuid4().hex}_{filename}"
    dest.write_bytes(await file.read())

    task = Task(
        user_id=user.id,
        filename=filename,
        original_path=str(dest),
        source_lang=source_lang,
        target_lang=target_lang,
        tier=tier_value,
        status=TaskState.PENDING.value,
        progress=0.0,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    logger.info("收到上传：%s（%s，task_id=%s）", filename, tier_value, task.id)
    request.app.state.worker.enqueue(task.id)
    return _serialize_task(task)


@router.get("/{task_id}/understanding")
def get_understanding(
    task_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """返回导读/术语表状态（惰性按需生成；未生成返回 pending）。"""
    load_owned_task(db, user, task_id)
    u = db.scalars(
        select(TaskUnderstanding).where(TaskUnderstanding.task_id == task_id)
    ).first()
    return _serialize_understanding(u)


@router.post("/{task_id}/understanding", status_code=200)
def compute_understanding(
    task_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """惰性生成导读/术语表：先取；未生成/失败则调用 LLM 抽取并缓存。幂等。"""
    load_owned_task(db, user, task_id)

    u = db.scalars(
        select(TaskUnderstanding).where(TaskUnderstanding.task_id == task_id)
    ).first()
    if u is not None and u.status == "ready":
        return _serialize_understanding(u)

    blocks = db.scalars(
        select(TaskBlock).where(TaskBlock.task_id == task_id).order_by(TaskBlock.id)
    ).all()
    items = [
        (b.block_id, b.translated or b.text)
        for b in blocks
        if (b.translated or b.text)
    ]
    if not items:
        raise HTTPException(status_code=400, detail="该任务没有可提炼的文本")

    if u is None:
        u = TaskUnderstanding(task_id=task_id)
        db.add(u)
    u.status = "pending"
    u.error = None
    db.commit()

    try:
        result = extract_understanding(items)
        u.guide_json = json.dumps(
            {
                k: result.get(k)
                for k in (
                    "research_question",
                    "method",
                    "conclusion",
                    "innovation",
                    "contribution",
                )
            },
            ensure_ascii=False,
        )
        u.terms_json = json.dumps(result.get("terms", []), ensure_ascii=False)
        u.status = "ready"
        u.error = None
    except Exception as exc:  # noqa: BLE001 - 失败降级为"暂无导读"，不影响主任务
        u.guide_json = None
        u.terms_json = None
        u.status = "failed"
        u.error = str(exc)
    db.commit()
    return _serialize_understanding(u)
