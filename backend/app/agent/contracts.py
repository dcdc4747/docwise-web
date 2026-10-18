"""Agent 的对外 ABI（**不许 import pydantic_ai**）。

这一层是"我们的语言"：工具、场景、上下文都只认这里定义的类型。
`runtime.py` 负责把这些翻译成 pydantic-ai 的东西；换引擎只改 runtime。

为什么要把 ABI 单独一个文件：`packs/` 和 `scenes/` 是插件，
**它们不该知道底下用的是哪家框架**——否则哪天换框架，插件全得重写。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


@dataclass
class ToolContext:
    """一次工具调用能看到的全部东西（**只给该看的**）。

    ⚠️ `db` 由 runtime 在**工具自己的线程里**新建：pydantic-ai 会把同步函数丢进线程池，
    请求级 Session 不能跨线程复用（SQLAlchemy Session 不是线程安全的）。
    """

    db: Any
    user_id: int
    scene_id: str
    # 页面带来的上下文（task_id / draft_id / selection…），**只读**、只收白名单字段
    scope: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """工具返回值。`note` 会进轨迹，也会回给模型（截断/没查到/降级原因）。

    `summary` 是**给界面看的摘要**（可选）：结果字典可能很长，`tool_result` 的
    excerpt 只截前 400 字，关键数字容易被挤掉。有 summary 时界面优先显示它，
    正文仍以 `data` 为准（模型读的是 data，不是 summary）。
    """

    data: Any
    note: str = ""
    summary: str = ""


@dataclass
class ToolSpec:
    """一个工具。`parameters` 是 JSON Schema（我们的格式，与框架无关）。"""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], ToolResult]
    max_result_chars: int = 4000
    timeout_ms: int = 20_000


@dataclass
class Pack:
    """一组工具。**一个功能一个文件**，`packs/__init__.py` 自动发现。"""

    name: str
    tools: tuple[ToolSpec, ...] = ()


@dataclass
class Scene:
    """一个入口的 agent 配置（场景）。加新入口 = 加一个 scene 文件。

    `packs` 是**白名单**：这个场景只能用这些包里的工具。
    agent 的能力边界由场景声明，不靠提示词约束。
    """

    id: str
    title: str
    system_prompt: str
    output_type: type[BaseModel]
    packs: tuple[str, ...] = ()
    default_tier: str = "standard"
    # 场景自己决定"要带哪些上下文"（当前文献摘要、草稿片段…）；返回空串就是不带
    build_context: Callable[[ToolContext], str] | None = None
    # 收尾校验钩子：拿到模型输出，剔除"编出来的东西"
    # （如写作建议里对不上原文的 original）。
    # 返回 (保留的输出, 剔掉的说明列表)。**默认不做**，由场景自己决定要校验什么。
    verify: Callable[[ToolContext, Any], tuple[Any, list[str]]] | None = None
    # planned = 口子留着、还没实现（前端据此显示"即将开放"）
    status: str = "ready"
