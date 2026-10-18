"""`skills` 工具包：让模型按需取 skill 正文（渐进披露）。

只有一个工具 `use_skill(name)`：
- 只给**当前板块**的 skill（跨板块拿不到，避免写作时去翻"怎么精读"）；
- 正文截断到 `MAX_BODY_CHARS`，截断时如实标注；
- 一轮最多 2 个是 **prompt 规则**（工具层拿不到轮次计数），
  硬护栏是**正文长度上限**，那条绕不过去。

⚠️ 不许 import pydantic_ai（结构用例钉着）。
"""

from __future__ import annotations

from ..contracts import Pack, ToolResult, ToolSpec
from ..skills import MAX_BODY_CHARS, load_skills


def use_skill(ctx, args: dict | None = None) -> ToolResult:
    """按名字取 skill 正文（只在本板块可用范围内）。"""
    payload = args or {}
    name = str(payload.get("name") or "").strip()
    available = sorted(skill.name for skill in load_skills().values())

    if not name:
        return ToolResult(
            data={"available": available},
            note="要给技能名。可用：" + "、".join(available),
        )

    skill = load_skills().get(name)
    if skill is None:
        return ToolResult(data={"available": available}, note=f"没有这个技能：{name}")

    scene_id = getattr(ctx, "scene_id", "") or ""
    if scene_id and scene_id not in skill.applies_to:
        return ToolResult(
            data={"applies_to": list(skill.applies_to)},
            note=f"「{name}」不是这个板块的技能（适用：{'、'.join(skill.applies_to)}）",
        )

    body = (skill.body or "").strip()
    if not body:
        return ToolResult(data={}, note=f"「{name}」的正文是空的")

    truncated = len(body) > MAX_BODY_CHARS
    if truncated:
        body = body[:MAX_BODY_CHARS] + "\n\n（正文过长，已截断）"

    return ToolResult(
        data={
            "name": skill.name,
            "title": skill.title,
            "body": body,
            "checks": list(skill.checks),
            "truncated": truncated,
        },
        note=f"已加载技能：{skill.title}",
    )


PACK = Pack(
    name="skills",
    tools=(
        ToolSpec(
            name="use_skill",
            description=(
                "取本板块预装的「技能」详情（体例规则、排版规范、改稿协议等）。"
                "只在需要具体做法时调用；一轮最多取 2 个，别当百科翻。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "技能名，如 journal-format",
                    },
                },
                "required": ["name"],
            },
            handler=use_skill,
            max_result_chars=6000,
        ),
    ),
)
