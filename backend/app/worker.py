from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from sqlalchemy import delete, select, update

from .db import SessionLocal
from .engine import TaskState, Tier, TranslateRequest, TranslationResult, get_engine
from .models import Task, TaskBlock, TaskHistory

logger = logging.getLogger(__name__)

# 空闲时也周期性刷新心跳；顺带扫表兜底，避免漏掉新建任务
HEARTBEAT_INTERVAL_SECONDS = 10.0
SWEEP_INTERVAL_SECONDS = 30.0


class TaskEventBus:
    """进程内任务状态发布/订阅，供 SSE 端点实时推送进度。

    单进程 worker 与 SSE 端点共享一个 bus：worker 在状态变化时 publish，
    SSE 端点 subscribe 到对应 task_id 并向下游推流。
    """

    def __init__(self) -> None:
        self._subscribers: dict[int, set[asyncio.Queue]] = {}

    def subscribe(self, task_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(task_id, set()).add(queue)
        return queue

    def unsubscribe(self, task_id: int, queue: asyncio.Queue) -> None:
        subs = self._subscribers.get(task_id)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                self._subscribers.pop(task_id, None)

    async def publish(self, task_id: int, event: dict) -> None:
        for queue in list(self._subscribers.get(task_id, ())):
            await queue.put(event)


def _record_history(
    session, task_id: int, action: str, detail: str | None = None
) -> None:
    session.add(TaskHistory(task_id=task_id, action=action, detail=detail))


class TranslationWorker:
    """单进程串行 worker：扫表恢复、行锁认领、线程池里跑引擎、落库并发布事件。

    串行处理避免 SQLite 写锁；并发多 worker 时靠"行锁认领"（UPDATE ... WHERE
    status='pending'）保证同一任务只被一个 worker 处理。
    韧性约定：**单个任务的任何异常都不得杀死循环**，异常如实落库并打日志。
    """

    def __init__(self, bus: TaskEventBus) -> None:
        self.bus = bus
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_heartbeat = time.monotonic()
        self._last_sweep = 0.0
        self.current_task_id: int | None = None

    # ---- 供健康检查读取的运行态 ----
    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def heartbeat_age(self) -> float:
        """距上次心跳的秒数（越小越健康）。"""
        return time.monotonic() - self._last_heartbeat

    def is_alive(self) -> bool:
        return self._task is not None and not self._task.done()

    def _heartbeat(self) -> None:
        self._last_heartbeat = time.monotonic()

    def enqueue(self, task_id: int) -> None:
        self._queue.put_nowait(task_id)
        logger.info("任务入队：task_id=%s（队列长度 %s）", task_id, self.queue_size)

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("worker 已启动（单进程串行）")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("worker 已停止")

    async def _loop(self) -> None:
        # 启动即恢复：中断的 in_progress 拉回 pending，并拉起所有待处理任务
        await self._startup_pass()
        while self._running:
            try:
                task_id = await asyncio.wait_for(
                    self._queue.get(), timeout=HEARTBEAT_INTERVAL_SECONDS
                )
            except TimeoutError:
                # 空闲：刷新心跳，并按周期扫表兜底
                self._heartbeat()
                await self._periodic_sweep()
                continue
            except asyncio.CancelledError:
                return
            if not self._running:
                return
            self._heartbeat()
            self.current_task_id = task_id
            try:
                await self._process(task_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 单任务异常不得杀死循环
                logger.exception("任务处理异常，循环继续：task_id=%s", task_id)
                self._fail_safely(task_id, f"内部错误：{exc}")
            finally:
                self.current_task_id = None
                self._heartbeat()

    async def _startup_pass(self) -> None:
        try:
            self._recover_interrupted()
            self._enqueue_pending()
            logger.info("worker 启动恢复完成：已拉起待处理任务")
        except Exception:  # noqa: BLE001 - 恢复失败也要让循环活着
            logger.exception("worker 启动恢复失败（将在周期扫表时重试）")

    async def _periodic_sweep(self) -> None:
        """空闲时的兜底扫表：把新出现的 pending 任务拉起来。

        认领（UPDATE ... WHERE status='pending'）是幂等的，重复入队不会重复执行。
        """
        if time.monotonic() - self._last_sweep < SWEEP_INTERVAL_SECONDS:
            return
        self._last_sweep = time.monotonic()
        try:
            self._enqueue_pending()
        except Exception:  # noqa: BLE001
            logger.exception("周期扫表失败（下轮重试）")

    def _fail_safely(self, task_id: int, error: str) -> None:
        """尽力把任务标记为失败——标记失败本身也不能再抛异常。"""
        try:
            self._persist_failure(task_id, error)
        except Exception:  # noqa: BLE001
            logger.exception("标记任务失败时又出错：task_id=%s", task_id)

    def _recover_interrupted(self) -> None:
        """把停在中途的 in_progress 任务回退为 pending，交由 worker 重新拉起。

        说明：阶段 1 引擎为一次性整体翻译，无法块级续跑；此处做到"任务级断点续跑"
        ——崩溃重启后任务不会卡死，会自动重新处理。
        """
        with SessionLocal() as session:
            result = session.execute(
                update(Task)
                .where(Task.status == TaskState.IN_PROGRESS.value)
                .values(
                    status=TaskState.PENDING.value,
                    progress=0.0,
                    error_message=None,
                )
            )
            session.commit()
            if result.rowcount:
                logger.warning(
                    "恢复中断任务 %s 个（in_progress → pending）", result.rowcount
                )

    def _enqueue_pending(self) -> None:
        with SessionLocal() as session:
            ids = session.scalars(
                select(Task.id).where(Task.status == TaskState.PENDING.value)
            ).all()
        for task_id in ids:
            self.enqueue(task_id)

    def _claim(self, task_id: int) -> bool:
        """行锁认领：原子地把 pending -> in_progress，返回是否抢到。

        抢到才处理，避免重复执行；顺带清空旧块，保证重跑幂等。
        """
        with SessionLocal() as session:
            result = session.execute(
                update(Task)
                .where(
                    Task.id == task_id,
                    Task.status == TaskState.PENDING.value,
                )
                .values(status=TaskState.IN_PROGRESS.value, progress=0.0)
            )
            session.execute(delete(TaskBlock).where(TaskBlock.task_id == task_id))
            if result.rowcount == 1:
                _record_history(session, task_id, "started")
            session.commit()
            return result.rowcount == 1

    def _load_request(self, task_id: int) -> TranslateRequest | None:
        with SessionLocal() as session:
            task = session.get(Task, task_id)
            if task is None or not task.original_path:
                return None
            return TranslateRequest(
                source_path=Path(task.original_path),
                source_lang=task.source_lang,
                target_lang=task.target_lang,
                tier=Tier(task.tier),
            )

    def _run_engine(self, request: TranslateRequest) -> TranslationResult:
        # 引擎调用为阻塞子进程，放线程池执行（见 _process 的 asyncio.to_thread）
        return get_engine(request.tier).translate(request)

    async def _process(self, task_id: int) -> None:
        if not self._claim(task_id):
            logger.debug("任务已被认领或不存在，跳过：task_id=%s", task_id)
            return
        logger.info("开始处理任务：task_id=%s", task_id)

        request = self._load_request(task_id)
        if request is None:
            self._persist_failure(task_id, "任务缺少 source_path，无法翻译")
            await self.bus.publish(
                task_id,
                {"type": "failed", "status": "failed", "progress": 0.0,
                 "error": "任务缺少 source_path，无法翻译"},
            )
            return

        await self.bus.publish(
            task_id,
            {"type": "status", "status": TaskState.IN_PROGRESS.value, "progress": 0.0},
        )
        started = time.monotonic()
        try:
            result = await asyncio.to_thread(self._run_engine, request)
        except Exception as exc:  # noqa: BLE001 - 引擎异常也如实落库并回传
            logger.exception("引擎执行失败：task_id=%s", task_id)
            self._persist_failure(task_id, str(exc))
            await self.bus.publish(
                task_id,
                {
                    "type": "failed",
                    "status": "failed",
                    "progress": 0.0,
                    "error": str(exc),
                },
            )
            return

        self._persist_result(task_id, result)
        terminal = (
            result.status.value
            if isinstance(result.status, TaskState)
            else result.status
        )
        logger.info(
            "任务处理结束：task_id=%s status=%s 用时=%.1fs 块数=%s",
            task_id,
            terminal,
            time.monotonic() - started,
            len(result.blocks),
        )
        await self.bus.publish(
            task_id,
            {
                "type": terminal,
                "status": terminal,
                "progress": result.progress,
                "error": result.error,
            },
        )

    def _persist_result(self, task_id: int, result: TranslationResult) -> None:
        with SessionLocal() as session:
            task = session.get(Task, task_id)
            if task is None:
                return
            for block in result.blocks:
                session.add(
                    TaskBlock(
                        task_id=task_id,
                        block_id=block.block_id,
                        text=block.text,
                        status=block.status,
                        translated=block.translated,
                        error=block.error,
                    )
                )
            terminal = (
                result.status.value
                if isinstance(result.status, TaskState)
                else result.status
            )
            task.status = terminal
            task.progress = result.progress
            task.error_message = result.error
            task.translated_path = (
                str(result.translated_path) if result.translated_path else None
            )
            task.dual_translated_path = (
                str(result.dual_path) if result.dual_path else None
            )
            _record_history(session, task_id, terminal, result.error)
            session.commit()
            session.refresh(task)

    def _persist_failure(self, task_id: int, error: str) -> None:
        with SessionLocal() as session:
            task = session.get(Task, task_id)
            if task is None:
                return
            task.status = TaskState.FAILED.value
            task.progress = 0.0
            task.error_message = error
            _record_history(session, task_id, TaskState.FAILED.value, error)
            session.commit()
