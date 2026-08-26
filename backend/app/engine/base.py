from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TranslateRequest:
    """一次翻译任务的输入。"""

    source_path: Path
    source_lang: str = "en"
    target_lang: str = "zh"
    tier: str = "fast"  # fast / medium / precise
    terms_path: Path | None = None


@dataclass
class BlockStatus:
    """单个文本块的处理状态。失败必须可见，禁止静默截断。"""

    block_id: str
    text: str
    status: str  # success / overflow / failed
    translated: str | None = None
    error: str | None = None


@dataclass
class TranslationResult:
    """引擎回报：译文 + 每块成败状态 + 进度。"""

    task_id: str
    translated_path: Path | None
    blocks: list[BlockStatus] = field(default_factory=list)
    status: str = "pending"  # pending / in_progress / completed / failed
    progress: float = 0.0
    error: str | None = None


class TranslationEngine(ABC):
    """统一的可插拔翻译引擎接口。

    引擎只负责"翻译 + 版面输出 + 每块状态回报"，不做流程控制（流程归调度器）。
    """

    name: str = "base"

    @abstractmethod
    def translate(self, request: TranslateRequest) -> TranslationResult:
        """执行一次翻译，返回译文与每块状态。"""
        raise NotImplementedError
