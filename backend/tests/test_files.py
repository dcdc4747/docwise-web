from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.engine import TaskState, TranslationResult
from app.main import app


def _pdf_bytes() -> bytes:
    return b"%PDF-1.4 fake docwise"


class ResultEngine:
    """测试用引擎：返回指向真实临时文件的 mono/dual 结果。"""

    name = "result-engine"

    def __init__(self, mono: Path, dual: Path) -> None:
        self.mono = mono
        self.dual = dual

    def translate(self, request) -> TranslationResult:
        _ = request
        return TranslationResult(
            task_id="res",
            translated_path=self.mono,
            dual_path=self.dual,
            status=TaskState.COMPLETED,
            progress=1.0,
        )


def _patch_engine(monkeypatch, engine) -> None:
    monkeypatch.setattr("app.worker.get_engine", lambda tier=None: engine)


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


def _create_completed_task(
    client: TestClient, monkeypatch, tmp_path
) -> tuple[int, Path, Path]:
    mono = tmp_path / "mono.pdf"
    dual = tmp_path / "dual.pdf"
    mono.write_bytes(_pdf_bytes())
    dual.write_bytes(_pdf_bytes())
    _patch_engine(monkeypatch, ResultEngine(mono, dual))
    resp = client.post(
        "/api/tasks/upload",
        files={"file": ("sample.pdf", _pdf_bytes(), "application/pdf")},
    )
    task_id = resp.json()["id"]
    _wait_terminal(client, task_id)
    return task_id, mono, dual


def test_get_task_file_mono_and_dual(monkeypatch, tmp_path) -> None:
    with TestClient(app) as client:
        task_id, mono, dual = _create_completed_task(client, monkeypatch, tmp_path)
        mono_resp = client.get(f"/api/tasks/{task_id}/files/mono")
        dual_resp = client.get(f"/api/tasks/{task_id}/files/dual")
    assert mono_resp.status_code == 200
    assert mono_resp.headers["content-type"].startswith("application/pdf")
    assert mono_resp.content == mono.read_bytes()
    assert dual_resp.status_code == 200
    assert dual_resp.content == dual.read_bytes()


def test_get_task_file_download_attachment(monkeypatch, tmp_path) -> None:
    with TestClient(app) as client:
        task_id, _, _ = _create_completed_task(client, monkeypatch, tmp_path)
        resp = client.get(f"/api/tasks/{task_id}/files/mono", params={"download": "1"})
    assert resp.status_code == 200
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition
    assert "sample_mono.pdf" in disposition


def test_get_task_file_unknown_kind(monkeypatch, tmp_path) -> None:
    with TestClient(app) as client:
        task_id, _, _ = _create_completed_task(client, monkeypatch, tmp_path)
        resp = client.get(f"/api/tasks/{task_id}/files/unknown")
    assert resp.status_code == 400


def test_get_task_file_missing_task() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/tasks/999999/files/mono")
    assert resp.status_code == 404


def test_get_task_file_missing_file(monkeypatch, tmp_path) -> None:
    _patch_engine(
        monkeypatch,
        ResultEngine(tmp_path / "missing.pdf", tmp_path / "d.pdf"),
    )
    with TestClient(app) as client:
        resp = client.post(
            "/api/tasks/upload",
            files={"file": ("sample.pdf", _pdf_bytes(), "application/pdf")},
        )
        task_id = resp.json()["id"]
        _wait_terminal(client, task_id)
        file_resp = client.get(f"/api/tasks/{task_id}/files/mono")
    assert file_resp.status_code == 404
