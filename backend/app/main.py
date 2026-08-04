from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import BASE_DIR
from .db import Base, engine, get_db
from .models import Task


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


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "docwise-web", "version": "0.1.0"}


@app.get("/api/tasks")
def list_tasks(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Task).order_by(Task.id.desc()).limit(50)
    ).all()
    return [
        {
            "id": task.id,
            "filename": task.filename,
            "status": task.status,
            "progress": task.progress,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        }
        for task in rows
    ]
