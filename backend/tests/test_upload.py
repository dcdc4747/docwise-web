from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.engine import BlockState, BlockStatus, TaskState, TranslationResult
from app.main import app


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


def test_upload_pdf_creates_task_and_completes(monkeypatch) -> None:
    _patch_engine(monkeypatch)
    with TestClient(app) as client:
        resp = client.post(
            "/api/tasks/upload",
            files={"file": ("sample.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"tier": "fast"},
        )
        assert resp.status_code == 202
        task = resp.json()
        assert task["id"] > 0
        assert task["filename"] == "sample.pdf"
        assert task["tier"] == "fast"

        status = _wait_terminal(client, task["id"])
        detail = client.get(f"/api/tasks/{task['id']}").json()
    assert status == "completed"
    assert detail["progress"] == 1.0
    assert detail["blocks"][0]["translated"] == "你好"


def test_upload_passes_tier(monkeypatch) -> None:
    _patch_engine(monkeypatch)
    with TestClient(app) as client:
        resp = client.post(
            "/api/tasks/upload",
            files={"file": ("sample.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"tier": "medium"},
        )
        assert resp.status_code == 202
        assert resp.json()["tier"] == "medium"


def test_upload_rejects_non_pdf(monkeypatch) -> None:
    _patch_engine(monkeypatch)
    with TestClient(app) as client:
        resp = client.post(
            "/api/tasks/upload",
            files={"file": ("note.txt", b"hello", "text/plain")},
            data={"tier": "fast"},
        )
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]
