from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.engine import BlockState
from app.main import app
from app.models import Task, TaskBlock

FAKE = {
    "research_question": {"text": "RQ", "source_block_ids": ["b1"]},
    "method": {"text": "M", "source_block_ids": ["b1"]},
    "conclusion": {"text": "C", "source_block_ids": ["b1"]},
    "innovation": {"text": "I", "source_block_ids": ["b1"]},
    "contribution": {"text": "CT", "source_block_ids": ["b1"]},
    "terms": [{"term": "t", "cn": "cn", "definition": "d"}],
}


def _make_completed_task_with_block() -> int:
    with SessionLocal() as session:
        task = Task(filename="a.pdf", status="completed")
        session.add(task)
        session.flush()
        session.add(
            TaskBlock(
                task_id=task.id,
                block_id="b1",
                text="hi",
                status=BlockState.SUCCESS,
                translated="你好",
            )
        )
        session.commit()
        return task.id


def test_compute_understanding_ready(monkeypatch) -> None:
    monkeypatch.setattr("app.main.extract_understanding", lambda items: FAKE)
    with TestClient(app) as client:
        task_id = _make_completed_task_with_block()
        res = client.post(f"/api/tasks/{task_id}/understanding")

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ready"
    assert data["guide"]["research_question"]["text"] == "RQ"
    assert data["guide"]["research_question"]["source_block_ids"] == ["b1"]
    assert data["terms"][0]["term"] == "t"


def test_compute_understanding_idempotent(monkeypatch) -> None:
    calls: list = []

    def fake(items) -> dict:
        calls.append(items)
        return FAKE

    monkeypatch.setattr("app.main.extract_understanding", fake)
    with TestClient(app) as client:
        task_id = _make_completed_task_with_block()
        client.post(f"/api/tasks/{task_id}/understanding")
        client.post(f"/api/tasks/{task_id}/understanding")

    assert len(calls) == 1  # 第二次命中缓存，不再调 LLM


def test_compute_understanding_failed_degrades(monkeypatch) -> None:
    def boom(items) -> dict:
        raise RuntimeError("llm down")

    monkeypatch.setattr("app.main.extract_understanding", boom)
    with TestClient(app) as client:
        task_id = _make_completed_task_with_block()
        res = client.post(f"/api/tasks/{task_id}/understanding")

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "failed"
    assert "llm down" in (data["error"] or "")
    assert data["guide"] is None


def test_get_understanding_pending_before_compute(monkeypatch) -> None:
    monkeypatch.setattr("app.main.extract_understanding", lambda items: FAKE)
    with TestClient(app) as client:
        with SessionLocal() as session:
            task = Task(filename="a.pdf", status="completed")
            session.add(task)
            session.commit()
            task_id = task.id
        res = client.get(f"/api/tasks/{task_id}/understanding")

    assert res.status_code == 200
    assert res.json()["status"] == "pending"


def test_compute_understanding_404() -> None:
    with TestClient(app) as client:
        res = client.post("/api/tasks/9999/understanding")

    assert res.status_code == 404
