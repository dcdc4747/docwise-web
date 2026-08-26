from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import BASE_DIR
from .db import Base, engine, get_db
from .engine import Tier, TranslateRequest, get_engine
from .models import Task, TaskBlock


@asynccontextmanager
async def lifespan(_: FastAPI):
    (BASE_DIR / "data").mkdir(exist_ok=True)
    Base.metadata.create_all(bind=engine)
    yield


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
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }
    if blocks is not None:
        data["error_message"] = task.error_message
        data["blocks"] = [_serialize_block(block) for block in blocks]
    return data


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


class TranslateRequestModel(BaseModel):
    """创建并执行一次翻译任务的请求体（阶段 1 用本地文件路径驱动）。"""

    source_path: str
    source_lang: str = "en"
    target_lang: str = "zh"
    tier: str = "fast"


def _run_translation(db: Session, body: TranslateRequestModel) -> Task:
    source_path = Path(body.source_path)
    if not source_path.exists():
        raise HTTPException(status_code=400, detail="source_path 不存在")

    task = Task(
        filename=source_path.name,
        original_path=str(source_path),
        status="in_progress",
        progress=0.0,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    try:
        engine = get_engine("pdf2zh")
        result = engine.translate(
            TranslateRequest(
                source_path=source_path,
                source_lang=body.source_lang,
                target_lang=body.target_lang,
                tier=Tier(body.tier),
            )
        )
        for block in result.blocks:
            db.add(
                TaskBlock(
                    task_id=task.id,
                    block_id=block.block_id,
                    text=block.text,
                    status=block.status,
                    translated=block.translated,
                    error=block.error,
                )
            )
        task.status = _status_value(result.status)
        task.progress = result.progress
        task.error_message = result.error
        db.commit()
    except Exception as exc:  # noqa: BLE001 - 把失败如实落库并回传
        task.status = "failed"
        task.error_message = str(exc)
        db.commit()
        raise

    return task


@app.post("/api/tasks", status_code=201)
def create_task(
    body: TranslateRequestModel, db: Annotated[Session, Depends(get_db)]
):
    task = _run_translation(db, body)
    blocks = db.scalars(
        select(TaskBlock).where(TaskBlock.task_id == task.id).order_by(TaskBlock.id)
    ).all()
    return _serialize_task(task, blocks)
