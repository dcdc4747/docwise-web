from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Tier(StrEnum):
    """档位。"""

    FAST = "fast"
    MEDIUM = "medium"
    PRECISE = "precise"


class TaskState(StrEnum):
    """任务级状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskCancelled(RuntimeError):
    """任务被用户取消（区别于"出错失败"，取消不算引擎缺陷）。"""


class CancelToken:
    """取消信号：从接口线程传进引擎线程，让跑着的引擎子进程能被叫停。

    引擎在自己的线程里轮询 `cancelled`（或 `wait(timeout)` 一小段），
    发现被取消就终止子进程并返回 CANCELLED，而不是继续烧算力。
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        """等待取消信号最多 timeout 秒；返回是否已取消（兼当 sleep 用）。"""
        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise TaskCancelled("任务已被取消")


class BlockState(StrEnum):
    """单个文本块的状态。失败必须可见，禁止静默截断。"""

    SUCCESS = "success"
    OVERFLOW = "overflow"
    FAILED = "failed"


@dataclass(frozen=True)
class TranslateRequest:
    """一次翻译任务的输入。"""

    source_path: Path
    source_lang: str = "en"
    target_lang: str = "zh"
    tier: Tier = Tier.FAST
    terms_path: Path | None = None
    # 结果落到哪个目录（约定 data/outputs/{task_id}，便于删除任务时整体清理）；
    # 不传则由引擎自己开临时目录（测试与一次性调用用）。
    output_dir: Path | None = None


@dataclass
class BlockStatus:
    """单个文本块的处理状态。"""

    block_id: str
    text: str
    status: BlockState = BlockState.SUCCESS
    translated: str | None = None
    error: str | None = None


@dataclass
class TranslationResult:
    """引擎回报：译文 + 每块成败状态 + 进度。"""

    task_id: str
    translated_path: Path | None
    dual_path: Path | None = None
    blocks: list[BlockStatus] = field(default_factory=list)
    status: TaskState = TaskState.PENDING
    progress: float = 0.0
    error: str | None = None


class TranslationEngine(ABC):
    """统一的可插拔翻译引擎接口。

    引擎只负责"翻译 + 版面输出 + 每块状态回报"，不做流程控制（流程归调度器）。
    """

    name: str = "base"

    @abstractmethod
    def translate(
        self, request: TranslateRequest, cancel: CancelToken | None = None
    ) -> TranslationResult:
        """执行一次翻译，返回译文与每块状态。

        `cancel` 不为空时，引擎应周期性检查它；一旦被取消就停止子进程并返回
        `TaskState.CANCELLED` 的结果（不要抛异常，让调度器能如实落库）。
        """
        raise NotImplementedError
