from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select, update

from . import progress as progress_lib
from . import storage
from .db import SessionLocal
from .engine import (
    CancelToken,
    TaskState,
    Tier,
    TranslateRequest,
    TranslationResult,
    get_engine,
)
from .models import Task, TaskBlock, TaskHistory

logger = logging.getLogger(__name__)

# 空闲时也周期性刷新心跳；顺带扫表兜底，避免漏掉新建任务
HEARTBEAT_INTERVAL_SECONDS = 10.0
SWEEP_INTERVAL_SECONDS = 30.0
# 引擎跑的时候多久去 engine.log 捞一次真实进度（秒）
PROGRESS_POLL_SECONDS = 1.5
# 阶段文字（库里只存机器值，人话在前端拼）
STAGE_TRANSLATING = "translating"


def _status_value(status) -> str:
    return getattr(status, "value", status)


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
        # 正在处理的任务 → 取消信号（接口线程 cancel()，引擎线程轮询）
        self._cancel_tokens: dict[int, CancelToken] = {}

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

    def request_cancel(self, task_id: int) -> bool:
        """请求取消正在跑的任务；返回"是否需要等 worker 收尾"。

        只碰内存（Token 的 Event.set 是原子的），可从接口线程安全调用；
        真正落库为 cancelled 由 worker 在引擎停下来之后做，避免和
        completed/failed 的落库打架。
        """
        token = self._cancel_tokens.get(task_id)
        if token is None:
            return False
        token.cancel()
        logger.info("已发出取消信号：task_id=%s", task_id)
        return True

    @property
    def running_task_ids(self) -> list[int]:
        return list(self._cancel_tokens)

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
                    stage=None,
                    eta_seconds=None,
                    started_at=None,
                    finished_at=None,
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
                .values(
                    status=TaskState.IN_PROGRESS.value,
                    progress=0.0,
                    # 诚实进度（F 批）：记下真正开跑的时刻，前端据此走秒
                    stage=STAGE_TRANSLATING,
                    eta_seconds=None,
                    started_at=datetime.now(),
                    finished_at=None,
                )
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
                # 结果按任务落一个目录：删除任务时整体清理，不留散落文件
                output_dir=storage.outputs_dir(task_id),
            )

    def _run_engine(
        self, request: TranslateRequest, cancel: CancelToken
    ) -> TranslationResult:
        # 引擎调用为阻塞子进程，放线程池执行（见 _process 的 asyncio.to_thread）
        return get_engine(request.tier).translate(request, cancel)

    async def _process(self, task_id: int) -> None:
        if not self._claim(task_id):
            logger.debug("任务已被认领或不存在，跳过：task_id=%s", task_id)
            return
        logger.info("开始处理任务：task_id=%s", task_id)
        # 认领后立刻登记取消信号：此刻起到引擎结束，用户点"取消"都能叫停
        token = CancelToken()
        self._cancel_tokens[task_id] = token

        try:
            await self._process_claimed(task_id, token)
        finally:
            self._cancel_tokens.pop(task_id, None)

    async def _process_claimed(self, task_id: int, cancel: CancelToken) -> None:
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
            {
                "type": "status",
                "status": TaskState.IN_PROGRESS.value,
                "progress": 0.0,
                "stage": STAGE_TRANSLATING,
                "started_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        started = time.monotonic()
        # 引擎跑的时候，另起一个任务定期把 engine.log 里的真实进度搬进库并推给前端
        watcher = asyncio.create_task(
            self._watch_progress(task_id, request.output_dir)
        )
        try:
            result = await asyncio.to_thread(self._run_engine, request, cancel)
        except Exception as exc:  # noqa: BLE001 - 引擎异常也如实落库并回传
            logger.exception("引擎执行失败：task_id=%s", task_id)
            if cancel.cancelled:
                self._persist_cancelled(task_id)
                await self.bus.publish(
                    task_id,
                    {"type": "cancelled", "status": "cancelled", "progress": 0.0,
                     "error": "已取消"},
                )
                return
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
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher

        terminal = _status_value(result.status)
        if terminal == TaskState.CANCELLED.value:
            self._persist_cancelled(task_id)
        else:
            self._persist_result(task_id, result)
        # 任务可能在翻译途中被删掉：此时落库为空转，顺手把子进程留下的目录清掉
        self._cleanup_if_deleted(task_id, request)
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

    @staticmethod
    def _cleanup_if_deleted(task_id: int, request: TranslateRequest) -> None:
        try:
            with SessionLocal() as session:
                if session.get(Task, task_id) is not None:
                    return
            if request.output_dir is not None:
                storage.remove_dir(request.output_dir)
            logger.info("任务已被删除，清理其输出目录：task_id=%s", task_id)
        except Exception:  # noqa: BLE001 - 清理失败不影响主流程
            logger.exception("清理已删除任务的输出目录失败：task_id=%s", task_id)

    async def _watch_progress(self, task_id: int, output_dir: Path | None) -> None:
        """引擎跑的时候，定期把 engine.log 里的**真实**进度搬进库并推给前端。

        解析不出（引擎还没打进度条 / 换了输出格式）就什么都不做——宁可让前端显示
        "引擎还没报进度"，也不编一个百分比出来。进度只增不减：引擎分阶段重跑时
        进度条会回到 0，落库时取历史最大值，避免进度条来回跳。
        """
        if output_dir is None:
            return
        log_path = output_dir / "engine.log"
        best_percent = 0.0
        last_eta: int | None = None
        while True:
            await asyncio.sleep(PROGRESS_POLL_SECONDS)
            parsed = progress_lib.progress_from_log(log_path)
            if parsed is None:
                continue
            percent = max(best_percent, parsed.percent)
            if percent <= best_percent and parsed.eta_seconds == last_eta:
                continue
            best_percent = percent
            last_eta = parsed.eta_seconds
            if not self._persist_progress(task_id, percent, parsed.eta_seconds):
                return  # 任务已经不在跑了（取消/删除/已结束），收工
            await self.bus.publish(
                task_id,
                {
                    "type": "progress",
                    "status": TaskState.IN_PROGRESS.value,
                    "progress": percent,
                    "stage": STAGE_TRANSLATING,
                    "eta_seconds": parsed.eta_seconds,
                    "engine_done": parsed.done,
                    "engine_total": parsed.total,
                    "engine_rate": parsed.rate,
                },
            )

    def _persist_progress(
        self, task_id: int, progress: float, eta_seconds: int | None
    ) -> bool:
        """把进度落库；返回任务是否仍在进行中。"""
        try:
            with SessionLocal() as session:
                task = session.get(Task, task_id)
                if task is None or task.status != TaskState.IN_PROGRESS.value:
                    return False
                task.progress = progress
                task.eta_seconds = eta_seconds
                task.stage = STAGE_TRANSLATING
                session.commit()
            return True
        except Exception:  # noqa: BLE001 - 进度写不进去也不能影响翻译本身
            logger.exception("写进度失败：task_id=%s", task_id)
            return True

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
            terminal = _status_value(result.status)
            task.status = terminal
            task.progress = result.progress
            task.error_message = result.error
            task.translated_path = (
                str(result.translated_path) if result.translated_path else None
            )
            task.dual_translated_path = (
                str(result.dual_path) if result.dual_path else None
            )
            # 终态：不再有"阶段"与"预计剩余"，耗时由 started_at/finished_at 决定
            task.stage = None
            task.eta_seconds = None
            task.finished_at = datetime.now()
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
            task.stage = None
            task.eta_seconds = None
            task.finished_at = datetime.now()
            _record_history(session, task_id, TaskState.FAILED.value, error)
            session.commit()

    def _persist_cancelled(self, task_id: int) -> None:
        """落库为"已取消"——取消不算失败，也不覆盖别的终态。"""
        with SessionLocal() as session:
            task = session.get(Task, task_id)
            if task is None:
                return
            task.status = TaskState.CANCELLED.value
            task.progress = 0.0
            task.error_message = "已取消"
            task.stage = None
            task.eta_seconds = None
            task.finished_at = datetime.now()
            _record_history(session, task_id, TaskState.CANCELLED.value, "用户取消")
            session.commit()
