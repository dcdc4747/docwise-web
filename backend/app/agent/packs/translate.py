"""翻译侧工具包：查进度、按用户明确确认重译。

用户问「我那篇翻译到哪了」时用 `get_progress`；想重译时**先解释、拿到明确确认**
再用 `request_retranslate`——没有 `confirm: true` 一个字都不改。

⚠️ 这个文件**不许 import pydantic_ai**（结构用例钉着）：工具只是普通函数，
框架细节全在 `runtime.py`——换引擎时这里一行不用改。

⚠️ 进度只照抄库里的 `tasks.progress`：解析不出就是 0，**绝不替引擎编百分比**。
"""

from __future__ import annotations

from sqlalchemy import func, select

from ...db import SessionLocal
from ...models import Task, TaskBlock
from ..contracts import Pack, ToolResult, ToolSpec

_CONFIRM_HINT = "要重新翻译，请在界面上点「重试」，或者明确说「确认重译」。"
# 还在排队 / 正在跑的任务不用重译：再置一次 pending 只会重复跑一遍
_ALREADY_MOVING = ("pending", "in_progress")
# 状态 → 人话（模型自己瞎猜进度，不如让它照抄这句）
_STATUS_TEXT = {
    "pending": "还在排队",
    "in_progress": "正在翻译",
    "completed": "已完成",
    "failed": "失败了",
    "cancelled": "已取消",
}


def _payload(args: object) -> dict:
    """`args` 可能是 None / 不是 dict（runtime 传什么进来都得接住）。"""
    return args if isinstance(args, dict) else {}


def _as_int(value: object) -> int | None:
    """模型偶尔把 id 说成字符串；容忍，但别把 bool 当数字。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _scope(ctx) -> dict:
    return ctx.scope if isinstance(ctx.scope, dict) else {}


def _target_id(ctx, payload: dict) -> int | None:
    """取任务 id：先看参数，再看页面带上来的 scope（正在读的那篇）。"""
    task_id = _as_int(payload.get("task_id"))
    if task_id is None:
        task_id = _as_int(_scope(ctx).get("task_id"))
    return task_id


def _describe(data: dict) -> str:
    text = _STATUS_TEXT.get(str(data["status"]), f"状态是 {data['status']}")
    if data["status"] == "in_progress":
        return f"{text}（{data['progress']:.0%}）"
    if data["status"] == "completed" and data["blocks"]:
        return f"{text}（{data['translated_blocks']}/{data['blocks']} 块有译文）"
    return text


def get_progress(ctx, args: dict | None = None) -> ToolResult:
    """读一篇的翻译进度（状态 / 百分比 / 阶段 / 预计剩余 / 语言对 / 档位 / 块数）。"""
    payload = _payload(args)
    task_id = _target_id(ctx, payload)
    if task_id is None:
        return ToolResult(
            data="没有指定 task_id", note="需要 task_id（先用 list_tasks 找到）"
        )

    with SessionLocal() as session:
        task = session.get(Task, task_id)
        # 归属：别人的文献一律当作「找不到」，别让模型从错误文案里猜出它存在
        if task is None or task.user_id != ctx.user_id:
            return ToolResult(data="找不到这篇文献", note="可能已删除，或不是你的文献")
        blocks, translated = session.execute(
            select(
                func.count(TaskBlock.id),
                # 只数有译文的块（COUNT(col) 不数 NULL）
                func.count(TaskBlock.translated),
            ).where(TaskBlock.task_id == task.id)
        ).one()
        data = {
            "task_id": task.id,
            "filename": task.filename,
            "status": task.status,
            "progress": round(float(task.progress or 0.0), 3),
            "stage": task.stage,
            "eta_seconds": task.eta_seconds,
            "source_lang": task.source_lang,
            "target_lang": task.target_lang,
            "tier": task.tier,
            # 页数没处算（任务表没有页数，块也不带页码），只给块数
            "blocks": int(blocks or 0),
            "translated_blocks": int(translated or 0),
        }
        if task.status == "failed":
            # 失败原因直接给模型：用户下一句多半是「为什么失败」
            data["error"] = (task.error_message or "")[:300]

    return ToolResult(data=data, note=_describe(data))


def request_retranslate(ctx, args: dict | None = None) -> ToolResult:
    """重译：**默认只解释**；只有 `confirm: true` 才把任务置回待处理。"""
    payload = _payload(args)
    task_id = _target_id(ctx, payload)
    if task_id is None:
        return ToolResult(
            data="没有指定 task_id", note="需要 task_id（先用 list_tasks 找到）"
        )

    # 先拦确认，再碰库：没确认时连任务存不存在都不该改变任何东西
    if payload.get("confirm") is not True:
        return ToolResult(data=_CONFIRM_HINT, note="没有确认，什么都没改")

    with SessionLocal() as session:
        task = session.get(Task, task_id)
        if task is None or task.user_id != ctx.user_id:
            return ToolResult(data="找不到这篇文献", note="可能已删除，或不是你的文献")

        previous = str(task.status)
        if previous in _ALREADY_MOVING:
            text = _STATUS_TEXT.get(previous, previous)
            return ToolResult(data=f"这篇{text}，不用重译", note="没有改任何东西")

        filename = task.filename
        task.status = "pending"
        task.progress = 0.0
        task.stage = None
        task.eta_seconds = None
        task.error_message = None
        task.finished_at = None
        session.commit()

    return ToolResult(
        data={
            "task_id": task_id,
            "filename": filename,
            "status": "pending",
            "previous_status": previous,
        },
        # 不调私有入队接口：只置状态，入队交给现有的重试链路（它会先清空旧块）
        note=(
            "已置为待处理：后台 worker 的空闲扫表会接手重跑（先清旧块）。"
            "界面上的「重试」能立刻入队。"
        ),
    )


PACK = Pack(
    name="translate",
    tools=(
        ToolSpec(
            name="get_progress",
            description=(
                "查一篇文献的翻译进度：状态、百分比、阶段、预计剩余秒数、"
                "语言对、档位、块数。用户问「翻译到哪了」时用。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "文献 id，可省略（默认看正在读的那篇）",
                    },
                },
                "additionalProperties": False,
            },
            handler=get_progress,
            max_result_chars=1200,
        ),
        ToolSpec(
            name="request_retranslate",
            description=(
                "重译一篇文献。**默认只解释、不执行**：只有用户明确确认后"
                "才可传 confirm=true，那时才会把任务置回待处理。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "文献 id"},
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": "用户明确确认后才传 true，否则不要传",
                    },
                },
                "required": ["task_id"],
                "additionalProperties": False,
            },
            handler=request_retranslate,
            max_result_chars=1200,
        ),
    ),
)
