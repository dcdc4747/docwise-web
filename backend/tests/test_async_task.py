from __future__ import annotations

import json
import tempfile
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.engine import BlockState, BlockStatus, TaskState, Tier, TranslationResult
from app.main import app
from app.models import Task


@pytest.fixture
def sample_pdf():
    """在沙箱可写的 tempdir 根目录建一个假 PDF（避免子目录/子进程目录被拒）。"""
    path = Path(tempfile.gettempdir()) / f"docwise_sample_{uuid.uuid4().hex}.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


class FakeEngine:
    """测试用引擎：立即返回完成的译文结果（避免真实子进程依赖）。"""

    name = "open-source"

    def translate(self, request) -> TranslationResult:
        _ = request
        return TranslationResult(
            task_id="fake",
            translated_path=Path("/tmp/out.pdf"),
            blocks=[
                BlockStatus(
                    block_id="b1", text="hello",
                    status=BlockState.SUCCESS, translated="你好",
                )
            ],
            status=TaskState.COMPLETED,
            progress=1.0,
            error=None,
        )


def _patch_engine(monkeypatch, engine=FakeEngine()) -> None:
    monkeypatch.setattr("app.worker.get_engine", lambda name="open-source": engine)


def _wait_terminal(client: TestClient, task_id: int, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200
        status = resp.json()["status"]
        if status in (TaskState.COMPLETED.value, TaskState.FAILED.value):
            return status
        time.sleep(0.05)
    raise AssertionError("任务未在限定时间内达到终态")


def test_create_task_returns_immediately(sample_pdf, monkeypatch) -> None:
    _patch_engine(monkeypatch)
    src = sample_pdf
    with TestClient(app) as client:
        resp = client.post("/api/tasks", json={"source_path": str(src)})
    # 立即返回，不阻塞：202 + id + 状态（待处理或进行中）
    assert resp.status_code == 202
    data = resp.json()
    assert data["id"] > 0
    assert data["status"] in ("pending", "in_progress")


def test_task_runs_to_completion_and_stores_blocks(sample_pdf, monkeypatch) -> None:
    _patch_engine(monkeypatch)
    src = sample_pdf
    with TestClient(app) as client:
        task_id = client.post(
            "/api/tasks", json={"source_path": str(src)}
        ).json()["id"]
        status = _wait_terminal(client, task_id)
        detail = client.get(f"/api/tasks/{task_id}").json()
    assert status == "completed"
    assert detail["progress"] == 1.0
    assert len(detail["blocks"]) == 1
    assert detail["blocks"][0]["status"] == "success"
    assert detail["blocks"][0]["translated"] == "你好"


def test_worker_routes_tier_to_engine(sample_pdf, monkeypatch) -> None:
    requested_tiers: list[Tier] = []

    class RecorderEngine:
        name = "recorder"

        def translate(self, request) -> TranslationResult:
            return TranslationResult(
                task_id="rec",
                translated_path=Path("/tmp/out.pdf"),
                status=TaskState.COMPLETED,
                progress=1.0,
            )

    def fake_get_engine(tier=Tier.FAST):
        requested_tiers.append(tier)
        return RecorderEngine()

    monkeypatch.setattr("app.worker.get_engine", fake_get_engine)
    src = sample_pdf
    with TestClient(app) as client:
        task_id = client.post(
            "/api/tasks",
            json={"source_path": str(src), "tier": "medium"},
        ).json()["id"]
        status = _wait_terminal(client, task_id)
    assert status == "completed"
    assert requested_tiers and requested_tiers[-1] == Tier.MEDIUM


def test_interrupted_task_recovered_on_startup(sample_pdf, monkeypatch) -> None:
    _patch_engine(monkeypatch)
    # 模拟崩溃前留下的 in_progress 任务（无子进程真实产物）
    with SessionLocal() as session:
        task = Task(
            filename="b.pdf",
            original_path=str(sample_pdf),
            status=TaskState.IN_PROGRESS.value,
        )
        session.add(task)
        session.commit()
        task_id = task.id

    with TestClient(app) as client:
        # worker 启动时把 in_progress 拉回 pending 并重新处理，最终到 completed
        status = _wait_terminal(client, task_id)
    assert status == "completed"


def _read_sse_events(response) -> list[dict]:
    events: list[dict] = []
    for raw in response.iter_lines():
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        if line.startswith("data:"):
            payload = json.loads(line[len("data:"):].strip())
            events.append(payload)
            if payload.get("type") in (
                TaskState.COMPLETED.value,
                TaskState.FAILED.value,
            ):
                break
    return events


def test_sse_streams_progress(sample_pdf, monkeypatch) -> None:
    _patch_engine(monkeypatch)
    src = sample_pdf
    with TestClient(app) as client:
        task_id = client.post(
            "/api/tasks", json={"source_path": str(src)}
        ).json()["id"]
        with client.stream("GET", f"/api/tasks/{task_id}/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            events = _read_sse_events(response)
    assert events, "SSE 未推送到任何事件"
    assert events[-1]["type"] == "completed"
