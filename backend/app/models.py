from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .engine.base import BlockState


class Task(Base):
    """任务卡：每个翻译任务的进度与状态。"""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    original_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_lang: Mapped[str] = mapped_column(String(16), default="en")
    target_lang: Mapped[str] = mapped_column(String(16), default="zh")
    tier: Mapped[str] = mapped_column(String(16), default="fast")
    translated_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True
    )  # pending / in_progress / completed / failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class TaskHistory(Base):
    """历史记录：任务生命周期中的关键动作。"""

    __tablename__ = "task_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class TaskBlock(Base):
    """单个文本块的翻译状态。失败必须可见，禁止静默截断。"""

    __tablename__ = "task_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    block_id: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[BlockState] = mapped_column(
        Enum(
            BlockState,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        default=BlockState.SUCCESS,
        index=True,
    )
    translated: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
