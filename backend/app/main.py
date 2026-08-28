import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from .config import BASE_DIR, _to_env
from .db import Base, engine, get_db
from .engine import Tier
from .models import Task, TaskBlock
from .worker import TaskEventBus, TranslationWorker

UPLOAD_DIR = BASE_DIR / "data" / "uploads"


def _inject_engine_env() -> None:
    """把 .env 里的引擎/DeepSeek 配置注入环境，供 worker 子进程读取。

    不覆盖已显式设置的环境变量（$env: 优先级高于 .env）。
    """
    for key, value in _to_env().items():
        if value and not os.environ.get(key):
            os.environ[key] = value


def _ensure_schema() -> None:
    """为已存在的 SQLite 库补上新增列（create_all 只建表、不改表）。"""
    if not str(engine.url).startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "tasks" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("tasks")}
    additions = {
        "source_lang": "VARCHAR(16) DEFAULT 'en'",
        "target_lang": "VARCHAR(16) DEFAULT 'zh'",
        "tier": "VARCHAR(16) DEFAULT 'fast'",
        "translated_path": "VARCHAR(1024)",
    }
    with engine.begin() as conn:
        for column, ddl in additions.items():
            if column not in existing:
                conn.execute(text(f"ALTER TABLE tasks ADD COLUMN {column} {ddl}"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    (BASE_DIR / "data").mkdir(exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _ensure_schema()
    _inject_engine_env()
    # 每个应用生命周期新建独立 worker/事件总线，避免 asyncio.Queue 跨事件循环绑定。
    app.state.event_bus = TaskEventBus()
    app.state.worker = TranslationWorker(app.state.event_bus)
    await app.state.worker.start()
    yield
    await app.state.worker.stop()


app = FastAPI(title="docwise-web", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _status_value(status):
    return getattr(status, "value", status)


def _serialize_block(block: TaskBlock) -> dict:
    return {
        "block_id": block.block_id,
        "text": block.text,
        "status": _status_value(block.status),
        "translated": block.translated,
        "error": block.error,
    }


def _serialize_task(task: Task, blocks: list[TaskBlock] | None = None) -> dict:
    data = {
        "id": task.id,
        "filename": task.filename,
        "status": _status_value(task.status),
        "progress": task.progress,
        "tier": task.tier,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }
    if blocks is not None:
        data["error_message"] = task.error_message
        data["translated_path"] = task.translated_path
        data["blocks"] = [_serialize_block(block) for block in blocks]
    return data


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "docwise-web", "version": "0.1.0"}


@app.get("/api/tasks")
def list_tasks(db: Annotated[Session, Depends(get_db)]):
    rows = db.scalars(
        select(Task).order_by(Task.id.desc()).limit(50)
    ).all()
    return [_serialize_task(task) for task in rows]


@app.get("/api/tasks/{task_id}")
def get_task(task_id: int, db: Annotated[Session, Depends(get_db)]):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

    blocks = db.scalars(
        select(TaskBlock).where(TaskBlock.task_id == task.id).order_by(TaskBlock.id)
    ).all()
    return _serialize_task(task, blocks)


@app.get("/api/tasks/{task_id}/events")
async def task_events(
    task_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    """SSE 推送：实时进度；前端也可轮询 GET /api/tasks/{id} 兜底。"""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

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
            if initial_status in ("completed", "failed"):
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield _sse_event(event)
                if event.get("type") in ("completed", "failed"):
                    return
        except asyncio.CancelledError:
            pass
        finally:
            bus.unsubscribe(task_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


class TranslateRequestModel(BaseModel):
    """创建一次翻译任务的请求体（阶段 1 用本地文件路径驱动）。"""

    source_path: str
    source_lang: str = "en"
    target_lang: str = "zh"
    tier: str = "fast"


@app.post("/api/tasks/upload", status_code=202)
async def create_task_upload(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
    tier: str = Form("fast"),
    source_lang: str = Form("en"),
    target_lang: str = Form("zh"),
):
    """前端上传 PDF：保存文件后创建异步翻译任务，返回任务卡。"""
    filename = Path(file.filename or "upload.pdf").name
    if file.content_type != "application/pdf" and not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / f"{uuid4().hex}_{filename}"
    dest.write_bytes(await file.read())

    task = Task(
        filename=filename,
        original_path=str(dest),
        source_lang=source_lang,
        target_lang=target_lang,
        tier=Tier(tier).value,
        status="pending",
        progress=0.0,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    request.app.state.worker.enqueue(task.id)
    return _serialize_task(task)


@app.post("/api/tasks", status_code=202)
async def create_task(
    body: TranslateRequestModel,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    """建任务即返回（异步），后台 worker 处理，SSE/轮询看进度。"""
    source_path = Path(body.source_path)
    if not source_path.exists():
        raise HTTPException(status_code=400, detail="source_path 不存在")

    task = Task(
        filename=source_path.name,
        original_path=str(source_path),
        source_lang=body.source_lang,
        target_lang=body.target_lang,
        tier=Tier(body.tier).value,
        status="pending",
        progress=0.0,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    request.app.state.worker.enqueue(task.id)
    return _serialize_task(task)
