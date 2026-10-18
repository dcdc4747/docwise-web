"""runtime：**唯一 import pydantic_ai 的文件**（换引擎只改这里）。

职责只有四件：
1. Scene → Agent（模型、提示词、工具、上限）；
2. ToolSpec → 它的 Tool（我们的 JSON Schema 翻成 pydantic 模型，**不碰私有 API**）；
3. run 一次，把结果整理成 `{answer, sources, steps, usage}`；
4. 出网环境护栏（它的 httpx2 会在 NO_PROXY 里读到 `[::1]` 直接崩，见 netenv）。

⚠️ 本文件**不许写业务查询**（那是 services 的事），也**不许被 packs/scenes import**。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, create_model

from ..db import SessionLocal
from ..netenv import sanitize_proxy_env
from .contracts import Scene, ToolContext, ToolSpec
from .registry import tools_of

logger = logging.getLogger(__name__)

_PY_TYPES = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}

# 循环上限：6 步左右（request_limit 含收尾那次，所以 +1）
# 块号：`p0_b3` / `p12_b40`（跨任务会重名，所以只在"工具真返回过"的集合里认）
_BLOCK_ID_RE = re.compile(r"\bp\d+_b\d+\b")

_REQUEST_LIMIT = 7
_TOOL_CALL_LIMIT = 12


@dataclass
class LLMConfig:
    """一次对话用哪家模型。密钥**只在内存里出现**，不写日志。"""

    base_url: str
    api_key: str
    model: str


def _args_model(name: str, schema: dict) -> type[BaseModel]:
    """我们的 JSON Schema → pydantic 模型（类型有限，映射可控）。"""
    fields: dict[str, Any] = {}
    required = set(schema.get("required") or [])
    for key, prop in (schema.get("properties") or {}).items():
        py = _PY_TYPES.get(prop.get("type", "string"), str)
        fields[key] = (py, ... if key in required else None)
    return create_model(f"{name}_args", **fields)


def _to_tool(spec: ToolSpec):
    """ToolSpec → pydantic-ai Tool。**同步 handler 会被框架丢进线程池**，
    所以这里在工具内部新建 Session（请求级 Session 不能跨线程）。"""
    from pydantic_ai import ModelRetry, Tool

    Args = _args_model(spec.name, spec.parameters)

    def _run_body(ctx, args: Args):  # noqa: ANN001 —— 真正的执行体（被 exec 出来的壳调用）
        payload = args.model_dump()
        try:
            with SessionLocal() as db:
                result = spec.handler(
                    ToolContext(
                        db=db,
                        user_id=ctx.deps.user_id,
                        scene_id=ctx.deps.scene_id,
                        scope=dict(ctx.deps.scope or {}),
                    ),
                    payload,
                )
        except Exception as exc:  # noqa: BLE001 —— 任何工具异常都不许炸整轮
            logger.warning("工具 %s 失败：%s", spec.name, exc)
            raise ModelRetry(f"{spec.name} 执行失败：{exc}") from exc
        data = result.data
        text = str(data)
        if len(text) > spec.max_result_chars:
            return text[: spec.max_result_chars] + "……（结果已截断）"
        return data

    # ⚠️ 为什么要 exec：本模块有 `from __future__ import annotations`，
    # 手写的 `def _call(ctx, args: Args)` 里 `Args` 会变成**字符串注解**，
    # pydantic-ai 在运行期解析类型时找不到它（实测 NameError）。
    # 用 exec 在命名空间里定义，注解就是**真的类对象**，框架能直接生成 schema。
    namespace = {"Args": Args, "_body": _run_body}
    exec(  # noqa: S102 —— 生成的源码是我们自己的常量，不含外部输入
        "def _call(ctx, args: Args):\n    return _body(ctx, args)\n",
        namespace,
    )
    _call = namespace["_call"]

    return Tool(
        function=_call,
        takes_ctx=True,
        name=spec.name,
        description=spec.description,
        timeout=spec.timeout_ms / 1000,
    )


def build_agent(scene: Scene, cfg: LLMConfig, model: Any = None):
    """Scene → Agent。`model` 参数给测试注入（FunctionModel），生产不传。"""
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    # ⚠️ 必须在**构造模型之前**洗环境：httpx2 建 URLPattern 时会被 `[::1]` 弄崩
    sanitize_proxy_env()

    if model is None:
        model = OpenAIChatModel(
            cfg.model,
            provider=OpenAIProvider(base_url=cfg.base_url, api_key=cfg.api_key),
        )

    return Agent(
        model,
        output_type=scene.output_type,
        deps_type=ToolContext,
        system_prompt=scene.system_prompt,
        tools=[_to_tool(spec) for spec in tools_of(scene)],
        retries=2,
        tool_timeout=20,
    )


def _steps_of(messages) -> list[dict]:
    """从历史里还原"人话轨迹"（前端「它查了什么」用它）。"""
    from pydantic_ai.messages import RetryPromptPart, ToolCallPart, ToolReturnPart

    steps: list[dict] = []
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                steps.append(
                    {
                        "kind": "tool_call",
                        "name": part.tool_name,
                        "args": part.args,
                    }
                )
            elif isinstance(part, ToolReturnPart):
                body = str(part.content)
                steps.append(
                    {
                        "kind": "tool_result",
                        "name": part.tool_name,
                        "ok": True,
                        "excerpt": body[:300],
                    }
                )
            elif isinstance(part, RetryPromptPart):
                steps.append(
                    {
                        "kind": "tool_result",
                        "name": getattr(part, "tool_name", "") or "",
                        "ok": False,
                        "excerpt": str(part.content)[:300],
                    }
                )
    return steps


async def run_scene(
    scene: Scene,
    question: str,
    *,
    user_id: int,
    scope: dict | None = None,
    cfg: LLMConfig,
    model: Any = None,
) -> dict:
    """跑一次场景，返回 `{answer, sources, steps, usage, requests}`。"""
    from pydantic_ai.usage import UsageLimits

    scope = dict(scope or {})
    ctx = ToolContext(db=None, user_id=user_id, scene_id=scene.id, scope=scope)
    context_note = ""
    if scene.build_context is not None:
        try:
            context_note = scene.build_context(ctx) or ""
        except Exception as exc:  # noqa: BLE001 —— 上下文构造失败不该拖垮对话
            logger.warning("场景 %s 构造上下文失败：%s", scene.id, exc)

    prompt = question if not context_note else f"{context_note}\n\n问题：{question}"
    agent = build_agent(scene, cfg, model=model)
    result = await agent.run(
        prompt,
        deps=ctx,
        usage_limits=UsageLimits(
            request_limit=_REQUEST_LIMIT, tool_calls_limit=_TOOL_CALL_LIMIT
        ),
    )

    output = result.output
    answer = getattr(output, "answer", "") or ""
    sources = list(getattr(output, "source_block_ids", []) or [])

    steps = _steps_of(result.all_messages())
    # 出处校验：只留**工具真的返回过**的块号（模型编的一律剔掉）
    # 块号形状是 `p<页>_b<块>`（如 p0_b3）；工具结果可能是 dict 的 repr，用正则取。
    seen: set[str] = set()
    for step in steps:
        if step["kind"] == "tool_result" and step.get("ok"):
            seen.update(_BLOCK_ID_RE.findall(str(step.get("excerpt", ""))))
    verified = [sid for sid in sources if sid in seen]

    usage = result.usage
    return {
        "answer": answer,
        "sources": verified,
        "dropped_sources": [sid for sid in sources if sid not in verified],
        "steps": steps,
        "usage": {
            "requests": getattr(usage, "requests", None),
            "tool_calls": getattr(usage, "tool_calls", None),
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        },
        "history_json": result.all_messages_json().decode("utf-8"),
    }


async def stream_scene(
    scene: Scene,
    question: str,
    *,
    user_id: int,
    scope: dict | None = None,
    cfg: LLMConfig,
    model: Any = None,
):
    """流式跑一次场景，逐步 `yield` 事件（见模块 docstring 的形状）。

    ⚠️ 事件的**类型名**是我们自己的（`tool_call`/`tool_result`/`delta`/`final`），
    前端不依赖 pydantic-ai 的类型——换引擎时前端不用改。
    """
    from pydantic_ai import AgentRunResultEvent
    from pydantic_ai.messages import (
        FunctionToolCallEvent,
        FunctionToolResultEvent,
        PartDeltaEvent,
        RetryPromptPart,
        TextPartDelta,
        ThinkingPartDelta,
    )
    from pydantic_ai.usage import UsageLimits

    scope = dict(scope or {})
    ctx = ToolContext(db=None, user_id=user_id, scene_id=scene.id, scope=scope)
    context_note = ""
    if scene.build_context is not None:
        try:
            context_note = scene.build_context(ctx) or ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("场景 %s 构造上下文失败：%s", scene.id, exc)
    prompt = question if not context_note else f"{context_note}\n\n问题：{question}"

    agent = build_agent(scene, cfg, model=model)
    yield {"type": "start", "scene": scene.id, "model": cfg.model}

    try:
        async with agent.run_stream_events(
            prompt,
            deps=ctx,
            usage_limits=UsageLimits(
                request_limit=_REQUEST_LIMIT, tool_calls_limit=_TOOL_CALL_LIMIT
            ),
        ) as stream:
            async for event in stream:
                if isinstance(event, FunctionToolCallEvent):
                    part = event.part
                    if str(part.tool_name).endswith("final_result"):
                        continue  # 收尾不是"查"
                    yield {
                        "type": "tool_call",
                        "name": part.tool_name,
                        "args": part.args,
                    }
                elif isinstance(event, FunctionToolResultEvent):
                    name = getattr(event.part, "tool_name", "") or ""
                    if str(name).endswith("final_result"):
                        continue
                    failed = isinstance(event.part, RetryPromptPart)
                    yield {
                        "type": "tool_result",
                        "name": name,
                        "ok": not failed,
                        "excerpt": str(event.content)[:400],
                    }
                elif isinstance(event, PartDeltaEvent):
                    delta = event.delta
                    # 思考片段（reasoner 类模型）：单独一种事件，前端只在"过程"里显示
                    if isinstance(delta, ThinkingPartDelta) and delta.content_delta:
                        yield {"type": "thinking", "text": delta.content_delta}
                    elif isinstance(delta, TextPartDelta) and delta.content_delta:
                        yield {"type": "delta", "text": delta.content_delta}
                elif isinstance(event, AgentRunResultEvent):
                    result = event.result
                    output = result.output
                    sources = list(getattr(output, "source_block_ids", []) or [])
                    steps = _steps_of(result.all_messages())
                    seen: set[str] = set()
                    for step in steps:
                        if step["kind"] == "tool_result" and step.get("ok"):
                            seen.update(
                                _BLOCK_ID_RE.findall(
                                    str(step.get("excerpt", ""))
                                )
                            )
                    usage = result.usage
                    yield {
                        "type": "final",
                        "answer": getattr(output, "answer", "") or "",
                        "sources": [sid for sid in sources if sid in seen],
                        "dropped_sources": [sid for sid in sources if sid not in seen],
                        "steps": steps,
                        "usage": {
                            "requests": getattr(usage, "requests", None),
                            "tool_calls": getattr(usage, "tool_calls", None),
                        },
                    }
    except Exception as exc:  # noqa: BLE001 —— 流式失败要**说人话**，不是静默断流
        logger.warning("流式跑场景 %s 失败：%s", scene.id, exc)
        yield {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
