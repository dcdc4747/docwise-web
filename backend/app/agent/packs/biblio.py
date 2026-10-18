"""参考文献工具包：按 CSL 样式给草稿的引文排版（**只读**）。

排版的重活全在引擎侧：CSL 样式数据是第三方（CC BY-SA）的，只存在引擎目录。
这里**不重写**找脚本 / 起子进程 / 超时 / 退出码那套实现——直接复用
`routers/bibliography.py` 的端点函数（它是普通函数，可显式传 db/user/style 调用），
所以失败文案与接口**只有一处**来源，不会两边漂移。

口径：

- 只读：不写库、不改稿子、不改 `citations`；
- 归属：按 `ctx.user_id` 取草稿，别人的一律当「找不到」；
- 引擎没配好 / 脚本不存在 / 超时 / 退出码非 0 → `{"error": 人话}`，
  **不抛异常、不返回半成品**。

⚠️ 这个文件**不许 import pydantic_ai**（结构用例钉着）。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

from ...db import SessionLocal
from ...models import Draft
from ...routers import bibliography
from ...routers.bibliography import SUPPORTED_STYLES
from ..contracts import Pack, ToolResult, ToolSpec

_DEFAULT_STYLE = "gb-t-7714-2015-numeric"
_MAX_RESULT_CHARS = 6000
# 路由器里的引擎超时是 60 秒；工具自己的上限必须更宽，
# 否则引擎还在跑就被框架按默认 20 秒掐断。
_TOOL_TIMEOUT_MS = 70_000


@dataclass(frozen=True)
class _UserRef:
    """端点只读 `user.id`；一次只读调用不必再把 User 行查一遍。"""

    id: int


def _payload(args: dict | None) -> dict:
    """`args` 容错：None / 非 dict（模型传了奇怪形状）都当空参数。"""
    return args if isinstance(args, dict) else {}


def _scope(ctx) -> dict:
    return ctx.scope if isinstance(ctx.scope, dict) else {}


def _as_int(value) -> int | None:
    """宽松转 int；转不了返回 None，交给调用方说人话。bool 不算数字。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fail(message: str, note: str = "") -> ToolResult:
    """失败一律是 `{"error": 人话}`，绝不返回半成品。"""
    return ToolResult(data={"error": message}, note=note)


def _human_error(detail: object) -> str:
    """把路由的 503 detail 变成工具结果里的一句人话（保留可诊断的原因）。"""
    text = str(detail or "").strip()
    for prefix in ("参考文献格式化", "参考文献排版"):
        if text.startswith(prefix):
            text = text.removeprefix(prefix).lstrip("：: ")
            break
    return f"参考文献排版没跑成：{text or '引擎没有给出原因'}"


def format_bibliography(ctx, args: dict | None = None) -> ToolResult:
    """把当前草稿的引文按样式排成参考文献表（**只读**）。

    - `draft_id` 默认取页面带来的 `ctx.scope["draft_id"]`；
    - 样式只认 `SUPPORTED_STYLES`（常量直接从 router 导入，不抄一份）；
    - 成功返回 `{style, entries, count}`；失败返回 `{"error": 人话}`。
    """
    payload = _payload(args)
    draft_id = _as_int(payload.get("draft_id"))
    if draft_id is None:
        draft_id = _as_int(_scope(ctx).get("draft_id"))
    if draft_id is None:
        return _fail("没有指定草稿", "需要 draft_id（默认用当前草稿）")

    style = payload.get("style")
    style_key = (_DEFAULT_STYLE if style is None else str(style)).strip()
    if style_key not in SUPPORTED_STYLES:
        return _fail(
            f"样式不支持：{style_key or '(空)'}；"
            f"可选 {' / '.join(SUPPORTED_STYLES)}",
            "样式不在白名单里，没有去跑引擎",
        )

    with SessionLocal() as db:
        draft = db.get(Draft, draft_id)
        # 归属：别人的草稿一律当「找不到」，别让模型从文案里猜出它存在
        if draft is None or draft.user_id != ctx.user_id:
            return _fail("找不到这篇草稿", "可能已删除，或不是你的草稿")
        try:
            result = bibliography.draft_bibliography(
                draft_id,
                db=db,
                user=_UserRef(ctx.user_id),
                style=style_key,
            )
        except HTTPException as exc:
            if exc.status_code == 404:
                return _fail("找不到这篇草稿", "可能已删除，或不是你的草稿")
            return _fail(
                _human_error(exc.detail),
                "引擎这次没跑成，没有返回半成品",
            )
        except Exception as exc:  # noqa: BLE001 —— 工具不许把异常抛给整轮
            return _fail(
                "参考文献排版没跑成：工具内部出了点问题",
                f"{type(exc).__name__}: {exc}"[:200],
            )

    entries = result.get("entries") if isinstance(result, dict) else None
    if not isinstance(entries, list):
        return _fail(
            "参考文献排版没跑成：引擎返回的条目形状不对",
            "没有把半成品回给模型",
        )
    count = _as_int(result.get("count"))
    if count is None:
        count = len(entries)
    note = f"{count} 条参考文献" if count else "这篇草稿还没有引文"
    return ToolResult(
        data={"style": style_key, "entries": entries, "count": count},
        note=note,
    )


PACK = Pack(
    name="biblio",
    tools=(
        ToolSpec(
            name="format_bibliography",
            description=(
                "把当前草稿的引文按 CSL 样式排成参考文献表（只读，不改稿子与引文）。"
                f"样式可选：{' / '.join(SUPPORTED_STYLES)}。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "integer",
                        "description": "草稿 id（默认当前草稿）",
                    },
                    "style": {
                        "type": "string",
                        "enum": list(SUPPORTED_STYLES),
                        "default": _DEFAULT_STYLE,
                        "description": "CSL 样式 key（默认 GB/T 7714 顺序编码制）",
                    },
                },
                "additionalProperties": False,
            },
            handler=format_bibliography,
            max_result_chars=_MAX_RESULT_CHARS,
            timeout_ms=_TOOL_TIMEOUT_MS,
        ),
    ),
)
