"""F 批：诚实进度——解析引擎日志 + 进度落库/接口字段。

解析用的样本**全部来自真实 engine.log**（不是编的）：

    b'not in git repo\\r\\n\\r  0%|          | 0/5 [00:00<?, ?it/s]'
    b'\\r 40%|\u2588\u2588\u2588\u2588      | 2/5 [00:01<00:01,  1.72it/s]'

tqdm 用 `\\r` 原地重绘（非 tty 时行尾也可能是 `\\n`），单位是页（引擎侧
`tqdm(total=total_pages)` + 每页 update）。
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID

from app import progress as progress_lib
from app import storage
from app.db import SessionLocal
from app.engine import BlockState, BlockStatus, TaskState, TranslationResult
from app.main import app
from app.models import Task
from app.worker import PROGRESS_POLL_SECONDS

REAL_TAIL = (
    "not in git repo\r\n"
    "\r  0%|          | 0/5 [00:00<?, ?it/s]"
    "\r 40%|\u2588\u2588\u2588\u2588      | 2/5 [00:01<00:01,  1.72it/s]"
)


# ---- 解析器（纯函数） ----

def test_parse_real_tqdm_log_takes_last_bar() -> None:
    parsed = progress_lib.parse_engine_progress(REAL_TAIL)
    assert parsed is not None
    assert (parsed.done, parsed.total) == (2, 5)
    assert parsed.percent == 0.4
    assert parsed.elapsed_seconds == 1
    assert parsed.eta_seconds == 1
    assert parsed.rate == 1.72
    assert parsed.label == "第 2/5 页"


def test_parse_unknown_eta_and_rate() -> None:
    parsed = progress_lib.parse_engine_progress("  0%|          | 0/5 [00:00<?, ?it/s]")
    assert parsed is not None
    assert parsed.percent == 0.0
    assert parsed.eta_seconds is None
    assert parsed.rate is None


def test_parse_hours_and_long_eta() -> None:
    parsed = progress_lib.parse_engine_progress(
        " 25%|##        | 5/20 [1:02:03<2:03:04,  1.00it/s]"
    )
    assert parsed is not None
    assert parsed.elapsed_seconds == 3723  # 1h2m3s
    assert parsed.eta_seconds == 7384  # 2h3m4s


def test_parse_returns_none_when_nothing_recognizable() -> None:
    noise = (
        "MuPDF error: syntax error: unknown keyword: '1.1652899999999998e'\r\n\r\n"
        "D:\\somewhere\\result.json\r\n"
    )
    assert progress_lib.parse_engine_progress(noise) is None
    assert progress_lib.parse_engine_progress("") is None


def test_progress_from_log_reads_only_the_tail() -> None:
    """日志前面塞一堆噪声（超过尾部窗口）也要能认出最后的进度条。"""
    workdir = storage.OUTPUTS_DIR / "test_tail"
    workdir.mkdir(parents=True, exist_ok=True)
    log = workdir / "engine.log"
    log.write_bytes(b"noise line\r\n" * 2000 + REAL_TAIL.encode("utf-8"))

    parsed = progress_lib.progress_from_log(log)

    assert parsed is not None
    assert (parsed.done, parsed.total) == (2, 5)


def test_progress_from_missing_log_is_none() -> None:
    missing = storage.OUTPUTS_DIR / "nope" / "engine.log"
    assert progress_lib.progress_from_log(None) is None
    assert progress_lib.progress_from_log(missing) is None


# ---- 接口字段 ----

def test_detail_exposes_engine_progress_and_queue_position() -> None:
    """跑着的任务：详情里给出引擎自报的分页进度；排队的给出"前面还有几篇"。"""
    with TestClient(app) as client:
        with SessionLocal() as session:
            running = Task(
                user_id=TEST_USER_ID, filename="running.pdf", tier="fast",
                status=TaskState.IN_PROGRESS.value, progress=0.4,
                stage="translating",
            )
            session.add(running)
            session.commit()
            running_id = running.id
            queued = Task(
                user_id=TEST_USER_ID, filename="queued.pdf", tier="fast",
                status=TaskState.PENDING.value,
            )
            session.add(queued)
            session.commit()
            queued_id = queued.id

        # 引擎日志落在这个任务自己的输出目录里
        out_dir = storage.outputs_dir(running_id)
        (out_dir / "engine.log").write_bytes(REAL_TAIL.encode("utf-8"))

        detail = client.get(f"/api/tasks/{running_id}").json()
        queued_detail = client.get(f"/api/tasks/{queued_id}").json()

    assert detail["stage"] == "translating"
    assert detail["engine_progress"]["done"] == 2
    assert detail["engine_progress"]["total"] == 5
    assert detail["engine_progress"]["eta_seconds"] == 1
    assert queued_detail["queue_position"] == 1  # 前面有一篇正在跑
    assert queued_detail["engine_progress"] is None


class FakeEngineWithLog:
    """假引擎：像真引擎那样往 engine.log 追加 tqdm 进度，并在中途回头看库里有没有跟上。

    用它验证"进度是真的从日志搬到库里"，不需要起子进程、也不花钱。
    任务号从 `request.output_dir`（= data/outputs/{task_id}）推出来，不依赖调用顺序。
    """

    name = "fake-progress"

    def __init__(self) -> None:
        self.task_id: int | None = None
        self.observed: float | None = None

    def _log_path(self) -> Path:
        assert self.task_id is not None
        return storage.outputs_dir(self.task_id) / "engine.log"

    def _write_bar(self, done: int, total: int) -> None:
        with self._log_path().open("a", encoding="utf-8") as handle:
            handle.write(
                f"\r {int(done / total * 100)}%|##  | {done}/{total} "
                f"[00:0{done}<00:0{total - done},  1.00it/s]"
            )

    def _wait_for_db_progress(self, floor: float, timeout: float = 6.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with SessionLocal() as session:
                task = session.get(Task, self.task_id)
                value = task.progress if task is not None else None
            if value is not None and value >= floor:
                self.observed = value
                return
            time.sleep(0.1)

    def translate(self, request, cancel=None) -> TranslationResult:
        _ = cancel
        self.task_id = int(Path(request.output_dir).name)
        self._write_bar(1, 4)
        self._wait_for_db_progress(0.25)  # 等 worker 的进度搬运工把 1/4 搬进库
        self._write_bar(3, 4)
        return TranslationResult(
            task_id="fake",
            translated_path=None,
            blocks=[
                BlockStatus(
                    block_id="b1", text="hello",
                    status=BlockState.SUCCESS, translated="你好",
                )
            ],
            status=TaskState.COMPLETED,
            progress=1.0,
        )


def test_worker_copies_engine_progress_into_db(monkeypatch) -> None:
    """worker 在引擎跑的时候会把 engine.log 里的真实进度写进库并推 SSE。"""
    engine = FakeEngineWithLog()

    monkeypatch.setattr("app.worker.get_engine", lambda tier=None: engine)

    with TestClient(app) as client:
        resp = client.post(
            "/api/tasks/upload",
            files={"file": ("progress.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"tier": "fast"},
        )
        task_id = resp.json()["id"]

        deadline = time.monotonic() + 15
        status = None
        while time.monotonic() < deadline:
            detail = client.get(f"/api/tasks/{task_id}").json()
            status = detail["status"]
            if status in (
                TaskState.COMPLETED.value,
                TaskState.FAILED.value,
                TaskState.CANCELLED.value,
            ):
                break
            time.sleep(0.1)

    assert status == TaskState.COMPLETED.value, "任务没跑完"
    # 关键断言：1/4 的进度**在引擎跑的过程中**就进了库（不是等结束才一次性写）
    assert engine.observed is not None, (
        f"进度没有在运行期落库（等 {PROGRESS_POLL_SECONDS}s 轮询也没等到 >=25%）"
    )
    assert engine.observed >= 0.25
    # 终态：进度归位、阶段清空、有起止时间
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        assert task.status == TaskState.COMPLETED.value
        assert task.progress == 1.0
        assert task.stage is None
        assert task.eta_seconds is None
        assert task.started_at is not None
        assert task.finished_at is not None
        assert task.finished_at >= task.started_at
