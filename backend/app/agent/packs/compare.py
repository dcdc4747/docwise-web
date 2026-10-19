"""文献对比工具包：把两篇的导读与术语表摆在一起，算共有/独有术语。

用途：用户问「这两篇有什么不同 / 有什么相通的结论」时，让模型基于
**已经生成过的**导读与术语表做对比，而不是自己编。

口径：
- 只读：不写库、不调模型、不 import pydantic_ai；
- 归属：按 `ctx.user_id` 取文献，别人的一律当「找不到」；
- 导读缺失 / 术语缺失**如实标注**（`guide_missing` / `terms_missing`），
  一侧缺了就写 `None`，绝不拿另一侧的内容去填。
"""

from __future__ import annotations

import json

from sqlalchemy import select

from ...db import SessionLocal
from ...models import Task, TaskUnderstanding
from ..contracts import Pack, ToolResult, ToolSpec

# 导读的五个字段，与 `app/llm.py` 的 `_GUIDE_KEYS` 同口径；
# 老数据若还有别的键，排在后面一并对比。
_GUIDE_KEYS = (
    "research_question",
    "method",
    "conclusion",
    "innovation",
    "contribution",
)


def _json_obj(raw):
    """理解层存的是 JSON 字符串；读坏了返回 None，绝不抛异常。"""
    if isinstance(raw, (dict, list)):
        return raw
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _task_id(value) -> int | None:
    """args 容错：字符串数字也收，其它一律当没给。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ordered_keys(*guides: dict) -> list[str]:
    """已知五个字段优先，其余键按出现顺序补在后面（老数据兼容）。"""
    keys = [key for key in _GUIDE_KEYS if any(key in guide for guide in guides)]
    for guide in guides:
        for key in guide:
            if key not in keys:
                keys.append(key)
    return keys


def _guide_text(value) -> str:
    """导读字段的真实结构是 `{"text": …, "source_block_ids": […]}`。"""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            return text.strip()
    return ""


def _guide_texts(raw) -> dict[str, str]:
    """只收有非空文本的字段；空字段等同于「没有」。"""
    data = _json_obj(raw)
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key in _ordered_keys(data):
        text = _guide_text(data[key])
        if text:
            out[key] = text
    return out


def _terms_of(raw) -> dict[str, dict]:
    """术语表：`[{term, cn, definition}]`，也容忍 `{"terms": […]}` 与旧键名。"""
    data = _json_obj(raw)
    if isinstance(data, dict):
        data = data.get("terms") or []
    if not isinstance(data, list):
        return {}
    out: dict[str, dict] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        term = str(
            item.get("term") or item.get("source") or item.get("en") or ""
        ).strip()
        cn = str(item.get("cn") or item.get("target") or item.get("zh") or "")
        if not term:
            continue
        key = term.casefold()
        if key in out:
            continue
        out[key] = {"term": term, "cn": cn.strip()}
    return out


def _compare_terms(
    terms_a: dict[str, dict], terms_b: dict[str, dict]
) -> tuple[list[dict], list[dict], list[dict]]:
    """共同术语 / 只在 A / 只在 B；顺序按各自术语表原顺序。"""
    same: list[dict] = []
    only_a: list[dict] = []
    only_b: list[dict] = []
    for key, item in terms_a.items():
        other = terms_b.get(key)
        if other is None:
            only_a.append({"term": item["term"], "cn": item["cn"]})
            continue
        same.append(
            {
                "term": item["term"],
                "cn_a": item["cn"],
                "cn_b": other["cn"],
                "cn_matches": item["cn"] == other["cn"],
            }
        )
    for key, item in terms_b.items():
        if key not in terms_a:
            only_b.append({"term": item["term"], "cn": item["cn"]})
    return same, only_a, only_b


def _guide_diff(
    guide_a: dict[str, str], guide_b: dict[str, str]
) -> dict[str, dict]:
    """左右并排（不是只列差异）：相同与不同都要能回答「相通/不同」。

    一侧没有这个字段时写 `None`，并标 `same=False`——不拿另一侧的内容补。
    """
    diff: dict[str, dict] = {}
    for key in _ordered_keys(guide_a, guide_b):
        text_a = guide_a.get(key)
        text_b = guide_b.get(key)
        diff[key] = {
            "a": text_a,
            "b": text_b,
            "same": text_a == text_b,
        }
    return diff


def _read_side(db, task_id: int, user_id: int) -> dict | None:
    """读一篇；按 `user_id` 过滤，别人的当不存在（不区分，免得泄露存在性）。"""
    task = db.scalars(
        select(Task).where(Task.id == task_id, Task.user_id == user_id)
    ).first()
    if task is None:
        return None
    understanding = db.scalars(
        select(TaskUnderstanding).where(TaskUnderstanding.task_id == task.id)
    ).first()
    return {
        "task_id": task.id,
        "filename": task.filename,
        "guide": _guide_texts(
            understanding.guide_json if understanding else None
        ),
        "terms": _terms_of(understanding.terms_json if understanding else None),
        "status": understanding.status if understanding else None,
    }


def _side_view(side: dict) -> dict:
    return {
        "task_id": side["task_id"],
        "filename": side["filename"],
        "guide_keys": list(side["guide"]),
        "guide_missing": not side["guide"],
        "terms_missing": not side["terms"],
        "terms_count": len(side["terms"]),
        "understanding_status": side["status"],
    }


def compare_documents(ctx, args: dict | None = None) -> ToolResult:
    """对比两篇文献的导读字段与术语表；读不到就直说，不抛异常。"""
    payload = args if isinstance(args, dict) else {}
    task_a = _task_id(payload.get("task_a"))
    task_b = _task_id(payload.get("task_b"))
    if task_a is None or task_b is None:
        return ToolResult(
            data="需要两篇文献的编号（task_a 与 task_b）才能对比。",
            note="缺少 task_a / task_b",
        )

    with SessionLocal() as db:
        side_a = _read_side(db, task_a, ctx.user_id)
        side_b = _read_side(db, task_b, ctx.user_id)

    if side_a is None:
        return ToolResult(
            data=(
                f"找不到第 1 篇文献（编号 {task_a}）："
                "可能已删除，或不在你的库里。"
            ),
            note="第 1 篇读不到",
        )
    if side_b is None:
        return ToolResult(
            data=(
                f"找不到第 2 篇文献（编号 {task_b}）："
                "可能已删除，或不在你的库里。"
            ),
            note="第 2 篇读不到",
        )

    same, only_a, only_b = _compare_terms(side_a["terms"], side_b["terms"])
    data = {
        "a": _side_view(side_a),
        "b": _side_view(side_b),
        "same_terms": same,
        "only_a_terms": only_a,
        "only_b_terms": only_b,
        "guide_diff": _guide_diff(side_a["guide"], side_b["guide"]),
    }

    gaps: list[str] = []
    for label, side in (("第 1 篇", side_a), ("第 2 篇", side_b)):
        if not side["guide"]:
            gaps.append(f"{label}没有导读")
        if not side["terms"]:
            gaps.append(f"{label}没有术语表")
    if gaps:
        note = "；".join(gaps) + "（如实标注，未编造）"
    else:
        note = (
            f"共同术语 {len(same)} 条，"
            f"各自独有 {len(only_a)}/{len(only_b)} 条"
        )
    return ToolResult(data=data, note=note)


PACK = Pack(
    name="compare",
    tools=(
        ToolSpec(
            name="compare_documents",
            description=(
                "对比两篇文献的导读字段与术语表：哪些结论相近或不同、"
                "哪些术语两篇都有、哪些各自独有。导读/术语缺失会如实标注。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task_a": {
                        "type": "integer",
                        "description": "第 1 篇文献 id",
                    },
                    "task_b": {
                        "type": "integer",
                        "description": "第 2 篇文献 id",
                    },
                },
                "required": ["task_a", "task_b"],
            },
            handler=compare_documents,
            max_result_chars=6000,
        ),
    ),
)
