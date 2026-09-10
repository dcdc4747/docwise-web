"""保命基建的回归测试：真健康检查、WAL、worker 韧性、日志幂等。"""

from __future__ import annotations

import asyncio
import logging

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID

from app.db import SessionLocal, engine
from app.logging_setup import setup_logging
from app.main import app
from app.models import Task
from app.worker import TaskEventBus, TranslationWorker


def test_health_reports_real_checks() -> None:
    with TestClient(app) as client:
        res = client.get("/api/health")

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["checks"] == {"database": True, "worker": True}
    assert data["queue_size"] is not None
    assert data["worker_heartbeat_age"] is not None


def test_sqlite_wal_enabled() -> None:
    with engine.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()

    assert str(mode).lower() == "wal"


def test_setup_logging_is_idempotent() -> None:
    root = logging.getLogger()
    before = len(root.handlers)
    setup_logging()
    setup_logging()

    assert len(root.handlers) == before


def test_worker_loop_survives_task_exception(monkeypatch, caplog) -> None:
    """单任务异常不得杀死 worker 循环（此前会静默全站停摆且无日志）。"""
    with SessionLocal() as session:
        task = Task(user_id=TEST_USER_ID, filename="boom.pdf", status="pending")
        session.add(task)
        session.commit()
        task_id = task.id

    async def scenario() -> bool:
        worker = TranslationWorker(TaskEventBus())

        async def boom(_task_id: int) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(worker, "_process", boom)
        await worker.start()
        worker.enqueue(task_id)
        await asyncio.sleep(0.3)
        alive = worker.is_alive()
        await worker.stop()
        return alive

    with caplog.at_level(logging.ERROR):
        assert asyncio.run(scenario()) is True

    assert "任务处理异常" in caplog.text
    with SessionLocal() as session:
        assert session.get(Task, task_id).status == "failed"


def test_worker_exposes_runtime_state() -> None:
    worker = TranslationWorker(TaskEventBus())
    worker.enqueue(1)
    worker.enqueue(2)

    assert worker.queue_size == 2
    assert worker.heartbeat_age >= 0
    assert worker.is_alive() is False  # 未启动
