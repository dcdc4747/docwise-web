from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import BASE_DIR
from .db import Base, engine, get_db
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
