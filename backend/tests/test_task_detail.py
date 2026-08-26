from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.engine import BlockState
from app.main import app
from app.models import Task, TaskBlock


def test_task_detail_returns_blocks() -> None:
    with SessionLocal() as session:
        task = Task(filename="a.pdf", status="in_progress")
        session.add(task)
        session.flush()
        session.add(
            TaskBlock(
                task_id=task.id, block_id="b1", text="hello",
                status=BlockState.SUCCESS, translated="你好",
            )
        )
        session.add(
            TaskBlock(
                task_id=task.id, block_id="b2", text="world",
                status=BlockState.FAILED, error="boom",
            )
        )
        session.commit()
        task_id = task.id

    with TestClient(app) as client:
        res = client.get(f"/api/tasks/{task_id}")

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "in_progress"
    assert len(data["blocks"]) == 2
    assert data["blocks"][0]["status"] == "success"
    assert data["blocks"][0]["translated"] == "你好"
    assert data["blocks"][1]["status"] == "failed"
    assert data["blocks"][1]["error"] == "boom"


def test_task_detail_404() -> None:
    with TestClient(app) as client:
        res = client.get("/api/tasks/9999")

    assert res.status_code == 404
