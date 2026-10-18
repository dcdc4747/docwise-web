"""E 批：任务生命周期（删除 / 重试 / 取消）与磁盘治理。

覆盖点：
- 删除任务：库里的子表（块/历史/理解/票据）与磁盘产物一起清掉，FTS 索引不留残渣；
- 归属：别人的任务删不掉（404，不是 403）；
- 取消：跑着的叫停子进程（worker 收尾落库为 cancelled）、排队中的直接置终态；
- 重试：失败任务清旧块与旧产物后重新排队（历史保留）；
- storage：只删自己地盘里的文件、孤儿目录才会被回收。
"""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID
from sqlalchemy import select

from app import storage
from app.db import SessionLocal
from app.engine import BlockState, BlockStatus, TaskState, TranslationResult
from app.main import app
from app.models import Task, TaskBlock, TaskHistory, TaskUnderstanding

PDF_BYTES = b"%PDF-1.4 fake"


class CompletedEngine:
    """立刻返回成功结果（避免真实子进程）。"""

    name = "completed-engine"

    def translate(self, request, cancel=None) -> TranslationResult:
        _ = cancel
        return TranslationResult(
            task_id="fake",
            translated_path=None,
            blocks=[
                BlockStatus(
                    block_id="b1",
                    text="hello",
                    status=BlockState.SUCCESS,
                    translated="你好",
                )
            ],
            status=TaskState.COMPLETED,
            progress=1.0,
        )


class BlockingEngine:
    """卡住不返回，直到收到取消信号——用来测"取消正在跑的翻译"。"""

    name = "blocking-engine"

    def __init__(self) -> None:
        self.started = threading.Event()

    def translate(self, request, cancel=None) -> TranslationResult:
        self.started.set()
        if cancel is not None:
            cancel.wait(10.0)
            if cancel.cancelled:
                return TranslationResult(
                    task_id="block",
                    translated_path=None,
                    blocks=[],
                    status=TaskState.CANCELLED,
                    progress=0.0,
                    error="已取消",
                )
        return TranslationResult(
            task_id="block",
            translated_path=None,
            blocks=[],
            status=TaskState.COMPLETED,
            progress=1.0,
        )


def _patch_engine(monkeypatch, engine) -> None:
    monkeypatch.setattr("app.worker.get_engine", lambda *a, **kw: engine)


def _upload(client: TestClient, name: str = "sample.pdf") -> dict:
    resp = client.post(
        "/api/tasks/upload",
        files={"file": (name, PDF_BYTES, "application/pdf")},
        data={"tier": "fast"},
    )
    assert resp.status_code == 202, resp.text
    return resp.json()


def _wait_status(
    client: TestClient, task_id: int, expected: str, timeout: float = 8.0
) -> str:
    deadline = time.monotonic() + timeout
    status = ""
    while time.monotonic() < deadline:
        resp = client.get(f"/api/tasks/{task_id}")
        if resp.status_code == 404:
            return "deleted"
        status = resp.json()["status"]
        if status == expected:
            return status
        time.sleep(0.05)
    raise AssertionError(f"任务未在 {timeout}s 内变成 {expected}（当前 {status}）")


def _make_task(status: str, filename: str = "old.pdf", **kwargs) -> int:
    """直接入库建任务（已带归属，避免走上传触发 worker）。"""
    with SessionLocal() as session:
        task = Task(
            user_id=kwargs.pop("user_id", TEST_USER_ID),
            filename=filename,
            tier="fast",
            status=status,
            progress=0.0,
            **kwargs,
        )
        session.add(task)
        session.commit()
        return task.id


def test_delete_moves_to_trash_and_purge_really_removes(monkeypatch) -> None:
    """⭐ 删除＝进回收站（行/子表/文件都留着）；**彻底删除**才真删。"""
    _patch_engine(monkeypatch, CompletedEngine())
    with TestClient(app) as client:
        task = _upload(client, "to-delete.pdf")
        task_id = task["id"]
        _wait_status(client, task_id, TaskState.COMPLETED.value)

        with SessionLocal() as session:
            stored = session.get(Task, task_id)
            upload_path = Path(stored.original_path)
        storage.outputs_dir(task_id).joinpath("mono.pdf").write_bytes(PDF_BYTES)
        # 软删前后要能对比：先记下每张子表有几行
        with SessionLocal() as session:
            counts_before = {
                model.__tablename__: len(
                    session.scalars(
                        select(model).where(model.task_id == task_id)
                    ).all()
                )
                for model in (TaskBlock, TaskHistory, TaskUnderstanding)
            }

        # ① 删除 → 进回收站
        resp = client.delete(f"/api/tasks/{task_id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["deleted"] == task_id
        assert resp.json()["restorable"] is True

        # 库里还在、子表**一条都没少**、文件还在
        with SessionLocal() as session:
            row = session.get(Task, task_id)
            assert row is not None and row.deleted_at is not None
            for model in (TaskBlock, TaskHistory, TaskUnderstanding):
                rows_now = session.scalars(
                    select(model).where(model.task_id == task_id)
                ).all()
                assert len(rows_now) == counts_before[model.__tablename__], (
                    f"{model.__tablename__} 在软删时被清掉了"
                )
        assert upload_path.exists(), "软删不该动文件"

        # 正常列表不显示，回收站显示
        assert all(item["id"] != task_id for item in client.get("/api/tasks").json())
        trashed = client.get("/api/tasks?trashed=1").json()
        assert any(item["id"] == task_id for item in trashed)
        assert trashed[0]["deleted_at"].endswith("+00:00")

        # ② 恢复 → 回到正常列表
        restored = client.post(f"/api/tasks/{task_id}/restore").json()
        assert restored["was_trashed"] is True
        assert any(item["id"] == task_id for item in client.get("/api/tasks").json())

        # ③ 再删一次，然后彻底删除
        client.delete(f"/api/tasks/{task_id}")
        purged = client.delete(f"/api/tasks/{task_id}/purge")
        assert purged.status_code == 200, purged.text
        assert purged.json()["irreversible"] is True

        with SessionLocal() as session:
            assert session.get(Task, task_id) is None
            for model in (TaskBlock, TaskHistory, TaskUnderstanding):
                left = session.scalars(
                    select(model).where(model.task_id == task_id)
                ).all()
                assert left == [], f"{model.__tablename__} 里还有残留"
        assert not upload_path.exists()
        assert client.get(f"/api/tasks/{task_id}").status_code == 404


def test_purge_requires_trash_first() -> None:
    """⭐ 彻底删除必须先"移入回收站"，否则 400（防绕过两步确认）。"""
    task_id = _make_task("completed", original_path=str(storage.UPLOADS_DIR / "x.pdf"))
    with TestClient(app) as client:
        resp = client.delete(f"/api/tasks/{task_id}/purge")
        assert resp.status_code == 400
        assert "回收站" in resp.json()["detail"]
        # 任务还在
        assert client.get(f"/api/tasks/{task_id}").status_code == 200


def test_restore_is_idempotent() -> None:
    """恢复一个不在回收站里的任务也算成功（幂等，不报错）。"""
    task_id = _make_task("completed", original_path=str(storage.UPLOADS_DIR / "y.pdf"))
    with TestClient(app) as client:
        body = client.post(f"/api/tasks/{task_id}/restore").json()
        assert body["was_trashed"] is False


def test_delete_running_task_cancels_first(monkeypatch) -> None:
    engine = BlockingEngine()
    _patch_engine(monkeypatch, engine)
    with TestClient(app) as client:
        task_id = _upload(client, "running.pdf")["id"]
        assert engine.started.wait(5.0), "引擎没有被拉起"

        resp = client.delete(f"/api/tasks/{task_id}")
        assert resp.status_code == 200, resp.text
        # 运行中删除要先叫停（否则 worker 还在写，恢复出来是半成品）
        assert resp.json()["was_running"] is True
        # ⭐ 但从 2026-10-18 起删除只是**进回收站**：行还在、详情仍可取（能恢复）
        assert client.get(f"/api/tasks/{task_id}").status_code == 200

    with SessionLocal() as session:
        row = session.get(Task, task_id)
        assert row is not None and row.deleted_at is not None


def test_retry_failed_task_restarts_clean(monkeypatch) -> None:
    _patch_engine(monkeypatch, CompletedEngine())
    task_id = _make_task(
        "failed",
        original_path=str(storage.UPLOADS_DIR / "old.pdf"),
        error_message="引擎未返回 result.json",
    )
    with SessionLocal() as session:
        session.add(
            TaskBlock(task_id=task_id, block_id="b_old", text="old", translated="旧")
        )
        session.add(TaskUnderstanding(task_id=task_id, status="ready", guide_json="{}"))
        session.commit()

    stale = storage.outputs_dir(task_id) / "old-mono.pdf"
    stale.write_bytes(PDF_BYTES)

    with TestClient(app) as client:
        resp = client.post(f"/api/tasks/{task_id}/retry")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == TaskState.PENDING.value
        with SessionLocal() as session:
            assert session.get(Task, task_id).error_message is None

        _wait_status(client, task_id, TaskState.COMPLETED.value)
        detail = client.get(f"/api/tasks/{task_id}").json()

    # 旧块被清掉，只剩本轮的新块
    assert [b["block_id"] for b in detail["blocks"]] == ["b1"]
    # 上一轮产物已删（新目录由 worker 重建，但旧文件不该在）
    assert not stale.exists()
    with SessionLocal() as session:
        assert (
            len(
                session.scalars(
                    select(TaskUnderstanding).where(
                        TaskUnderstanding.task_id == task_id
                    )
                ).all()
            )
            == 0
        )
        actions = [
            row.action
            for row in session.scalars(
                select(TaskHistory).where(TaskHistory.task_id == task_id)
            ).all()
        ]
    assert "retry" in actions
    assert TaskState.COMPLETED.value in actions


def test_retry_rejects_active_task(monkeypatch) -> None:
    """正在跑的任务不能重试：要先把翻译停下来（取消）再说。"""
    engine = BlockingEngine()
    _patch_engine(monkeypatch, engine)
    with TestClient(app) as client:
        task_id = _upload(client, "busy.pdf")["id"]
        assert engine.started.wait(5.0), "引擎没有被拉起"
        resp = client.post(f"/api/tasks/{task_id}/retry")
        assert resp.status_code == 409
        assert "重试" in resp.json()["detail"]
        client.post(f"/api/tasks/{task_id}/cancel")  # 收尾，避免测试退出时还挂着任务


def test_cancel_running_and_queued_tasks(monkeypatch) -> None:
    engine = BlockingEngine()
    _patch_engine(monkeypatch, engine)
    with TestClient(app) as client:
        running_id = _upload(client, "running.pdf")["id"]
        assert engine.started.wait(5.0), "引擎没有被拉起"

        # worker 正忙：新任务排在队列里（pending），取消它走"直接置终态"这条路
        queued_id = _upload(client, "queued.pdf")["id"]
        resp = client.post(f"/api/tasks/{queued_id}/cancel")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == TaskState.CANCELLED.value
        assert (
            client.get(f"/api/tasks/{queued_id}").json()["status"]
            == TaskState.CANCELLED.value
        )

        # 正在跑的：叫停子进程，由 worker 收尾落库
        resp = client.post(f"/api/tasks/{running_id}/cancel")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "cancelling"
        _wait_status(client, running_id, TaskState.CANCELLED.value)
        detail = client.get(f"/api/tasks/{running_id}").json()
        assert detail["error_message"] == "已取消"

    with SessionLocal() as session:
        actions = [
            row.action
            for row in session.scalars(
                select(TaskHistory).where(TaskHistory.task_id == running_id)
            ).all()
        ]
    assert TaskState.CANCELLED.value in actions


def test_cancel_completed_task_returns_409(monkeypatch) -> None:
    _patch_engine(monkeypatch, CompletedEngine())
    with TestClient(app) as client:
        task_id = _upload(client, "done.pdf")["id"]
        _wait_status(client, task_id, TaskState.COMPLETED.value)
        resp = client.post(f"/api/tasks/{task_id}/cancel")
    assert resp.status_code == 409


def test_storage_refuses_files_outside_data_dir() -> None:
    """安全阀：记录里的路径被人改成 data 之外的东西时，拒绝删除。

    用系统临时目录当"data 之外"（不放 tmp_path：沙盒里 pytest 的 tmp_path 不可写）。
    """
    outsider = Path(tempfile.gettempdir()) / "docwise_outside_test.pdf"
    outsider.write_bytes(PDF_BYTES)
    try:
        assert storage.remove_file(outsider) is False
        assert outsider.exists()  # 没被删掉
    finally:
        outsider.unlink(missing_ok=True)


def test_cleanup_orphan_outputs_keeps_known_tasks() -> None:
    kept = storage.outputs_dir(4242)
    kept.joinpath("mono.pdf").write_bytes(PDF_BYTES)
    orphan = storage.outputs_dir(999999)
    orphan.joinpath("mono.pdf").write_bytes(PDF_BYTES)

    removed = storage.cleanup_orphan_outputs({4242})

    assert removed >= 1
    assert kept.exists() and kept.joinpath("mono.pdf").exists()
    assert not orphan.exists()
