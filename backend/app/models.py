from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .engine.base import BlockState


class Task(Base):
    """任务卡：每个翻译任务的进度与状态。"""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 归属：登录用户（老库里为空，启动时按 DOCWISE_LEGACY_OWNER 归属）
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    original_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_lang: Mapped[str] = mapped_column(String(16), default="en")
    target_lang: Mapped[str] = mapped_column(String(16), default="zh")
    tier: Mapped[str] = mapped_column(String(16), default="fast")
    translated_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    dual_translated_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True
    )  # pending / in_progress / completed / failed / cancelled
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    # 这批字是怎么来的：None / "text-layer"（PDF 文字层）/ "ocr"（扫描件走 OCR）。
    # 界面据此如实说明"字是认出来的、可能有个别错字"——扫描件不能和文字层混为一谈。
    text_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 诚实进度（F 批）：阶段 + 引擎自报的预计剩余秒数；进度只增不减
    stage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    eta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 形体（阅读位置记忆）：上次读到第几页（1 起数）；没读过就是 NULL，
    # 界面据此决定显示「继续读 · 上次读到第 N 页」还是「开始阅读」——不假装记得。
    last_read_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 版面区域（2026-10-01，任务 A）：引擎自己跑一次版面模型，把每页的
    # `{页码: [{cls, bbox, conf}]}` 原样带回来（bbox 是**距页顶**的点坐标，
    # 与块 layout 同一口径）。
    # 与 `task_blocks.layout` 一样**只存原始量、不存判定结果**：判定规则将来改了，
    # 老任务不用重跑引擎就跟着受益。缺失（老任务 / OCR 扫描件）就是 NULL。
    regions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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
    # 版面信号（2026-09-30 起的契约）：`{"unit_h":…, "bold":…, "y0":…, "page_h":…}`。
    # **存原始信号、不存判定结果**——分级规则将来还会改，规则改了所有有信号的块一起受益；
    # 老任务这里是 NULL，分级器自动退回"只看文字形状"。
    # 字段含义见 scripts/extract_blocks.py。
    layout: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class TaskUnderstanding(Base):
    """论文导读/术语表的惰性计算结果（按需生成、缓存；失败可降级为"暂无"）。"""

    __tablename__ = "task_understanding"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id"), index=True, unique=True
    )
    guide_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="pending"
    )  # pending / ready / failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class User(Base):
    """账号：密码只存哈希（scrypt + 每人独立盐），绝不存明文。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")  # user / admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuthSession(Base):
    """登录会话：只存令牌的 sha256，可随时吊销（退出 / 踢设备）。"""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AuthTicket(Base):
    """临时票据：给"带不了请求头"的三种请求用（进度推送 / PDF 预览 / 下载）。

    绑定 用户 + 任务 + 用途，60 秒内有效；**不一次性消费**——否则同一页面多次
    取 URL 会互相把票据用掉，表现为"有时能打开、有时打不开"。
    """

    __tablename__ = "auth_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    scope: Mapped[str] = mapped_column(String(16))  # files / events
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)
